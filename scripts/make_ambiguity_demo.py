"""Create explicit synthetic SAME-input/different-project fixtures; execute no fixture code."""
import argparse
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from aicr.ambiguity_contracts import SCALE
from aicr.io import digest, read_json, read_jsonl, write_json, write_jsonl


def make_demo(data: Path):
    samples, references = [], []
    comment = 'In this project render can be called with None and crash on user.name; add a None guard inside render.'
    for guarded in (True, False):
        texts = {'target.py': 'def render(user):\n    return user.name\n',
                 'caller.py': 'from target import render\n\nuser = None\n' +
                    ('if user is not None:\n    render(user)\n' if guarded else 'render(user)\n')}
        sha = digest(texts)[:40]
        sid = 'synthetic-' + digest([comment, texts])[:16]
        snapshot = {'id': 'synthetic-snap-' + digest(texts)[:16], 'commit_sha': sha, 'partial': False,
                    'provenance': 'synthetic_fixture_not_a_git_commit',
                    'files': {p: {'text': t, 'text_sha256': digest(t)} for p, t in texts.items()}}
        path = data / 'snapshots' / (snapshot['id'] + '.json')
        if path.exists() and read_json(path) != snapshot:
            raise ValueError('Existing demo snapshot differs; use a new data directory')
        write_json(path, snapshot)
        samples.append({'id': sid, 'provider': 'synthetic_fixture', 'repo_id': 'synthetic/' + sid,
            'comment_text': comment, 'path': 'target.py', 'original_line': 2, 'original_commit_id': sha,
            'snapshot_id': snapshot['id'], 'strict_eligible': True, 'source_url': 'synthetic:' + sid,
            'created_at': '2026-10-27T00:00:00Z',
            'student_snippet': {'path': 'target.py', 'start_line': 1, 'end_line': 2}})
        references.append({'sample_id': sid, 'scale_id': SCALE, 'label': 'reject' if guarded else 'accept',
            'source_kind': 'synthetic_reference', 'source_ref': 'constructed_guard_fixture_v1', 'annotator_key': None})
    for path, rows in [(data / 'normalized/samples.jsonl', samples), (data / 'human/synthetic-references.jsonl', references)]:
        if path.exists() and read_jsonl(path) != rows:
            raise ValueError('Existing demo data differs; use a new data directory')
        write_jsonl(path, rows)
    print('Created two synthetic fixtures with identical comment/snippet and different callers. References are NOT human annotations.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=root / 'data/ambiguity-demo-v1')
    make_demo(parser.parse_args().data)
