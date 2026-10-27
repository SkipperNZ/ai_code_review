"""Full new protocol through real Pi SDK and a scripted loopback provider."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from aicr.ambiguity import run_ambiguity
from aicr.contracts import chunk
from aicr.io import ROOT, read_json
from test_ambiguity import assessment, fixture_data


def content_text(content):
    return content if isinstance(content, str) else ''.join(c.get('text', '') for c in content if c['type'] == 'text')


@pytest.mark.parametrize('scenario', ['guarded', 'unguarded', 'server_error', 'invalid_json', 'timeout'])
def test_real_pi_full_ambiguity_protocol(tmp_path, monkeypatch, scenario):
    data, sample, snapshot, human_file = fixture_data(tmp_path, guarded=scenario != 'unguarded')
    calls = []
    config = read_json(ROOT / 'configs/default.example.json')
    local = chunk(snapshot, 'target.py', 1, 2)
    outside = chunk(snapshot, 'caller.py', 1, 3)
    verdict = 'accept' if scenario == 'unguarded' else 'reject'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps({'data': [{'id': config['model']['id']}]}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(body)
            visible = json.dumps(body)
            for forbidden in ['UNTRUSTED_BODY_LABEL_SENTINEL', 'RATIONALE_MUST_NOT_LEAK', 'SYNTHETIC_HIDDEN_H_SIGNAL']:
                assert forbidden not in visible
            if scenario == 'server_error':
                self.send_error(500, 'fixture-ambiguity-nonsecret')
                return
            if scenario == 'timeout':
                time.sleep(.3)
            first = json.loads(next(content_text(m['content']) for m in body['messages'] if m['role'] == 'user'))
            assert first['identity']['sample_id'] != sample['id']
            schema_id = first['schema']['$id']
            inputs = first['input']
            has_tool_result = any(m['role'] == 'tool' for m in body['messages'])
            tool = bool(body.get('tools')) and not has_tool_result and 'claim:' not in schema_id
            if tool:
                delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'fixture-read', 'type': 'function',
                    'function': {'name': 'read_lines', 'arguments': json.dumps({'snapshot_id': snapshot['id'],
                        'path': 'caller.py', 'start_line': 1, 'end_line': 3})}}]}
            else:
                if 'ambiguity-claim:' in schema_id:
                    value = {'status': 'identified', 'claim_excerpt': inputs['comment'], 'rationale': 'fixture extractor'}
                elif 'ambiguity-verification:' in schema_id:
                    assert 'local_chunk_ids' in inputs and 'decision' not in inputs
                    value = {'outcome': 'context_dependency_supported', 'resolved_decision': verdict,
                        'missing_local_premise': 'Whether callers guard the nullable value',
                        'local_insufficiency_explanation': 'No caller is in the fixed local snippet.',
                        'rationale': 'Scripted provider, not a human reference.',
                        'decisive_links': [{'source_chunk_id': outside['source_chunk_id'], 'relation': 'supports' if verdict == 'accept' else 'refutes'}]}
                else:
                    known = has_tool_result or len(inputs['chunks']) > 1
                    value = assessment(verdict, outside) if known else assessment('unknown')
                delta = {'role': 'assistant', 'content': 'invalid JSON' if scenario == 'invalid_json' else json.dumps(value)}
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            events = [{'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]},
                      {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if tool else 'stop'}],
                       'usage': {'prompt_tokens': 100, 'completion_tokens': 50, 'total_tokens': 150}}]
            try:
                for event in events:
                    event.update(id='fixture', object='chat.completion.chunk', model=config['model']['id'], created=1)
                    self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config['model'].update(base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key_env='AICR_AMBIGUITY_FIXTURE_KEY', api_key_file='')
    monkeypatch.setenv('AICR_AMBIGUITY_FIXTURE_KEY', 'fixture-ambiguity-nonsecret')
    config['limits']['wall_seconds'] = .05 if scenario == 'timeout' else 30
    try:
        out = run_ambiguity(data, tmp_path / 'runs', config, human_file=human_file, synthetic_demo=True)
    finally:
        server.shutdown(); server.server_close()
    case = read_json(Path(out['directory']) / sample['id'] / 'case.json')
    for path in Path(out['directory']).glob('*/**/trace.jsonl'):
        assert 'fixture-ambiguity-nonsecret' not in path.read_text(encoding='utf-8')
    if scenario in ('guarded', 'unguarded'):
        assert case['conclusion'] == 'model_supported_context_dependency', case
        assert case['stages']['L']['assessment']['decision'] == 'unknown'
        assert case['stages']['R']['tool_calls'] == case['stages']['V']['tool_calls'] == 1
        assert case['ambiguity_gold_label'] is None and out['metrics']['human_context_reference_available'] is False
        assert case['stages']['L']['input_hash'] == case['stages']['L_repeat']['input_hash']
    else:
        assert case['status'] == 'claim_unavailable' and not case['candidate']
        assert case['stages']['E']['status'] == {'server_error': 'endpoint_error', 'invalid_json': 'json_invalid', 'timeout': 'timeout'}[scenario]
