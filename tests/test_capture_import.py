"""Synthetic API captures exercise the offline transport; no live GitHub calls."""
import importlib.util
from pathlib import Path

import pytest

from aicr.github import GitHubClient
from aicr.io import ROOT, read_jsonl, write_json

spec = importlib.util.spec_from_file_location('aicr_capture_import_script', ROOT / 'scripts/import_public_capture.py')
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def capture_fixture(tmp_path):
    comment = {'id': 1, 'body': 'This is a synthetic inline finding with enough text for the collector.',
               'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:00Z',
               'user': {'type': 'Bot', 'login': 'fixture[bot]', 'id': 7},
               'html_url': 'https://github.com/example/fixture/pull/1#discussion_r1',
               'path': 'x.py', 'reactions': {'total_count': 3}}
    path = tmp_path / 'source.json'
    payload = {'captured_at': '2026-01-02T00:00:00Z', 'responses': [
        {'route': '/repos/example/fixture', 'body': {'full_name': 'example/fixture', 'private': False}},
        {'route': '/repos/example/fixture/pulls/1/comments?per_page=100&page=1', 'body': [comment]}]}
    write_json(path, payload)
    return path, payload


def test_import_never_requests_missing_reactions_or_infers_them_from_counts(tmp_path, monkeypatch):
    path, _ = capture_fixture(tmp_path)
    def no_network(*args, **kwargs):
        pytest.fail('Capture importer attempted a live network request')
    import requests
    monkeypatch.setattr(requests.Session, 'get', no_network)
    data = tmp_path / 'data'
    result = script.import_capture(path, data, ['fixture[bot]'])
    signal = read_jsonl(data / 'signals/user-signals.jsonl')[0]
    assert signal['reactions_complete'] is False and signal['events'] == []
    assert signal['reaction_error'] == 'RuntimeError'
    with pytest.raises(ValueError, match='new data directory'):
        script.import_capture(path, data, ['fixture[bot]'])


@pytest.mark.parametrize('mutation', ['private', 'metadata', 'route', 'duplicate'])
def test_import_validates_all_routes_before_writing(tmp_path, mutation):
    path, payload = capture_fixture(tmp_path)
    if mutation == 'private': payload['responses'][0]['body']['private'] = True
    if mutation == 'metadata': payload['responses'].pop(0)
    if mutation == 'route': payload['responses'][1]['route'] = 'https://evil.invalid/secret'
    if mutation == 'duplicate': payload['responses'].append(payload['responses'][0])
    write_json(path, payload)
    data = tmp_path / 'data'
    with pytest.raises(ValueError): script.import_capture(path, data, ['fixture[bot]'])
    assert not data.exists()
