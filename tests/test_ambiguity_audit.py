"""Human-audit infrastructure tested on constructed data/annotations, not real human labels."""
import copy
from pathlib import Path

import pytest

from aicr.ambiguity_audit import export_audit, read_audit_chunk, score_audit
from aicr.contracts import chunk
from aicr.io import digest, read_json, read_jsonl, write_json, write_jsonl


def audit_fixture(tmp_path, *, synthetic=True):
    data, run, output = tmp_path / 'data', tmp_path / 'run', tmp_path / 'audit'
    samples, cases, snapshots = [], [], {}
    for n in range(2):
        sid = 'fixture-' + str(n)
        text = 'def render(user):\n    return user.name\n'
        snapshot = {'id': 'snap-' + sid, 'commit_sha': str(n) * 40, 'partial': False,
                    'files': {p: {'text': t, 'text_sha256': digest(t)} for p, t in {
                        'target.py': text, 'caller.py': 'render(None)\n' if n == 0 else 'render(User())\n'}.items()}}
        sample = {'id': sid, 'provider': 'synthetic_fixture' if synthetic else 'github',
                  'comment_text': 'render can receive None and crash.', 'snapshot_id': snapshot['id'],
                  'original_commit_id': snapshot['commit_sha']}
        samples.append(sample)
        snapshots[snapshot['id']] = snapshot
        write_json(data / 'snapshots' / (snapshot['id'] + '.json'), snapshot)
        cases.append({'sample_id': sid, 'human': {'label': 'HIDDEN_H_SIGNAL', 'annotator_key': 'original-reviewer'},
                      'scale_id': 'comment-endorsement-v1', 'local_chunks': [chunk(snapshot, 'target.py', 1, 2)],
                      'core_claim': {'text': sample['comment_text'], 'claim_id': digest(sample['comment_text'])[:24]},
                      'candidate': n == 0, 'conclusion': 'model_supported_context_dependency' if n == 0 else 'not_selected',
                      'status': 'complete'})
    write_jsonl(data / 'normalized/samples.jsonl', samples)
    identity = {'protocol': 'ambiguity-1.0.1', 'selected': [s['id'] for s in samples],
                'sample_hashes': {s['id']: digest(s) for s in samples},
                'snapshot_hashes': {sid: digest((data / 'snapshots' / (sid + '.json')).read_text()) for sid in snapshots}}
    run_id = 'fixture-' + digest(identity)[:12]
    for c in cases:
        c['run_id'] = run_id
        write_json(run / c['sample_id'] / 'case.json', c)
    write_json(run / 'manifest.json', {'id': run_id, 'identity': identity, 'data_root': str(data)})
    write_json(run / 'case-hashes.json', {c['sample_id']: digest(c) for c in cases})
    export_audit([run], output)
    return run, output


def annotations(output, *, source='synthetic_test_fixture'):
    packets = read_jsonl(output / 'local/packets.jsonl')
    index = {r['packet_id']: r for r in read_json(output / 'private/index.json')}
    local, repository = [], []
    for p in packets:
        required = index[p['packet_id']]['candidate']
        base = {'audit_id': p['audit_id'], 'packet_id': p['packet_id'], 'source_kind': source,
                'annotator_key': 'fixture-auditor', 'rationale': 'Constructed annotation for infrastructure test.',
                'model_outputs_unseen': True, 'human_signal_unseen': True}
        local.append({**base, 'phase': 'local', 'decision': 'unknown', 'evaluability': 'insufficient'})
        c = read_audit_chunk(output, p['packet_id'], 'caller.py', 1, 1)
        repository.append({**base, 'phase': 'repository', 'decision': 'accept' if required else 'reject',
                           'context_dependency': 'required' if required else 'not_required',
                           'missing_premise': 'Whether a None caller exists' if required else None,
                           'evidence': [{k: c[k] for k in ['path', 'start_line', 'end_line', 'excerpt']}]})
    lp, rp = output / 'fixture-local.jsonl', output / 'fixture-repository.jsonl'
    write_jsonl(lp, local); write_jsonl(rp, repository)
    return lp, rp


def test_exports_candidates_and_controls_without_model_or_human_signal(tmp_path):
    run, output = audit_fixture(tmp_path)
    export_audit([run], output)  # identical export is idempotent
    local = (output / 'local/packets.jsonl').read_text()
    repo = (output / 'repository/packets.jsonl').read_text()
    for marker in ['HIDDEN_H_SIGNAL', 'candidate', 'model_confirmed', 'conclusion', 'original-reviewer', 'source_url']:
        assert marker not in local and marker not in repo
    assert len(read_jsonl(output / 'local/packets.jsonl')) == 2
    assert not (output / 'local/snapshots').exists()
    assert len(list((output / 'repository/snapshots').glob('*.json'))) == 2
    # The recipient can read evidence using only their blinded repository directory.
    import shutil
    recipient = tmp_path / 'reviewer-copy'
    shutil.copytree(output / 'repository', recipient)
    packet = read_jsonl(recipient / 'packets.jsonl')[0]
    assert read_audit_chunk(recipient, packet['packet_id'], 'target.py', 1, 2)['excerpt'].startswith('def render')
    assert not (recipient / 'private').exists()


