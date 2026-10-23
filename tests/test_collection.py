from aicr import github
from aicr.audit import signal_state
from aicr.context import build_context
from aicr.io import read_jsonl


def test_discovery_is_only_audited_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(github.GitHubClient, 'get', lambda self, route: {'total_count': 200, 'incomplete_results': True,
        'items': [{'html_url': 'https://github.com/o/r/pull/7'}, {'html_url': 'https://github.com/o/r/issues/8'}]})
    r = github.discover(tmp_path, {'github': {}}, '"review bot"', 2)
    assert r['search_incomplete'] and r['candidates'] == [{'repo': 'o/r', 'pr': 7, 'url': 'https://github.com/o/r/pull/7'}]
    assert r['reaction_availability'] == 'not_yet_verified'


def test_collector_keeps_conflicting_reactions_separate(tmp_path, monkeypatch):
    c = {'id': 7, 'body': '_Potential issue | Critical_\n\nThe divisor can be zero for an allowed input; add a guard.',
         'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-02T00:00:00Z',
         'user': {'id': 1, 'type': 'Bot', 'login': 'bot[bot]'}, 'path': 'a.py',
         'html_url': 'https://github.com/o/r/pull/1#discussion_r7', 'reactions': {'total_count': 3}}
    reactions = [{'id': i, 'content': v, 'user': {'id': i, 'type': kind}} for i, v, kind in [(2, '+1', 'User'), (3, '-1', 'User'), (1, '+1', 'Bot')]]
    monkeypatch.setattr(github.GitHubClient, 'get', lambda *args: {'private': False})
    monkeypatch.setattr(github.GitHubClient, 'pages', lambda self, route: (reactions if route.endswith('/reactions') else [c], True))
    r = github.collect(tmp_path, {'github': {}, 'seeds': [{'repo': 'o/r', 'pr': 1}], 'bot_logins': ['bot[bot]']})
    assert r['samples_with_human_thumb'] == 1
    sample = read_jsonl(tmp_path / 'normalized/samples.jsonl')[0]
    signal = read_jsonl(tmp_path / 'signals/user-signals.jsonl')[0]
    assert signal_state(signal) == 'conflicting'
    assert sample['body_history_status'] == 'current_only'
    assert 'Critical' not in sample['comment_text'] and 'Critical' in sample['body']
    assert 'reactor' not in str(sample)
