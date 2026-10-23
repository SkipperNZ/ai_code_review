from __future__ import annotations

from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median

from .context import build_context
from .io import ROOT, now, read_json, read_jsonl, write_json, write_jsonl, atomic_text, digest
from .contracts import validate_assessment
from .audit import signal_state
from .runner import select_samples


def latest_results(directory: Path) -> list[dict]:
    latest = {}
    for path in sorted(directory.glob('*/**/result.json')):
        r = read_json(path)
        key = (r['sample_id'], r['mode'])
        if key not in latest or r['finished_at'] > latest[key]['finished_at']:
            latest[key] = r
    return list(latest.values())


def evaluate(directory: Path, human: Path | None = None, data: Path | None = None) -> dict:
    manifest = read_json(directory / 'manifest.json')
    results = latest_results(directory)
    metrics = {'run_id': manifest['id'], 'evaluated_at': now(), 'human_reference_available': False,
               'quality_improvement_claim': 'not_measured', 'latency_quantile_method': 'nearest_rank',
               'modes': {}, 'paired_verdict_transitions': {}}
    assessments = {}
    for r in results:
        if r['status'] == 'ok':
            assessments[(r['sample_id'], r['mode'])] = read_json(r['assessment_ref'])
    for mode in manifest['modes']:
        rows = [r for r in results if r['mode'] == mode]
        times = sorted(r['wall_seconds'] for r in rows)
        n = len(rows)
        accepted = [assessments[(r['sample_id'], mode)] for r in rows if (r['sample_id'], mode) in assessments]
        metrics['modes'][mode] = {'planned': len(manifest['selected']), 'completed': n, 'statuses': dict(Counter(r['status'] for r in rows)),
            'raw_schema_valid': sum(r.get('validation', {}).get('raw_schema_valid', False) for r in rows) if manifest['config'].get('response_contract') else None,
            'schema_valid': sum(r.get('validation', {}).get('schema_valid', False) for r in rows),
            'semantic_valid': sum(r.get('validation', {}).get('semantic_valid', False) for r in rows),
            'evidence_valid': sum(r.get('validation', {}).get('evidence_valid', False) for r in rows),
            'valid_yield': len(accepted) / len(manifest['selected']) if manifest['selected'] else None,
            'verdicts': dict(Counter(a['correctness']['value'] for a in accepted)),
            'actions': dict(Counter(a['utility']['recommended_action'] for a in accepted)),
            'strict_eligible_completed': sum(r['strict_eligible'] for r in rows),
            'p50_seconds': median(times) if times else None,
            'p95_seconds': times[ceil(len(times) * .95) - 1] if times else None,
            'tool_calls': sum(r.get('tool_calls', 0) for r in rows), 'generated_tokens': sum(r.get('generated_tokens', 0) for r in rows)}
    transitions = Counter()
    for sid in manifest['selected']:
        local, agent = assessments.get((sid, 'local')), assessments.get((sid, 'agent'))
        if local and agent:
            transitions[local['correctness']['value'] + ' -> ' + agent['correctness']['value']] += 1
    metrics['paired_verdict_transitions'] = dict(transitions)
    metrics['engineering_gate'] = {'minimum_samples_per_mode': 40, 'minimum_schema_valid_rate': .95,
        'passed': all(metrics['modes'].get(m, {}).get('completed', 0) >= 40 and
                      (metrics['modes'][m]['raw_schema_valid'] if metrics['modes'][m]['raw_schema_valid'] is not None else metrics['modes'][m]['schema_valid']) / metrics['modes'][m]['planned'] >= .95 for m in ['local', 'agent'])}
    metrics['engineering_gate']['basis'] = 'raw_model_schema_valid' if manifest['config'].get('response_contract') else 'legacy_full_assessment_schema_valid'
    metrics['model_confidence_calibrated'] = False
    metrics['cost_status'] = 'api_cost_not_metered_local_compute_cost_unknown'
    for mode, m in metrics['modes'].items():
        m['schema_valid_rate'] = m['schema_valid'] / m['planned'] if m['planned'] else None
        m['format_repairs'] = sum(r.get('format_repair', False) for r in results if r['mode'] == mode)
        m['uncertainty_reasons'] = dict(Counter(u for (sid, mod), a in assessments.items() if mod == mode for u in a['uncertainty_reasons']))
    if data and (data / 'signals/user-signals.jsonl').exists():
        states = {s['sample_id']: signal_state(s) for s in read_jsonl(data / 'signals/user-signals.jsonl')}
        metrics['selected_signal_states'] = dict(Counter(states.get(sid, 'unavailable') for sid in manifest['selected']))
        metrics['reaction_noise_estimate'] = None
    if human:
        if not data:
            raise ValueError('Data root required for human reference validation')
        metrics['human_comparison'] = compare_humans(human, assessments, manifest['selected'], data)
        metrics['human_reference_available'] = bool(metrics['human_comparison']['accepted_annotations'])
    write_json(directory / 'metrics.json', metrics)
    human_note = 'Есть валидированные human annotations; agreement см. в metrics.json. Причинный эффект на продукт не измерен.' if metrics['human_reference_available'] else 'Ручного reference нет. Изменение verdict не является измеренным улучшением качества.'
    lines = ['# Инженерные результаты прототипа', '', human_note, '',
             '| Режим | Запланировано | Завершено | Принято | Raw JSON valid | Final schema valid | p50 s |', '| --- | --- | --- | --- | --- | --- | --- |']
    for mode, m in metrics['modes'].items():
        lines.append(f'| {mode} | {m["planned"]} | {m["completed"]} | {m["statuses"].get("ok", 0)} | {m["raw_schema_valid"] if m["raw_schema_valid"] is not None else "legacy"} | {m["schema_valid"]} | {m["p50_seconds"]} |')
    lines += ['', 'Полные статусы, неопределённость и переходы сохранены в metrics.json. Проверка evidence здесь подтверждает ссылки и точность цитат, не истинность выводов.']
    atomic_text(directory / 'SUMMARY.md', '\n'.join(lines) + '\n')
    cases = []
    for sid in manifest['selected']:
        values = {m: assessments[(sid, m)] for m in manifest['modes'] if (sid, m) in assessments}
        if values:
            cases.append({'sample_id': sid, 'kind': 'model_generated_not_human_verified', 'assessments': values})
    write_jsonl(directory / 'cases.jsonl', cases)
    return metrics


