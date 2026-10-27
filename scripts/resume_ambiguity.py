"""Integrity-check or resume an ambiguity run with its frozen code and human-input snapshot."""
import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--data', type=Path, help='Defaults to the original recorded data root')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--retry-failed', action='store_true')
    args = parser.parse_args()
    directory = args.directory.resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    identity = manifest['identity']
    execution = directory / 'execution'
    sys.path.insert(0, str(execution / 'src'))
    from aicr.io import digest, read_jsonl
    from aicr import ambiguity, runner
    if runner.code_hash() != identity['code_hash'] or digest(identity)[:12] != manifest['id'].rsplit('-', 1)[1]:
        raise RuntimeError('Frozen source or run identity differs')
    data = (args.data or Path(manifest['data_root'])).resolve()
    samples = {s['id']: s for s in read_jsonl(data / 'normalized/samples.jsonl')}
    if any(sid not in samples or digest(samples[sid]) != expected for sid, expected in identity['sample_hashes'].items()):
        raise RuntimeError('Sample capture changed')
    if any(digest((data / 'snapshots' / (sid + '.json')).read_text(encoding='utf-8')) != expected for sid, expected in identity['snapshot_hashes'].items()):
        raise RuntimeError('Snapshot changed')
    human_path = directory / 'human-inputs.jsonl'
    humans = {h['sample_id']: h for h in read_jsonl(human_path)}
    if {sid: digest(h) for sid, h in humans.items()} != identity['human_hashes']:
        raise RuntimeError('Frozen human input changed')
    dependency_root = next((p for p in execution.parents if (p / 'node_modules').is_dir()), None)
    if dependency_root is None or digest((dependency_root / 'package-lock.json').read_text(encoding='utf-8')) != digest((execution / 'package-lock.json').read_text(encoding='utf-8')):
        raise RuntimeError('Dependency lock differs from frozen run')
    if args.dry_run:
        cases = list(directory.glob('*/case.json'))
        if cases:
            hashes = json.loads((directory / 'case-hashes.json').read_text(encoding='utf-8'))
            for path in cases:
                row = json.loads(path.read_text(encoding='utf-8'))
                if digest(row) != hashes.get(row['sample_id']) or row['run_id'] != manifest['id']:
                    raise RuntimeError('Saved case changed')
        print(json.dumps({'run_id': manifest['id'], 'integrity_valid': True, 'cases_completed': len(cases),
                          'planned': len(identity['selected']), 'model_requests_now': 0}, indent=2))
        return
    original_doctor = runner.doctor
    def checked_doctor(config):
        frozen_root = runner.ROOT
        try:
            runner.ROOT = dependency_root
            health = original_doctor(config)
        finally:
            runner.ROOT = frozen_root
        if not health['ok'] or health.get('deployment_fingerprint') != identity['deployment']:
            raise RuntimeError('Deployment unavailable or changed; use a new run')
        return health
    def frozen_humans(path, **kwargs):
        if Path(path).resolve() != human_path:
            raise RuntimeError('Unexpected human input path')
        return humans
    ambiguity.doctor = checked_doctor
    ambiguity.load_humans = frozen_humans
    out = ambiguity.run_ambiguity(data, directory.parent, identity['config'],
        name=manifest['id'].rsplit('-', 1)[0], limit=len(identity['selected']), human_file=human_path,
        sample_ids=identity['selected'], strict=identity['strict_only'], retry_failed=args.retry_failed,
        synthetic_demo=identity['synthetic_demo'])
    if out['run_id'] != manifest['id']:
        raise RuntimeError('Run identity changed')
    print(json.dumps(out, indent=2))


if __name__ == '__main__':
    main()
