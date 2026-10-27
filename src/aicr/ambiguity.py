"""Independent L/R -> post-hoc H -> blinded verification and context-addition control."""
import copy
import json
import re
from collections import Counter
from pathlib import Path

from .ambiguity_contracts import (PROTOCOL, SCALE, STAGES, candidate_rule, load_humans,
                                 materialize_links, reaction_proxy, schema_for, snippet_for, validate_stage)
from .io import ROOT, atomic_text, digest, now, queue_lock, read_json, read_jsonl, safe_repo_path, write_json, write_jsonl
from .pi_runtime import execute_pi
from .runner import code_hash, doctor, select_samples, source_files

# Refuse an in-process run after files changed since this module was imported.
# Every production CLI starts fresh; this also catches notebook/test-service misuse.
_LOADED_SOURCE_HASH = code_hash()


def _stage(stage: str, context: dict, sample: dict, snapshot: dict, config: dict, run_id: str,
           directory: Path, execution: Path, local: list[dict], snapshot_hash: str, retry_failed: bool, activity: dict) -> dict:
    kind = STAGES[stage]
    prompt = {'claim': 'ambiguity-claim.txt', 'assessment': 'ambiguity-assess.txt', 'verification': 'ambiguity-verify.txt'}[kind]
    mode = 'agent' if stage in ('R', 'V') else 'local'
    limits = dict(config['limits'])
    if mode == 'local':
        limits.update(max_turns=2, max_tool_calls=0, wall_seconds=min(180, limits['wall_seconds']))
    # Visible identity must not depend even indirectly on H or a descriptive run name.
    # H stays in the outer run manifest; it cannot perturb an otherwise identical L/R request.
    job = {'task': 'Return the requested protocol result using only the supplied input and schema.',
           'sample_id': digest(sample['id'])[:24], 'run_id': digest([PROTOCOL, snapshot_hash])[:24], 'mode': mode, 'context': context,
           'snapshot': snapshot, 'limits': limits,
           'system_prompt': (execution / 'prompts' / prompt).read_text(encoding='utf-8'),
           'schema': schema_for(kind, execution),
           'model': {k: config['model'][k] for k in ('base_url', 'id', 'context_window', 'max_output_tokens', 'chat_template_kwargs') if k in config['model']}}
    fingerprint = digest({**{k: v for k, v in job.items() if k != 'snapshot'}, 'snapshot_hash': snapshot_hash})
    attempts = sorted(directory.glob('attempt-*'), key=lambda p: int(p.name.split('-')[-1]))
    for attempt in reversed(attempts):
        if not (attempt / 'result.json').exists():
            continue
        saved = read_json(attempt / 'result.json')
        if saved['input_hash'] != fingerprint:
            raise RuntimeError('Stage input changed under an existing run identity')
        if (saved.get('run_id'), saved.get('sample_id'), saved.get('stage')) != (run_id, sample['id'], stage):
            raise RuntimeError('Saved stage identity changed')
        if saved['status'] == 'ok' or not retry_failed:
            if saved['status'] == 'ok':
                response, shown = read_json(attempt / 'response.json'), read_json(attempt / 'shown-chunks.json')
                if digest(response) != saved['response_hash'] or digest(saved['assessment']) != saved['response_hash'] or digest(shown) != saved['shown_hash']:
                    raise RuntimeError('Saved stage artifacts changed')
            return saved
        break
    number = int(attempts[-1].name.split('-')[-1]) + 1 if attempts else 1
    attempt = directory / f'attempt-{number}'
    job['runtime_dir'] = str((attempt / 'runtime').resolve())
    transport = execute_pi(job, config, attempt, execution)
    final = transport['final']
    activity['stages_executed_now'] += 1
    activity['model_requests_now'] += final.get('requests', 0) if final else 0
    result = {'protocol': PROTOCOL, 'stage': stage, 'run_id': run_id, 'sample_id': sample['id'], 'input_hash': fingerprint,
              'directory': str(attempt.resolve()), 'finished_at': now(), 'wall_seconds': transport['wall_seconds'],
              'status': transport['transport_status'] or 'endpoint_error', 'assessment': None,
              'requests': 0, 'tool_calls': 0, 'generated_tokens': 0, 'format_repair': False}
    if final:
        result.update({k: final[k] for k in ('requests', 'tool_calls', 'generated_tokens', 'format_repair')})
        result['status'] = transport['transport_status'] or final['status']
        if not transport['transport_status'] and final.get('assessment') is not None:
            value, shown = final['assessment'], final['shown_chunks']
            validation = validate_stage(kind, value, snapshot, shown, local, sample['comment_text'], job['schema'])
            result['validation'] = validation
            result['status'] = ('json_invalid' if not validation['schema_valid'] else
                                'evidence_invalid' if not validation['evidence_valid'] else
                                'consistency_invalid' if not validation['consistency_valid'] else 'ok')
            if result['status'] == 'ok':
                result.update(assessment=value, response_hash=digest(value), shown_hash=digest(shown))
                write_json(attempt / 'response.json', value)
                write_json(attempt / 'evidence.json', materialize_links(value, shown, local))
    # Provider statuses never become a decision. The raw candidate remains in its own artifact.
    if result['status'] == 'candidate':
        result['status'] = 'endpoint_error'
    write_json(attempt / 'result.json', result)
    return result


