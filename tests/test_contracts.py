import copy
import io
import tarfile

import pytest

from aicr.context import build_context
from aicr.contracts import chunk, validate_assessment
from aicr.github import normalize_comment
from aicr.io import ROOT, digest, read_jsonl, safe_repo_path
from aicr.snapshots import build_archive_snapshot, hunk_matches


@pytest.fixture
def reference():
    assessment = read_jsonl(ROOT / 'examples/assessments.jsonl')[0]
    e = assessment['evidence'][0]
    snapshot = {'id': e['snapshot_id'], 'commit_sha': e['commit_sha'], 'partial': False,
                'files': {e['path']: {'text': e['excerpt'], 'text_sha256': digest(e['excerpt'])}}}
    c = chunk(snapshot, e['path'], 1, 3)
    e['source_chunk_id'] = c['source_chunk_id']
    return assessment, snapshot, c


def check(reference, change=None, shown=True):
    a, snapshot, c = copy.deepcopy(reference)
    if change: change(a)
    return validate_assessment(a, snapshot, [c] if shown else [], sample_id=a['sample_id'], run_id=a['run_id'], mode=a['context_mode'])


def test_valid_anchor(reference):
    result = check(reference)
    assert result['schema_valid'] and result['semantic_valid'] and result['evidence_valid']


def test_unshown_evidence_rejected(reference):
    assert not check(reference, shown=False)['evidence_valid']


def test_forged_shown_chunk_rejected(reference):
    a, snapshot, c = copy.deepcopy(reference)
    c['source_chunk_id'] = 'forged'
    a['evidence'][0]['source_chunk_id'] = 'forged'
    r = validate_assessment(a, snapshot, [c], sample_id=a['sample_id'], run_id=a['run_id'], mode=a['context_mode'])
    assert not r['evidence_valid']


def test_fabricated_quote_rejected(reference):
    assert not check(reference, lambda a: a['evidence'][0].update(excerpt='return 0'))['evidence_valid']


def test_wrong_commit_rejected(reference):
    assert not check(reference, lambda a: a['evidence'][0].update(commit_sha='a' * 40))['evidence_valid']


def test_supported_without_support_rejected(reference):
    assert not check(reference, lambda a: a['evidence'][0].update(relation='context'))['semantic_valid']


def test_unknown_reaction_field_rejected(reference):
    assert not check(reference, lambda a: a.update(user_reaction='+1'))['schema_valid']


def test_native_ordinal_scale(reference):
    assert not check(reference, lambda a: a['severity'].update(value='medium'))['schema_valid']
    assert not check(reference, lambda a: a['complexity'].update(value=6))['schema_valid']


def test_blinding_allowlist(reference):
    a, snapshot, _ = reference
    sample = {'id': 'x', 'path': 'example.py', 'original_line': 3, 'comment_text': 'Is zero handled?',
              'body': 'LABEL LEAK', 'user_reaction': 'LIKE LEAK', 'teacher': 'TEACHER LEAK', 'generator_rationale': None}
    context = build_context(sample, snapshot, 'local')
    assert 'LEAK' not in str(context)
    assert context['comment_created_at'] is None
    assert context['body_history_status'] == 'unknown'


def test_historical_metadata_is_explicit_and_allowlisted(reference):
    _, snapshot, _ = reference
    sample = {'id': 'x', 'path': 'example.py', 'original_line': 3, 'comment_text': 'Finding',
              'created_at': '2026-01-01T00:00:00Z', 'body_history_status': 'current_only',
              'late_replies': 'LEAK', 'accepted': 'LEAK', 'judge': 'LEAK', 'reaction': 'LEAK'}
    context = build_context(sample, snapshot, 'agent')
    assert context['input_contract'] == 'blinded-context-0.2'
    assert context['comment_created_at'] == sample['created_at']
    assert context['body_history_status'] == 'current_only'
    assert 'LEAK' not in str(context)


@pytest.mark.parametrize('path', ['../a', '/etc/passwd', 'C:/a', 'a\\b', 'a//b', 'a/./b'])
def test_unsafe_paths(path):
    assert not safe_repo_path(path)


def test_historical_hunk_mismatch():
    hunk = '@@ -1,1 +1,2 @@\n old\n+new'
    assert hunk_matches('old\nnew\n', hunk, 2)
    assert not hunk_matches('old\nfuture\n', hunk, 2)


def test_archive_never_extracts_symlinks_or_traversal(tmp_path):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, contents in [('root/code.py', b'print(1)'), ('root/../../escape', b'bad'), ('root/.env', b'secret')]:
            info = tarfile.TarInfo(name); info.size = len(contents); tar.addfile(info, io.BytesIO(contents))
        link = tarfile.TarInfo('root/link'); link.type = tarfile.SYMTYPE; link.linkname = '/etc/passwd'; tar.addfile(link)
    s = build_archive_snapshot('a/b', 'a' * 40, stream.getvalue(), {'max_files': 100, 'max_total_bytes': 10000, 'max_file_bytes': 1000})
    assert list(s['files']) == ['code.py']
    assert list(tmp_path.iterdir()) == []


def test_edited_comment_is_not_historical_ground_truth():
    c = {'id': 1, 'body': '_Functional_ | _Major_\n\nReal finding.\n<details>Agent instructions</details>',
         'user': {'type': 'Bot', 'login': 'coderabbitai[bot]'}, 'created_at': '2026-01-01T00:00:00Z',
         'updated_at': '2026-01-02T00:00:00Z', 'html_url': 'https://github.com/a/b/pull/1', 'path': 'a.py'}
    sample = normalize_comment('a/b', 1, c, '2026-02-01T00:00:00Z')
    assert sample['body_history_status'] == 'current_only'
    assert sample['comment_text'] == 'Real finding.'
    assert not sample['strict_eligible']
