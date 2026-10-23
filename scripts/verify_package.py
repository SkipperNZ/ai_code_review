"""Verify a portable source ZIP without extracting or executing it."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


def verify(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip() is not None:
            raise ValueError('Archive contains duplicate or corrupt entries')
        forbidden = []
        for name in names:
            parts = PurePosixPath(name).parts
            if (name.startswith('/') or '\\' in name or ':' in name or '..' in parts or
                    set(parts) & {'data', 'runs', '.venv', 'node_modules', '.cache', '.git'} or
                    name.endswith('.local.json') or name.endswith('api-key.local.txt') or '.env' in parts):
                forbidden.append(name)
        if forbidden:
            raise ValueError('Forbidden package entries: ' + ', '.join(forbidden))
        manifest = json.loads(archive.read('SOURCE_MANIFEST.json'))
        if set(manifest) != set(names) - {'SOURCE_MANIFEST.json'}:
            raise ValueError('Source manifest file inventory differs from archive')
        for name, expected in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('Source hash differs: ' + name)
        model = json.loads(archive.read('configs/default.json'))['model']
        if (model['base_url'] != 'http://127.0.0.1:8000/v1' or model['id'] != 'SET_MODEL_ID' or model.get('api_key_file')):
            raise ValueError('Portable model configuration is not sanitized')
    return {'archive': str(path.resolve()), 'files': len(names), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'integrity_valid': True,
            'forbidden_entries': 0, 'model_configuration_sanitized': True,
            'scope': 'archive_integrity_and_packaging_rules_not_arbitrary_secret_detection'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = verify(args.archive)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)
