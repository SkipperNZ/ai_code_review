"""Run an explicitly selected GitHub demo; this is not random or held-out sampling."""
import argparse
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from aicr.io import read_json, read_jsonl
from aicr.runner import run_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=root / 'configs/default.json')
    parser.add_argument('--comment-id', type=int, action='append', required=True)
    parser.add_argument('--name', default='selected-demo')
    parser.add_argument('--modes', choices=['local', 'static', 'agent'], nargs='+', default=['local', 'agent'])
    args = parser.parse_args()
    ids = set(args.comment_id)
    samples = [s for s in read_jsonl(args.data / 'normalized/samples.jsonl')
               if s['provider'] == 'github' and s['comment_id'] in ids]
    if len(samples) != len(ids) or any(not s['snapshot_id'] for s in samples):
        raise ValueError('Every explicit comment ID must resolve to exactly one captured sample with a snapshot')
    print(json.dumps({'selection': 'explicit_ids_not_random_or_holdout', 'comment_ids': sorted(ids)}, indent=2), flush=True)
    result = run_batch(args.data.resolve(), root / 'runs', samples, read_json(args.config),
                       args.name, args.modes, len(samples))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
