"""Construct callee-definition and locally decidable controls. No fixture code is executed."""
import argparse
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from aicr.ambiguity_contracts import SCALE
from aicr.io import digest, read_json, read_jsonl, write_json, write_jsonl


def make_controls(data: Path):
    cases = []
    comment = 'The call to transform(None) raises AttributeError because transform unconditionally reads value.name.'
    for guarded in (True, False):
        cases.append((comment, 'entry.py', 2,
            {'entry.py': 'from service import transform\nresult = transform(None)\n',
             'service.py': 'def transform(value):\n' + ('    if value is None:\n        return "anonymous"\n' if guarded else '') + '    return value.name\n'},
            'reject' if guarded else 'accept', 'missing_callee_definition'))
    for safe in (True, False):
        cases.append(('compute(0) raises ZeroDivisionError because x is the divisor.', 'maths.py', 2,
            {'maths.py': 'def compute(x):\n    return 10 / ' + ('(x + 1)' if safe else 'x') + '\n',
             'notes.txt': 'A small independent example.\n'}, 'reject' if safe else 'accept', 'locally_decidable'))
    samples, references, expectations = [], [], []
    for comment, path, anchor, texts, decision, kind in cases:
        sha = digest(texts)[:40]
        sid = 'synthetic-' + digest([comment, texts])[:16]
        snapshot = {'id': 'synthetic-snap-' + digest(texts)[:16], 'commit_sha': sha, 'partial': False,
                    'provenance': 'synthetic_fixture_not_a_git_commit',
                    'files': {p: {'text': t, 'text_sha256': digest(t)} for p, t in texts.items()}}
        target = data / 'snapshots' / (snapshot['id'] + '.json')
        if target.exists() and read_json(target) != snapshot:
            raise ValueError('Existing control snapshot differs; choose a new data directory')
        write_json(target, snapshot)
        samples.append({'id': sid, 'provider': 'synthetic_fixture', 'repo_id': 'synthetic/' + sid,
            'comment_text': comment, 'path': path, 'original_line': anchor, 'original_commit_id': sha,
            'snapshot_id': snapshot['id'], 'strict_eligible': True, 'source_url': 'synthetic:' + sid,
            'created_at': '2026-10-27T00:00:00Z', 'student_snippet': {'path': path, 'start_line': 1, 'end_line': 2}})
        references.append({'sample_id': sid, 'scale_id': SCALE, 'label': decision,
            'source_kind': 'synthetic_reference', 'source_ref': 'constructed_control_fixture_v1', 'annotator_key': None})
        expectations.append({'sample_id': sid, 'kind': kind, 'repository_decision': decision,
                             'source_kind': 'constructed_fixture_expectation_not_human',
                             'context_required': kind == 'missing_callee_definition'})
    for target, rows in [(data / 'normalized/samples.jsonl', samples), (data / 'human/synthetic-references.jsonl', references),
                         (data / 'fixture-expectations.jsonl', expectations)]:
        if target.exists() and read_jsonl(target) != rows:
            raise ValueError('Existing controls differ; choose a new data directory')
        write_jsonl(target, rows)
    print('Created four synthetic controls: two missing definitions and two locally decidable findings. Not human annotations.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=root / 'data/ambiguity-controls-v1')
    make_controls(parser.parse_args().data)
