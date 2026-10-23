"""Measure optional server template control; prints counts only, never reasoning text."""
import json
import time
import requests
from aicr.io import ROOT, model_secret, read_json, write_json

cfg = read_json(ROOT / 'configs/default.json')['model']
s = requests.Session(); s.trust_env = False
key = model_secret(cfg)
if key: s.headers['Authorization'] = 'Bearer ' + key
results = []
for setting in [None, {'enable_thinking': False}]:
    body = {'model': cfg['id'], 'messages': [{'role': 'user', 'content': 'Return exactly {"sum":17} as JSON and no other text.'}],
            'max_tokens': 512, 'temperature': 0, 'stream': True, 'stream_options': {'include_usage': True}}
    if setting is not None: body['chat_template_kwargs'] = setting
    start = time.monotonic(); output = ''; reasoning = 0; usage = None; finish = None
    with s.post(cfg['base_url'] + '/chat/completions', json=body, stream=True, timeout=(10, 60)) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith(b'data: ') or line == b'data: [DONE]': continue
            item = json.loads(line[6:])
            if item.get('usage'): usage = item['usage']
            for choice in item.get('choices', []):
                d = choice.get('delta', {})
                output += d.get('content') or ''
                reasoning += len(d.get('reasoning_content') or d.get('reasoning') or '')
                finish = choice.get('finish_reason') or finish
    result = {'chat_template_kwargs': setting, 'seconds': round(time.monotonic()-start, 3), 'reasoning_chars': reasoning,
              'content_chars': len(output), 'expected_json': output.strip() == '{"sum":17}', 'finish_reason': finish, 'usage': usage}
    results.append(result); print(json.dumps(result), flush=True)
write_json(ROOT / 'runs/probes/reasoning-controls.json', results)
