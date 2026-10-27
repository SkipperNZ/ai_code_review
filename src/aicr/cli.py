from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate, export_human
from .github import collect, discover
from .io import ROOT, read_json, read_jsonl, write_json
from .runner import doctor, run_batch
from .snapshots import materialize
from .audit import audit_data
from .contracts import chunk
from .io import safe_repo_path
from .triage import triage
from .comparison import compare_runs
from .ambiguity import run_ambiguity, evaluate_ambiguity
from .ambiguity_audit import export_audit, read_audit_chunk, score_audit


def main():
    parser = argparse.ArgumentParser(description='AICR research prototype. Commands never publish comments.')
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/default.json')
    parser.add_argument('--data', type=Path, default=ROOT / 'data')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    discovery = sub.add_parser('discover'); discovery.add_argument('--query', default='"coderabbitai" is:merged')
    discovery.add_argument('--limit', type=int, default=20)
    collector = sub.add_parser('collect'); collector.add_argument('--discovery', type=Path)
    sub.add_parser('validate')
    snap = sub.add_parser('snapshot'); snap.add_argument('--max-snapshots', type=int, default=12)
    run = sub.add_parser('run'); run.add_argument('--name', default='smoke'); run.add_argument('--limit', type=int, default=40)
    run.add_argument('--modes', nargs='+', choices=['local', 'static', 'agent'], default=['local', 'static', 'agent'])
    run.add_argument('--strict', action='store_true'); run.add_argument('--retry-failed', action='store_true')
    ev = sub.add_parser('evaluate'); ev.add_argument('directory', type=Path); ev.add_argument('--human', type=Path)
    tri = sub.add_parser('triage'); tri.add_argument('directory', type=Path)
    tri.add_argument('--mode', choices=['local', 'static', 'agent'], default='agent')
    compare = sub.add_parser('compare'); compare.add_argument('baseline', type=Path); compare.add_argument('candidate', type=Path)
    compare.add_argument('--mode', choices=['local', 'static', 'agent'], default='agent')
    ambiguity = sub.add_parser('ambiguity-run', help='Independent L/R, post-hoc H, blinded targeted verification and controls')
    ambiguity.add_argument('--name', default='ambiguity'); ambiguity.add_argument('--limit', type=int, default=4)
    source = ambiguity.add_mutually_exclusive_group()
    source.add_argument('--human', type=Path, help='Explicit comment-endorsement-v1 JSONL annotations')
    source.add_argument('--reaction-proxy', action='store_true', help='Explicit weak thumbs-to-endorsement mapping, never context ground truth')
    ambiguity.add_argument('--only-with-human', action='store_true'); ambiguity.add_argument('--strict', action='store_true')
    ambiguity.add_argument('--sample-id', action='append'); ambiguity.add_argument('--retry-failed', action='store_true')
    ambiguity.add_argument('--synthetic-demo', action='store_true', help='Allow clearly tagged synthetic references, not human annotations')
    amb_ev = sub.add_parser('ambiguity-evaluate'); amb_ev.add_argument('directory', type=Path)
    amb_export = sub.add_parser('ambiguity-export-audit', help='Offline blinded local/repository packets including non-candidates')
    amb_export.add_argument('directories', nargs='+', type=Path); amb_export.add_argument('--output', type=Path, required=True)
    amb_read = sub.add_parser('ambiguity-audit-read', help='Read canonical historical code in an exported repository packet')
    amb_read.add_argument('directory', type=Path); amb_read.add_argument('packet_id'); amb_read.add_argument('path')
    amb_read.add_argument('--start', type=int, required=True); amb_read.add_argument('--end', type=int, required=True)
    amb_score = sub.add_parser('ambiguity-score-audit', help='Score separately supplied human context annotations, no model calls')
    amb_score.add_argument('directory', type=Path)
    amb_score.add_argument('--local', type=Path, required=True); amb_score.add_argument('--repository', type=Path, required=True)
    amb_score.add_argument('--allow-synthetic-test', action='store_true')
    read = sub.add_parser('read-snapshot'); read.add_argument('snapshot_id'); read.add_argument('path')
    read.add_argument('--start', type=int, required=True); read.add_argument('--end', type=int, required=True)
    human = sub.add_parser('export-human'); human.add_argument('--limit', type=int, default=240)
    human.add_argument('--output', type=Path, help='Defaults to <data>/human/blind-packets.jsonl')
    args = parser.parse_args()
    config = read_json(args.config) if args.command in {'doctor', 'discover', 'collect', 'snapshot', 'run', 'ambiguity-run'} else None
    if args.command == 'doctor':
        result = doctor(config); write_json(args.data / 'manifests/doctor.json', result)
    elif args.command == 'discover': result = discover(args.data, config, args.query, args.limit)
    elif args.command == 'collect':
        if args.discovery:
            config = {**config, 'seeds': read_json(args.discovery)['candidates']}
        result = collect(args.data, config)
    elif args.command == 'validate': result = audit_data(args.data)
    elif args.command == 'evaluate': result = evaluate(args.directory, args.human, args.data)
    elif args.command == 'triage': result = triage(args.directory, args.data, args.mode)
    elif args.command == 'compare': result = compare_runs(args.baseline, args.candidate, args.mode)
    elif args.command == 'ambiguity-evaluate': result = evaluate_ambiguity(args.directory)
    elif args.command == 'ambiguity-export-audit': result = export_audit(args.directories, args.output)
    elif args.command == 'ambiguity-audit-read': result = read_audit_chunk(args.directory, args.packet_id, args.path, args.start, args.end)
    elif args.command == 'ambiguity-score-audit':
        result = score_audit(args.directory, args.local, args.repository, allow_synthetic=args.allow_synthetic_test)
    elif args.command == 'ambiguity-run':
        result = run_ambiguity(args.data, ROOT / 'runs', config, name=args.name, limit=args.limit,
            human_file=args.human, use_reaction_proxy=args.reaction_proxy, only_with_human=args.only_with_human,
            sample_ids=args.sample_id, strict=args.strict, retry_failed=args.retry_failed, synthetic_demo=args.synthetic_demo)
    elif args.command == 'read-snapshot':
        if not safe_repo_path(args.snapshot_id) or '/' in args.snapshot_id or not safe_repo_path(args.path):
            raise ValueError('Unsafe snapshot/path')
        result = chunk(read_json(args.data / 'snapshots' / (args.snapshot_id + '.json')), args.path, args.start, args.end)
    else:
        samples = read_jsonl(args.data / 'normalized/samples.jsonl')
        if args.command == 'snapshot': result = materialize(args.data, samples, config['snapshot'], args.max_snapshots)
        elif args.command == 'run': result = run_batch(args.data, ROOT / 'runs', samples, config, args.name, args.modes, args.limit, args.strict, args.retry_failed)
        else: result = export_human(args.data, samples, args.output or args.data / 'human/blind-packets.jsonl', args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