def test_public_reader_rejects_modified_scope_and_escaping_path(tmp_path):
    _, output = audit_fixture(tmp_path)
    directory = output / 'repository'
    packets = read_jsonl(directory / 'packets.jsonl')
    packet = packets[0]
    with pytest.raises(ValueError, match='Unsafe repository path'):
        read_audit_chunk(directory, packet['packet_id'], '../secret', 1, 2)
    packet['snapshot_partial'] = not packet['snapshot_partial']
    write_jsonl(directory / 'packets.jsonl', packets)
    manifest = read_json(directory / 'manifest.json'); manifest['packets_hash'] = digest(packets)
    write_json(directory / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='scope metadata'):
        read_audit_chunk(directory, packet['packet_id'], 'target.py', 1, 2)


def test_synthetic_audit_never_enters_human_metrics(tmp_path):
    _, output = audit_fixture(tmp_path)
    local, repo = annotations(output)
    with pytest.raises(ValueError, match='allow-synthetic-test'):
        score_audit(output, local, repo)
    result = score_audit(output, local, repo, allow_synthetic=True)
    assert result['eligible_human_references'] == 0
    assert result['human_context_audit']['candidate']['precision'] is None
    assert result['synthetic_diagnostics']['candidate']['tp'] == 1
    assert result['synthetic_diagnostics']['candidate']['tn'] == 1
    # Merely typing human_manual does not turn synthetic *samples* into real human evaluation.
    local, repo = annotations(output, source='human_manual')
    result = score_audit(output, local, repo)
    assert result['eligible_human_references'] == 0


def test_human_reference_metrics_and_incomplete_audit_recall(tmp_path):
    # This fixture simulates a real provider solely to exercise scoring code; it is not exported as research data.
    _, output = audit_fixture(tmp_path, synthetic=False)
    local, repo = annotations(output, source='human_manual')
    result = score_audit(output, local, repo)
    assert result['human_context_audit']['candidate']['precision'] == 1
    assert result['human_context_audit']['candidate']['recall'] == 1
    assert result['audit_fully_resolved_by_humans'] and not result['population_performance_estimate']
    write_jsonl(repo, read_jsonl(repo)[:1])
    incomplete = score_audit(output, local, repo)
    assert incomplete['paired'] == 1 and incomplete['excluded'] == {'incomplete_pair': 1}
    assert incomplete['human_context_audit']['candidate']['recall'] is None


@pytest.mark.parametrize('change', ['quote', 'inside', 'blind', 'model', 'duplicate', 'phase', 'unknown'])
def test_invalid_annotations_are_not_silently_repaired(tmp_path, change):
    _, output = audit_fixture(tmp_path)
    local, repo = annotations(output)
    rows = read_jsonl(repo)
    row = next(r for r in rows if r['context_dependency'] == 'required')
    if change == 'quote': row['evidence'][0]['excerpt'] = 'made up'
    if change == 'inside': row['evidence'][0] = {'path': 'target.py', 'start_line': 1, 'end_line': 2, 'excerpt': 'def render(user):\n    return user.name'}
    if change == 'blind': row['human_signal_unseen'] = False
    if change == 'model': row['source_kind'] = 'model_generated'
    if change == 'duplicate': rows.append(copy.deepcopy(row))
    if change == 'phase': row['phase'] = 'local'
    if change == 'unknown': row['decision'] = 'unknown'
    write_jsonl(repo, rows)
    with pytest.raises(ValueError):
        score_audit(output, local, repo, allow_synthetic=True)


def test_previous_selector_is_excluded_from_independent_audit(tmp_path):
    _, output = audit_fixture(tmp_path, synthetic=False)
    local, repo = annotations(output, source='human_manual')
    rows = read_jsonl(repo)
    for row in rows: row['annotator_key'] = 'original-reviewer'
    write_jsonl(repo, rows)
    result = score_audit(output, local, repo)
    assert result['eligible_human_references'] == 0 and result['excluded'] == {'selection_annotator_reused': 2}


def test_export_and_reader_reject_modified_artifacts(tmp_path):
    run, output = audit_fixture(tmp_path)
    packet = read_jsonl(output / 'repository/packets.jsonl')[0]
    snap_path = output / 'repository' / packet['snapshot_ref']
    snapshot = read_json(snap_path)
    snapshot['partial'] = True
    write_json(snap_path, snapshot)
    with pytest.raises(ValueError, match='Snapshot changed'):
        read_audit_chunk(output, packet['packet_id'], 'caller.py', 1, 1)
    cpath = run / 'fixture-0/case.json'
    case = read_json(cpath); case['candidate'] = False; write_json(cpath, case)
    with pytest.raises(ValueError, match='Case changed'):
        export_audit([run], tmp_path / 'new-audit')


def test_duplicate_runs_or_examples_do_not_inflate_audit(tmp_path):
    run, output = audit_fixture(tmp_path)
    with pytest.raises(ValueError, match='Unique'):
        export_audit([run, run], output)
    import shutil
    duplicate = tmp_path / 'run-copy'
    shutil.copytree(run, duplicate)
    with pytest.raises(ValueError, match='Duplicate audit input'):
        export_audit([run, duplicate], tmp_path / 'duplicate-audit')
