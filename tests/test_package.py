import hashlib
import importlib.util
import json
import zipfile

import pytest

from aicr.io import ROOT

spec = importlib.util.spec_from_file_location('verify_package', ROOT / 'scripts/verify_package.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def package(path, *, extra=None, corrupt=False, private_config=False):
    model = {'base_url': 'http://127.0.0.1:8000/v1', 'id': 'SET_MODEL_ID', 'api_key_file': ''}
    if private_config:
        model['api_key_file'] = 'private-key-file'
    payloads = {'configs/default.json': json.dumps({'model': model}).encode(), 'README.md': b'public source'}
    payloads.update(extra or {})
    manifest = {k: hashlib.sha256(v).hexdigest() for k, v in payloads.items()}
    if corrupt:
        payloads['README.md'] = b'changed after hashing'
    with zipfile.ZipFile(path, 'w') as z:
        for name, payload in payloads.items():
            z.writestr(name, payload)
        z.writestr('SOURCE_MANIFEST.json', json.dumps(manifest))


def test_portable_archive_hashes_and_config(tmp_path):
    path = tmp_path / 'source.zip'; package(path)
    assert module.verify(path)['integrity_valid']


@pytest.mark.parametrize('kwargs', [{'extra': {'runs/private.json': b'captured'}}, {'corrupt': True}, {'private_config': True}])
def test_portable_archive_rejects_capture_tampering_and_local_key_paths(tmp_path, kwargs):
    path = tmp_path / 'source.zip'; package(path, **kwargs)
    with pytest.raises(ValueError):
        module.verify(path)