def _assessment(stage: dict | None) -> dict | None:
    return stage['assessment'] if stage and stage['status'] == 'ok' else None


def _base_context(sample: dict, local: list[dict], claim: dict) -> dict:
    return {'input_contract': 'ambiguity-blinded-1', 'comment': sample['comment_text'],
            'core_claim': claim, 'chunks': copy.deepcopy(local)}


def _sample_run(sample, snapshot, config, run_id, directory, execution, human, snapshot_hash, retry_failed, activity):
    row = {'protocol': PROTOCOL, 'sample_id': sample['id'], 'run_id': run_id, 'scale_id': SCALE,
           'source_url': sample.get('source_url'), 'strict_eligible': sample.get('strict_eligible', False),
           'human': human, 'stages': {}, 'candidate': False, 'conclusion': 'not_evaluated',
           'ambiguity_gold_label': None, 'annotation_source': 'model_generated_not_human_context_audit'}
    try:
        c, policy = snippet_for(sample, snapshot, config.get('ambiguity', {}).get('max_local_lines', 160))
    except (ValueError, KeyError, TypeError) as exc:
        row.update(status='input_unavailable', conclusion='input_unavailable', error=str(exc))
        return row
    local = [c]
    row.update(local_chunks=local, snippet_policy=policy,
               local_input_hash=digest({'comment': sample['comment_text'], 'chunks': local}),
               student_features_hash=digest({'comment': sample['comment_text'], 'snippet': c['excerpt']}))
    def stage(name, context):
        result = _stage(name, context, sample, snapshot, config, run_id, directory / name, execution, local, snapshot_hash, retry_failed, activity)
        row['stages'][name] = result
        print(json.dumps({'event': 'ambiguity_stage', 'sample_id': sample['id'], 'stage': name, 'status': result['status']}), flush=True)
        return result
    extraction = stage('E', {'input_contract': 'ambiguity-extraction-1', 'comment': sample['comment_text'], 'chunks': []})
    claim = _assessment(extraction)
    if not claim or claim['status'] != 'identified':
        row.update(status='claim_unavailable', conclusion='claim_unavailable')
        return row
    shared_claim = {'claim_id': digest(claim['claim_excerpt'])[:24], 'text': claim['claim_excerpt']}
    row['core_claim'] = shared_claim
    # Separate sessions with identical comment, fixed snippet and shared extracted excerpt.
    base = _base_context(sample, local, shared_claim)
    l = stage('L', base)
    r = stage('R', {**copy.deepcopy(base), 'snapshot_id': snapshot['id'], 'snapshot_partial': snapshot['partial']})
    comparison = candidate_rule(_assessment(l), _assessment(r), human)
    row.update(status='complete', comparison=comparison, candidate=comparison['candidate'])
    if not _assessment(l) or not _assessment(r):
        row['status'] = 'assessment_failure'
    if not comparison['candidate']:
        row['conclusion'] = 'assessment_unavailable' if row['status'] == 'assessment_failure' else 'not_selected'
        return row
    # L_repeat receives the same context and rubric as L; not its earlier answer.
    repeat = stage('L_repeat', copy.deepcopy(base))
    row['local_repeat_changed'] = (repeat['assessment']['decision'] != l['assessment']['decision']) if _assessment(repeat) else None
    repository_chunks = read_json(Path(r['directory']) / 'shown-chunks.json')
    cited = {e['source_chunk_id'] for e in r['assessment']['evidence_links']}
    leads = [s for s in repository_chunks if s['source_chunk_id'] in cited and s['source_chunk_id'] != c['source_chunk_id']]
    # Leads carry code only, never the relation, rationale, prior decision or human label.
    v_context = {**copy.deepcopy(base), 'local_chunk_ids': [c['source_chunk_id']],
                 'chunks': local + leads, 'snapshot_id': snapshot['id'], 'snapshot_partial': snapshot['partial']}
    v = stage('V', v_context)
    verification = _assessment(v)
    if not verification:
        row['conclusion'] = 'verification_unavailable'
        return row
    row['verification_outcome'] = verification['outcome']
    if verification['outcome'] != 'context_dependency_supported':
        row['conclusion'] = verification['outcome']
        return row
    if verification['resolved_decision'] != r['assessment']['decision']:
        row['conclusion'] = 'verifier_disagrees_with_repository'
        return row
    v_chunks = read_json(Path(v['directory']) / 'shown-chunks.json')
    decisive = {e['source_chunk_id'] for e in verification['decisive_links']}
    additions = [s for s in v_chunks if s['source_chunk_id'] in decisive]
    addition = stage('L_plus_context', {**copy.deepcopy(base), 'evidence_condition': 'snippet_plus_selected_context', 'chunks': local + additions})
    row['context_addition_matches_repository'] = (addition['assessment']['decision'] == r['assessment']['decision']) if _assessment(addition) else None
    if row['local_repeat_changed'] is not False:
        row['conclusion'] = 'local_instability_or_repeat_unavailable'
    elif row['context_addition_matches_repository'] is not True:
        row['conclusion'] = 'context_addition_not_corroborated'
    else:
        row['conclusion'] = 'model_supported_context_dependency'
    return row


