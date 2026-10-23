"""Resume an existing batch using its frozen Python/TS code, even after project edits."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parents[1] / 'data')
    parser.add_argument('--retry-failed', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--check-endpoint', action='store_true', help='Also verify deployment during dry-run, without completions')
    args = parser.parse_args()
    directory, data = args.directory.resolve(), args.data.resolve()
    execution = directory / 'execution'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    sys.path.insert(0, str(execution / 'src'))
    from aicr.io import digest, read_jsonl
    from aicr import runner
    from aicr.runner import code_hash, run_batch
    if code_hash() != manifest['code_hash']:
        raise RuntimeError('Frozen source hashes differ from manifest')
    identity = {k: manifest[k] for k in ['config', 'code_hash', 'deployment', 'selected', 'sample_hashes', 'snapshot_hashes', 'modes', 'strict_only']}
    if digest(identity)[:12] != manifest['id'].rsplit('-', 1)[1]:
        raise RuntimeError('Run identity differs from manifest contents')
    index = {s['id']: s for s in read_jsonl(data / 'normalized/samples.jsonl')}
    samples = [index[sid] for sid in manifest['selected']]
    if any(digest(s) != manifest['sample_hashes'][s['id']] for s in samples):
        raise RuntimeError('Sample capture changed; restore the original capture before resuming')
    for sid, expected in manifest['snapshot_hashes'].items():
        if digest((data / 'snapshots' / (sid + '.json')).read_text(encoding='utf-8')) != expected:
            raise RuntimeError('Snapshot changed')
    dependency_root = next((p for p in execution.parents if (p / 'node_modules').is_dir()), None)
    if not dependency_root or digest((dependency_root / 'package-lock.json').read_text(encoding='utf-8')) != digest((execution / 'package-lock.json').read_text(encoding='utf-8')):
        raise RuntimeError('Dependency lock differs from frozen run; restore its dependencies in a separate checkout')
    original_doctor = runner.doctor
    def checked_doctor(config):
        # Python's version lookup needs the installation root; worker imports resolve ancestors normally.
        frozen_root = runner.ROOT
        try:
            runner.ROOT = dependency_root
            health = original_doctor(config)
        finally:
            runner.ROOT = frozen_root
        if not health['ok'] or health.get('deployment_fingerprint') != manifest['deployment']:
            raise RuntimeError('Deployment unavailable or changed; use a separately named new run')
        return health
    runner.doctor = checked_doctor
    if args.check_endpoint:
        checked_doctor(manifest['config'])
    if args.dry_run:
        statuses = {}
        with sqlite3.connect((directory.parent / 'queue.sqlite').as_uri() + '?mode=ro', uri=True) as db:
            for sample in samples:
                for mode in manifest['modes']:
                    row = db.execute('SELECT status FROM jobs WHERE key=?', (digest([manifest['id'], sample['id'], mode]),)).fetchone()
                    status = row[0] if row else 'not_started'
                    statuses[status] = statuses.get(status, 0) + 1
        print(json.dumps({'run_id': manifest['id'], 'integrity_valid': True, 'planned': len(samples) * len(manifest['modes']),
                          'statuses': statuses, 'model_requests': 0, 'endpoint_checked': args.check_endpoint}, indent=2))
        return
    result = run_batch(data, directory.parent, samples, manifest['config'], manifest['id'].rsplit('-', 1)[0],
                       manifest['modes'], len(samples), manifest['strict_only'], args.retry_failed)
    if result['run_id'] != manifest['id']:
        raise RuntimeError('Deployment identity changed; new run created instead of resuming old deployment')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
