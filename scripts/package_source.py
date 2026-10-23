"""Create a portable source archive, excluding captures, traces, dependencies and credentials."""
import hashlib
import argparse
import json
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', default='0.2.0', help='Version for a new archive; an existing archive is never overwritten')
args = parser.parse_args()
if not args.version or any(c not in '0123456789.-abcdefghijklmnopqrstuvwxyz' for c in args.version):
    raise ValueError('Unsafe release version')
names = ['.gitignore', 'AGENTS.md', 'README.md', 'pyproject.toml', 'requirements.txt',
         'package.json', 'package-lock.json', 'tsconfig.json', 'aicr.ps1']
files = [root / n for n in names]
for folder, pattern in [('src', '*.py'), ('worker', '*.ts'), ('schemas', '*.json'), ('prompts', '*.txt'),
                        ('docs', '*.md'), ('examples', '*.jsonl'), ('tests', '*.py'), ('scripts', '*.py')]:
    files += list((root / folder).rglob(pattern))
payloads = {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(files) if p.is_file()}
config = json.loads((root / 'configs/default.json').read_text(encoding='utf-8'))
config['model'].update(base_url='http://127.0.0.1:8000/v1', id='SET_MODEL_ID', api_key_file='')
payloads['configs/default.json'] = (json.dumps(config, indent=2) + '\n').encode()
payloads['PORTABLE_SETUP.txt'] = (
    'Set configs/default.json model.base_url and model.id for your deployment before running.\n'
    'Provide credentials via MB_JUDGE_API_KEY; the archive contains no credential file.\n'
    'Read docs/06-runbook.md and docs/07-handoff.md. Captures/runs/node_modules/.venv are excluded.\n'
    'Reported experiment results refer to the original workstation capture; human quality is not established.\n'
).encode()
manifest = {name: hashlib.sha256(content).hexdigest() for name, content in payloads.items()}
payloads['SOURCE_MANIFEST.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
out = root / ('dist/aicr-prototype-' + args.version + '.zip')
out.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(out, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
    for name, content in sorted(payloads.items()):
        archive.writestr(name, content)
with zipfile.ZipFile(out) as archive:
    assert archive.testzip() is None
print(json.dumps({'archive': str(out), 'files': len(payloads), 'bytes': out.stat().st_size,
                  'sha256': hashlib.sha256(out.read_bytes()).hexdigest(), 'model_configuration_required': True}, indent=2))