def run_ambiguity(data: Path, runs: Path, config: dict, *, name='ambiguity', limit=4, human_file=None,
                  use_reaction_proxy=False, only_with_human=False, sample_ids=None, strict=False,
                  retry_failed=False, synthetic_demo=False) -> dict:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) or limit < 1:
        raise ValueError('Safe run name and positive limit required')
    if human_file and use_reaction_proxy:
        raise ValueError('Choose a human file OR the explicit reaction-proxy mapping')
    if synthetic_demo and not human_file:
        raise ValueError('Synthetic demo requires explicitly tagged synthetic references')
    human_rows = load_humans(human_file, allow_synthetic=synthetic_demo) if human_file else {}
    signal_path = data / 'signals/user-signals.jsonl'
    signals = {s['sample_id']: s for s in read_jsonl(signal_path)} if use_reaction_proxy and signal_path.exists() else {}
    samples = read_jsonl(data / 'normalized/samples.jsonl')
    if len({s['id'] for s in samples}) != len(samples):
        raise ValueError('Duplicate normalized sample identity')
    if sample_ids:
        if len(sample_ids) != len(set(sample_ids)):
            raise ValueError('Duplicate explicit sample ID')
        samples = [s for s in samples if s['id'] in sample_ids]
        if len(samples) != len(sample_ids):
            raise ValueError('Every explicit sample ID must resolve uniquely')
    def human_for(sid):
        return reaction_proxy(sid, signals.get(sid), str(signal_path.resolve())) if use_reaction_proxy else human_rows.get(sid,
            {'sample_id': sid, 'scale_id': SCALE, 'label': 'unknown', 'source_kind': 'unavailable', 'human_verified': False})
    if only_with_human:
        samples = [s for s in samples if human_for(s['id'])['label'] != 'unknown']
    selected = select_samples(samples, limit, strict)
    if not selected:
        raise ValueError('No eligible samples; no model requests made')
    if any(s.get('provider') == 'synthetic_fixture' for s in selected) and not synthetic_demo:
        raise ValueError('Synthetic fixtures require --synthetic-demo; they are not real samples')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', s['id']) for s in selected):
        raise ValueError('Unsafe sample ID')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', s.get('snapshot_id', '')) or
           not re.fullmatch(r'[0-9a-f]{40}', s.get('original_commit_id') or '') or
           not safe_repo_path(s['path']) for s in selected):
        raise ValueError('Unsafe snapshot identity, historical SHA or anchor path')
    with queue_lock(runs / '.queue.lock'):
        source_texts = {str(p.relative_to(ROOT)): p.read_text(encoding='utf-8') for p in source_files()}
        captured_hash = digest({p: digest(t) for p, t in source_texts.items()})
        if captured_hash != _LOADED_SOURCE_HASH:
            raise RuntimeError('Source changed after Python import; start a fresh CLI process')
        health = doctor(config)
        if not health['ok']:
            raise RuntimeError('Model preflight failed: ' + str(health.get('error', health.get('http_status'))))
        hashes = {s['snapshot_id']: digest((data / 'snapshots' / (s['snapshot_id'] + '.json')).read_text(encoding='utf-8')) for s in selected}
        humans = {s['id']: human_for(s['id']) for s in selected}
        identity = {'protocol': PROTOCOL, 'scale_id': SCALE, 'code_hash': captured_hash, 'config': config,
                    'deployment': health['deployment_fingerprint'], 'selected': [s['id'] for s in selected],
                    'sample_hashes': {s['id']: digest(s) for s in selected}, 'snapshot_hashes': hashes,
                    'human_hashes': {sid: digest(h) for sid, h in humans.items()}, 'strict_only': strict,
                    'synthetic_demo': synthetic_demo}
        run_id = name + '-' + digest(identity)[:12]
        directory = runs / run_id
        directory.mkdir(parents=True, exist_ok=True)
        existing = directory / 'manifest.json'
        if existing.exists() and read_json(existing)['identity'] != identity:
            raise RuntimeError('Run identity collision')
        if not existing.exists():
            write_json(existing, {'id': run_id, 'identity': identity, 'doctor': health, 'data_root': str(data.resolve()), 'created_at': now()})
        human_input = directory / 'human-inputs.jsonl'
        if human_input.exists():
            saved_humans = {h['sample_id']: h for h in read_jsonl(human_input)}
            if saved_humans != humans:
                raise RuntimeError('Frozen human inputs changed')
        else:
            write_jsonl(human_input, list(humans.values()))
        execution = directory / 'execution'
        # Hash and copy the same captured bytes, rather than rereading mutable files.
        for relative, content in source_texts.items():
            target = execution / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and digest(target.read_text(encoding='utf-8')) != digest(content):
                raise RuntimeError('Frozen execution bundle changed')
            if not target.exists():
                atomic_text(target, content)
        case_hash_path = directory / 'case-hashes.json'
        case_hashes = read_json(case_hash_path) if case_hash_path.exists() else {}
        activity = {'stages_executed_now': 0, 'model_requests_now': 0}
        for sample in selected:
            path = data / 'snapshots' / (sample['snapshot_id'] + '.json')
            if digest(path.read_text(encoding='utf-8')) != hashes[sample['snapshot_id']]:
                raise RuntimeError('Snapshot changed during experiment')
            snapshot = read_json(path)
            if snapshot['id'] != sample['snapshot_id'] or snapshot['commit_sha'] != sample['original_commit_id']:
                raise ValueError('Snapshot identity differs from historical sample')
            if any(not safe_repo_path(p) or digest(f['text']) != f['text_sha256'] for p, f in snapshot['files'].items()):
                raise ValueError('Snapshot file identity/hash invalid')
            case = _sample_run(sample, snapshot, config, run_id, directory / sample['id'], execution,
                               humans[sample['id']], hashes[sample['snapshot_id']], retry_failed, activity)
            write_json(directory / sample['id'] / 'case.json', case)
            case_hashes[sample['id']] = digest(case)
            write_json(case_hash_path, case_hashes)
        metrics = evaluate_ambiguity(directory)
    return {'run_id': run_id, 'directory': str(directory.resolve()), 'executed_now': activity, 'metrics': metrics}


