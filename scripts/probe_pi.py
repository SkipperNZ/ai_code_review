"""A synthetic cross-file integration probe; never mixed into the public corpus."""
from pathlib import Path

from aicr.io import ROOT, digest, read_json, now
from aicr.runner import run_one

config = read_json(ROOT / 'configs/default.json')
config['limits']['wall_seconds'] = 180
snapshot = {'id': 'synthetic-cross-file-v1', 'commit_sha': 'a' * 40, 'partial': False, 'files': {}}
for path, text in {
    'calculate.py': 'from guards import denominator\n\ndef reciprocal(x):\n    return 1 / denominator(x)\n',
    'guards.py': 'def denominator(x):\n    """Return a non-zero integer divisor, including when x is zero."""\n    return max(1, abs(int(x)))\n',
}.items():
    snapshot['files'][path] = {'text': text, 'text_sha256': digest(text)}
sample = {'id': 'synthetic-cross-file-v1', 'comment_text': 'reciprocal(0) will divide by zero. Add a zero check before the division.',
          'generator_rationale': None, 'path': 'calculate.py', 'original_line': 4, 'original_start_line': None, 'strict_eligible': False}
probe_id = 'synthetic-' + now().replace(':', '').replace('.', '')
for mode in ['local', 'agent']:
    result = run_one(sample, snapshot, config, mode, probe_id, ROOT / 'runs' / probe_id / mode)
    print({k: result[k] for k in ('mode', 'status', 'wall_seconds')}, flush=True)
