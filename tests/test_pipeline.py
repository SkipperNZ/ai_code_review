import copy
import sqlite3

import pytest

from aicr.audit import signal_state
from aicr.io import read_json, write_json, digest
from aicr import runner, snapshots


def test_reactions_never_turn_missing_or_conflict_into_binary():
    s = {'events': [], 'reactions_complete': True}
    assert signal_state(s) == 'no_observed_human_thumb'
    s['reactions_complete'] = False
    assert signal_state(s) == 'incomplete'
    s['events'] = [{'content': '+1', 'reactor_type': 'Bot', 'is_self': False}]
    s['reactions_complete'] = True
    assert signal_state(s) == 'no_observed_human_thumb'
    s['events'] += [{'content': v, 'reactor_type': 'User', 'is_self': False} for v in ['+1', '-1']]
    assert signal_state(s) == 'conflicting'


def test_resume_and_snapshot_cache_invalidation(tmp_path, monkeypatch):
    data, runs = tmp_path / 'data', tmp_path / 'runs'
    snap = {'id': 'snap', 'files': {}}
    write_json(data / 'snapshots/snap.json', snap)
    sample = {'id': 's1', 'repo_id': 'o/r', 'created_at': '2026-01-01T00:00:00Z', 'path': 'a.py',
              'comment_text': 'a comment', 'snapshot_id': 'snap', 'strict_eligible': True}
    monkeypatch.setattr(runner, 'doctor', lambda _: {'ok': True, 'deployment_fingerprint': 'x'})
    monkeypatch.setattr(runner, 'code_hash', lambda: 'constant')
    calls = []
    def fake(*args, **kwargs):
        calls.append(args)
        return {'status': 'ok', 'wall_seconds': 1}
    monkeypatch.setattr(runner, 'run_one', fake)
    first = runner.run_batch(data, runs, [sample], {}, 'fixture', ['local'], 1)
    second = runner.run_batch(data, runs, [sample], {}, 'fixture', ['local'], 1)
    assert first['run_id'] == second['run_id'] and len(calls) == 1
    snap['files']['a.py'] = 'changed'
    write_json(data / 'snapshots/snap.json', snap)
    third = runner.run_batch(data, runs, [sample], {}, 'fixture', ['local'], 1)
    assert third['run_id'] != first['run_id'] and len(calls) == 2


def test_failed_snapshot_can_recover_without_stale_exclusion(tmp_path, monkeypatch):
    sample = {'id': 's', 'repo_id': 'o/r', 'side': 'RIGHT', 'path': 'a.py', 'original_commit_id': 'a' * 40,
              'diff_hunk': '@@ -1 +1 @@\n+ok', 'original_line': 1,
              'eligibility_reasons': ['snapshot_unavailable_or_budget']}
    monkeypatch.setattr(snapshots, 'fetch_snapshot', lambda *a: {'id': 'snap', 'partial': False, 'files': {'a.py': {'text': 'ok\n'}}})
    result = snapshots.materialize(tmp_path, [sample], {}, 1)
    assert result['strict_eligible'] == 1
    assert not sample['eligibility_reasons']


@pytest.mark.parametrize('saved_status', [None, 'ok', 'semantic_invalid'])
def test_interrupted_queue_recovery_preserves_completed_work(tmp_path, monkeypatch, saved_status):
    data, runs = tmp_path / 'data', tmp_path / 'runs'
    write_json(data / 'snapshots/snap.json', {'id': 'snap', 'files': {}})
    sample = {'id': 's1', 'repo_id': 'o/r', 'created_at': '2026-01-01T00:00:00Z', 'path': 'a.py',
              'comment_text': 'a comment', 'snapshot_id': 'snap', 'strict_eligible': True}
    monkeypatch.setattr(runner, 'doctor', lambda _: {'ok': True, 'deployment_fingerprint': 'x'})
    monkeypatch.setattr(runner, 'code_hash', lambda: 'constant')
    calls = []
    def fake(sample, snapshot, config, mode, run_id, directory, **kwargs):
        calls.append(directory)
        result = {'run_id': run_id, 'sample_id': sample['id'], 'mode': mode, 'status': 'ok', 'wall_seconds': 1}
        write_json(directory / 'result.json', result)
        return result
    monkeypatch.setattr(runner, 'run_one', fake)
    first = runner.run_batch(data, runs, [sample], {}, 'fixture', ['local'], 1)
    attempt = calls[0]
    write_json(attempt / 'input.json', {'historical_attempt': True})
    if saved_status is None:
        (attempt / 'result.json').unlink()
    else:
        r = read_json(attempt / 'result.json'); r['status'] = saved_status; write_json(attempt / 'result.json', r)
    with sqlite3.connect(runs / 'queue.sqlite') as db:
        db.execute("UPDATE jobs SET status='running'")
    second = runner.run_batch(data, runs, [sample], {}, 'fixture', ['local'], 1)
    assert first['run_id'] == second['run_id']
    assert read_json(attempt / 'input.json') == {'historical_attempt': True}
    if saved_status is None:
        assert len(calls) == 2 and calls[1].name == 'attempt-2'
        assert second['completed_now'] == 1
    else:
        assert len(calls) == 1 and second['completed_now'] == 0
        with sqlite3.connect(runs / 'queue.sqlite') as db:
            assert db.execute('SELECT status FROM jobs').fetchone()[0] == saved_status