def evaluate_ambiguity(directory: Path) -> dict:
    manifest = read_json(directory / 'manifest.json')
    if manifest['identity']['protocol'] not in {'ambiguity-1.0.0', 'ambiguity-1.0.1', PROTOCOL}:
        raise ValueError('Not an ambiguity run')
    rows = []
    case_hashes = read_json(directory / 'case-hashes.json')
    for sid in manifest['identity']['selected']:
        path = directory / sid / 'case.json'
        if path.exists():
            row = read_json(path)
            if digest(row) != case_hashes.get(sid):
                raise ValueError('Case contents changed since completion')
            if row['sample_id'] != sid or row['run_id'] != manifest['id'] or digest(row['human']) != manifest['identity']['human_hashes'][sid]:
                raise ValueError('Case identity or human provenance changed')
            rows.append(row)
    stages = [stage for row in rows for stage in row['stages'].values()]
    metrics = {'protocol': manifest['identity']['protocol'], 'run_id': manifest['id'], 'evaluated_at': now(),
               'planned': len(manifest['identity']['selected']), 'completed': len(rows),
               'statuses': dict(Counter(r['status'] for r in rows)),
               'human_sources': dict(Counter(r['human']['source_kind'] for r in rows)),
               'candidates': sum(r['candidate'] for r in rows),
               'candidate_kinds': dict(Counter(r['comparison']['kind'] for r in rows if r['candidate'])),
               'conclusions': dict(Counter(r['conclusion'] for r in rows)),
               'stage_statuses': {name: dict(Counter(s['status'] for s in stages if s['stage'] == name)) for name in STAGES},
               'model_requests': sum(s['requests'] for s in stages), 'tool_calls': sum(s['tool_calls'] for s in stages),
               'generated_tokens': sum(s['generated_tokens'] for s in stages),
               'wall_seconds': round(sum(s['wall_seconds'] for s in stages), 3),
               'format_repairs': sum(s['format_repair'] for s in stages),
               'human_context_reference_available': False, 'detector_precision': None, 'detector_recall': None,
               'classifier_trained': False, 'source_labels_modified': False,
               'scope': 'model_generated_candidates_and_controls; H proxy/manual endorsement is not context-dependency ground truth'}
    write_json(directory / 'ambiguity-metrics.json', metrics)
    write_jsonl(directory / 'ambiguity-cases.jsonl', rows)
    write_jsonl(directory / 'ambiguity-candidates.jsonl', [r for r in rows if r['candidate']])
    text = ['# L/R/H experiment', '', f"Run: `{manifest['id']}`; completed {len(rows)}/{metrics['planned']}.", '',
            f"Candidates H=R≠L: {metrics['candidates']}. Conclusions: {metrics['conclusions']}.", '',
            'Candidates and verification results are model-generated. A human endorsement/proxy used for selection '
            'is not an independent human context-dependency annotation. Precision/recall are not measured. '
            'No classifier was trained and no original labels were modified.']
    atomic_text(directory / 'AMBIGUITY-SUMMARY.md', '\n'.join(text) + '\n')
    return metrics
