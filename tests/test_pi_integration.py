"""Real Pi SDK against a scripted loopback OpenAI endpoint, never an LLM reference."""
import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from aicr.contracts import chunk, validate_record
from aicr.io import ROOT, digest, read_json, read_jsonl
from aicr.runner import run_one


def wire_text(content):
    return content if isinstance(content, str) else ''.join(c['text'] for c in content if c['type'] == 'text')


@pytest.mark.parametrize('contract', ['compact-0.2.1', 'compact-0.3.0'])
@pytest.mark.parametrize('scenario,expected', [('valid', 'ok'), ('repair', 'ok'), ('invalid', 'json_invalid'),
                                             ('schema_repair', 'ok'), ('tool', 'ok'), ('tool_path_error', 'ok'),
                                             ('budget', 'budget_exhausted'), ('timeout', 'timeout'), ('server_error', 'endpoint_error')])
def test_real_pi_with_mock(tmp_path, scenario, expected, contract, monkeypatch):
    answer = copy.deepcopy(read_jsonl(ROOT / 'examples/assessments.jsonl')[0])
    e = answer['evidence'][0]
    snapshot = {'id': e['snapshot_id'], 'commit_sha': e['commit_sha'], 'partial': False,
                'files': {e['path']: {'text': e['excerpt'], 'text_sha256': digest(e['excerpt'])}}}
    c = chunk(snapshot, e['path'], 1, 3)
    e['source_chunk_id'] = c['source_chunk_id']
    sample = {'id': 'synthetic-mock', 'path': e['path'], 'original_line': 3,
              'comment_text': answer['claims'][0]['text'], 'strict_eligible': False}
    mode = 'agent' if scenario in ('tool', 'tool_path_error', 'budget') else 'local'
    answer.update(sample_id=sample['id'], run_id='mock-only', context_mode=mode)
    # Fixture endpoint follows the compact model contract, not the canonical record.
    evidence = {x['evidence_id']: x for x in answer.pop('evidence')}
    for name in ['schema_version', 'sample_id', 'run_id', 'context_mode']:
        answer.pop(name)
    for name in ['severity', 'complexity']:
        answer[name].pop('scale_id')
    answer['correctness'].pop('value')
    for claim in answer['claims']:
        claim.pop('claim_id')
        fields = ['source_chunk_id', 'relation', 'start_line', 'end_line'] if contract == 'compact-0.2.1' else ['source_chunk_id', 'relation']
        claim['evidence_links'] = [{k: evidence[eid][k] for k in fields}
                                   for eid in claim.pop('evidence_ids')]
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            if scenario == 'server_error':
                self.send_error(500, 'Synthetic server failure fixture-nonsecret')
                return
            if scenario == 'timeout':
                time.sleep(1)
            tool = scenario in ('tool', 'tool_path_error', 'budget') and len(calls) == 1
            if tool:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'call_fixture', 'type': 'function',
                         'function': {'name': 'read_lines', 'arguments': json.dumps({'snapshot_id': snapshot['id'],
                                      'path': '../outside-secret.txt' if scenario == 'tool_path_error' else e['path'], 'start_line': 1, 'end_line': 3})}}]}
            else:
                payload_answer = copy.deepcopy(answer)
                if scenario == 'schema_repair' and len(calls) == 1:
                    payload_answer['claims'][0].pop('evidence_links')
                content = 'not JSON' if scenario == 'invalid' or (scenario == 'repair' and len(calls) == 1) else json.dumps(payload_answer)
                delta = {'role': 'assistant', 'content': content}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            payloads = [
                {'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if tool else 'stop'}],
                 'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}},
            ]
            try:
                for payload in payloads:
                    payload.update(id='mock', object='chat.completion.chunk', model='mock', created=1)
                    self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = read_json(ROOT / 'configs/default.example.json')
    config['response_contract'] = contract
    config['model'].update(base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key_env='AICR_MOCK_KEY', api_key_file='')
    monkeypatch.setenv('AICR_MOCK_KEY', 'fixture-nonsecret')
    config['limits']['wall_seconds'] = .05 if scenario == 'timeout' else 30
    if scenario == 'budget':
        config['limits']['max_turns'] = 1
    runtime = tmp_path / scenario / 'runtime'
    runtime.mkdir(parents=True)
    forbidden = 'MUST_NOT_LOAD_OUT_OF_BUNDLE_SENTINEL'
    (runtime / 'AGENTS.md').write_text(forbidden, encoding='utf-8')
    (runtime.parent / 'outside-secret.txt').write_text(forbidden, encoding='utf-8')
    try:
        result = run_one(sample, snapshot, config, mode, 'mock-only', tmp_path / scenario)
    finally:
        server.shutdown()
        server.server_close()
    assert result['status'] == expected, result
    assert not validate_record('run_attempt', result)
    assert forbidden not in json.dumps(calls)
    trace = (tmp_path / scenario / 'trace.jsonl').read_text(encoding='utf-8')
    assert forbidden not in trace and 'fixture-nonsecret' not in trace
    payload_metadata = [json.loads(line)['data'] for line in trace.splitlines() if json.loads(line)['type'] == 'request_payload']
    if calls:
        assert payload_metadata[0]['max_tokens'] == calls[0]['max_tokens']
        assert payload_metadata[0]['message_chars'] > 0
    if calls:
        prompt = next(m['content'] for m in calls[0]['messages'] if m['role'] == 'user')
        model_input = json.loads(wire_text(prompt))['input']
        assert model_input['input_contract'] == 'blinded-context-0.2'
        displayed = model_input['chunks'][0]
        assert displayed['numbered_excerpt'].startswith('1 | ')
        assert 'excerpt' not in displayed
        assert displayed['source_chunk_id'] == c['source_chunk_id']
    if scenario == 'tool':
        assert result['tool_calls'] == 1
        assert len(calls) == 2
        names = {t['function']['name'] for t in calls[0]['tools']}
        assert names == {'list_paths', 'read_diff', 'read_lines', 'search_text'}
        assert calls[0]['chat_template_kwargs'] == config['model']['chat_template_kwargs']
        tool_text = next(m['content'] for m in calls[1]['messages'] if m['role'] == 'tool')
        assert json.loads(wire_text(tool_text))['numbered_excerpt'].startswith('1 | ')
        shown = read_json(tmp_path / scenario / 'shown-chunks.json')
        assert all('numbered_excerpt' not in c for c in shown)
        assert shown[0]['excerpt'] == e['excerpt']
    if scenario in ('repair', 'schema_repair'):
        assert result['format_repair'] and len(calls) == 2
    if scenario == 'tool_path_error':
        assert result['tool_calls'] == 1 and len(calls) == 2
        tool_text = next(m['content'] for m in calls[1]['messages'] if m['role'] == 'tool')
        assert 'path_not_in_snapshot' in wire_text(tool_text)
    if expected != 'ok':
        assert result['assessment_ref'] is None
