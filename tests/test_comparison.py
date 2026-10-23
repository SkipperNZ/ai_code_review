import pytest

from aicr.comparison import compare_runs
from aicr.io import read_json, write_json


def make_run(directory, selected, statuses):
    write_json(directory / 'manifest.json', {'id': directory.name, 'modes': ['agent'], 'selected': selected,
               'sample_hashes': {sid: 'hash-' + sid for sid in selected}, 'snapshot_hashes': {'snap': 'hash'},
               'code_hash': directory.name, 'deployment': 'same-metadata'})
    for sid, status in statuses.items():
        write_json(directory / sid / 'agent/attempt-1/result.json', {
            'sample_id': sid, 'mode': 'agent', 'run_id': directory.name, 'finished_at': '2026-01-01',
            'status': status, 'wall_seconds': 10, 'tool_calls': 2,
            'validation': {'raw_schema_valid': True, 'evidence_valid': status != 'evidence_invalid'}})


def test_comparison_uses_same_pairs_and_preserves_pending(tmp_path):
    b, c = tmp_path / 'before', tmp_path / 'after'
    make_run(b, ['s1', 's2', 's3', 'extra'], {'s1': 'evidence_invalid', 's2': 'ok', 's3': 'ok', 'extra': 'ok'})
    make_run(c, ['s1', 's2', 's3'], {'s1': 'ok', 's2': 'semantic_invalid'})
    r = compare_runs(b, c)
    assert r['planned_common'] == 3 and r['completed_pairs'] == 2
    assert r['recovered'] == r['regressed'] == 1
    assert r['summary']['baseline']['completed_pairs_ok'] == 1
    assert r['summary']['candidate']['statuses']['pending'] == 1
    assert r['model_quality_change'] is None
    assert r['baseline_only_selected'] == 1


@pytest.mark.parametrize('key', ['sample_hashes', 'snapshot_hashes'])
def test_comparison_rejects_changed_captures(tmp_path, key):
    b, c = tmp_path / 'before', tmp_path / 'after'
    make_run(b, ['s1'], {'s1': 'ok'}); make_run(c, ['s1'], {'s1': 'ok'})
    m = read_json(c / 'manifest.json')
    m[key][next(iter(m[key]))] = 'different'
    write_json(c / 'manifest.json', m)
    with pytest.raises(ValueError, match='changed'):
        compare_runs(b, c)


def test_comparison_refuses_foreign_result(tmp_path):
    b, c = tmp_path / 'before', tmp_path / 'after'
    make_run(b, ['s1'], {'s1': 'ok'}); make_run(c, ['s1'], {'s1': 'ok'})
    p = c / 's1/agent/attempt-1/result.json'
    r = read_json(p); r['run_id'] = 'unrelated'; write_json(p, r)
    with pytest.raises(ValueError, match='different run'):
        compare_runs(b, c)