def compare_humans(path: Path, predictions: dict, selected: list, data: Path) -> dict:
    """Report agreement only on explicitly human, evidence-validated annotations."""
    references, rejected = {}, []
    accepted = 0
    sample_snapshots = {s['id']: s['snapshot_id'] for s in read_jsonl(data / 'normalized/samples.jsonl')}
    for row in read_jsonl(path):
        sid = row.get('sample_id')
        if row.get('annotation_source') != 'human' or not row.get('annotator_key') or row.get('annotation_stage') != 'repository' or not row.get('assessment'):
            rejected.append({'sample_id': sid, 'reason': 'requires_completed_human_repository_annotation'})
            continue
        if sid not in selected:
            continue
        if row.get('snapshot_id') != sample_snapshots.get(sid):
            rejected.append({'sample_id': sid, 'reason': 'snapshot does not belong to sample'})
            continue
        snapshot = read_json(data / 'snapshots' / (row['snapshot_id'] + '.json'))
        a = row['assessment']
        validation = validate_assessment(a, snapshot, row.get('shown_chunks', []), sample_id=sid, run_id=a.get('run_id'), mode='agent')
        if not all(validation[k] for k in ['schema_valid', 'semantic_valid', 'evidence_valid']):
            rejected.append({'sample_id': sid, 'reason': validation['errors']})
            continue
        references.setdefault(sid, {})[row['annotator_key']] = a
        accepted += 1
    # No majority-vote relabeling: disagreement is reported and excluded from consensus.
    consensus = {sid: next(iter(rows.values())) for sid, rows in references.items()
                 if len({a['correctness']['value'] for a in rows.values()}) == 1}
    disputed = sorted(set(references) - set(consensus))
    modes = {}
    for mode in ['local', 'static', 'agent']:
        pairs = [(predictions[(sid, mode)], ref) for sid, ref in consensus.items() if (sid, mode) in predictions]
        matches = sum(p['correctness']['value'] == h['correctness']['value'] for p, h in pairs)
        modes[mode] = {'paired': len(pairs), 'correctness_agreement': matches / len(pairs) if pairs else None,
                      'confusion': dict(Counter(h['correctness']['value'] + ' -> ' + p['correctness']['value'] for p, h in pairs))}
    revisions = Counter()
    for sid, ref in consensus.items():
        if (sid, 'local') in predictions and (sid, 'agent') in predictions:
            l = predictions[(sid, 'local')]['correctness']['value'] == ref['correctness']['value']
            a = predictions[(sid, 'agent')]['correctness']['value'] == ref['correctness']['value']
            revisions['both_match' if l and a else 'beneficial' if a else 'harmful' if l else 'neither_matches'] += 1
    return {'accepted_annotations': accepted, 'unique_samples': len(references), 'consensus_samples': len(consensus),
            'disputed_samples': disputed, 'single_annotator_samples': sum(len(r) == 1 for r in references.values()),
            'rejected': rejected, 'modes': modes, 'paired_revisions': dict(revisions),
            'interpretation': 'human agreement; no causal quality-improvement or reaction-noise claim'}


def export_human(data: Path, samples: list[dict], output: Path, limit: int) -> dict:
    selected = select_samples(samples, limit)
    packets = []
    for sample in selected:
        snapshot = read_json(data / 'snapshots' / (sample['snapshot_id'] + '.json'))
        context = build_context(sample, snapshot, 'local')
        packets.append({'sample_id': sample['id'], 'rubric_version': 'prototype-rubric-v1', 'blind_stage': 'local_first',
                        'annotation_source': 'human', 'annotation_stage': 'local', 'snapshot_id': snapshot['id'],
                        'input': context, 'shown_chunks': context['chunks'], 'annotator_key': None, 'assessment': None})
    write_jsonl(output, packets)
    index = [{'sample_id': s['id'], 'repo_id': s['repo_id'], 'pr_number': s['pr_number'], 'source_url': s['source_url'],
              'strict_eligible': s['strict_eligible'], 'body_history_status': s['body_history_status'],
              'group': digest([s['repo_id'], s['pr_number']])[:16], 'use': 'development_only_no_locked_test_claim'} for s in selected]
    write_json(output.with_suffix('.index.json'), {'selection': 'deterministic_repo_round_robin_no_signal_selection',
                'split_status': 'development_only; independent future PR/repository holdout not yet collected', 'samples': index})
    return {'packets': len(packets), 'output': str(output), 'status': 'awaiting_human_annotations', 'locked_test_samples': 0}
