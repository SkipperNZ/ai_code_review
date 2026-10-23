from __future__ import annotations

import io
import re
import tarfile
from pathlib import Path

import requests

from .io import digest, now, read_json, safe_repo_path, write_json, write_jsonl

SENSITIVE = re.compile(r'(^|/)(\.env(?:\..*)?|\.git|\.aws|\.ssh|credentials|id_rsa|id_ed25519)(/|$)', re.I)


def build_archive_snapshot(repo: str, sha: str, content: bytes, limits: dict) -> dict:
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Expected exact Git commit SHA')
    snapshot = {'id': 'snap-' + digest(repo + ':' + sha)[:24], 'repo_id': repo, 'commit_sha': sha, 'captured_at': now(),
                'source_url': f'https://codeload.github.com/{repo}/tar.gz/{sha}', 'archive_sha256': digest_bytes(content),
                'files': {}, 'skipped': {}, 'partial': False}
    size = 0
    with tarfile.open(fileobj=io.BytesIO(content), mode='r:gz') as archive:
        for member in archive:
            if not member.isfile():
                continue
            path = member.name.partition('/')[2]
            if not safe_repo_path(path) or SENSITIVE.search(path):
                continue
            if member.size > limits['max_file_bytes']:
                snapshot['skipped'][path] = 'file_size_limit'
                snapshot['partial'] = True
                continue
            if size + member.size > limits['max_total_bytes'] or len(snapshot['files']) >= limits['max_files']:
                snapshot['partial'] = True
                snapshot['skipped']['__remaining__'] = 'snapshot_budget'
                break
            raw = archive.extractfile(member).read()
            if b'\x00' in raw:
                continue
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                snapshot['skipped'][path] = 'non_utf8'
                continue
            text = text.replace('\r\n', '\n').replace('\r', '\n')
            size += member.size
            snapshot['files'][path] = {'text': text, 'raw_sha256': digest_bytes(raw), 'text_sha256': digest(text)}
    snapshot['text_bytes'] = size
    return snapshot


def digest_bytes(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


def fetch_snapshot(root: Path, repo: str, sha: str, limits: dict) -> dict:
    key = 'snap-' + digest(repo + ':' + sha)[:24]
    path = root / 'snapshots' / (key + '.json')
    if path.exists():
        return read_json(path)
    session = requests.Session()
    session.trust_env = False
    response = session.get(f'https://codeload.github.com/{repo}/tar.gz/{sha}', stream=True, timeout=(10, 45))
    response.raise_for_status()
    parts, size = [], 0
    with response:
        for part in response.iter_content(1024 * 1024):
            size += len(part)
            if size > limits['max_archive_bytes']:
                raise ValueError('Archive download exceeds configured limit')
            parts.append(part)
    snapshot = build_archive_snapshot(repo, sha, b''.join(parts), limits)
    write_json(path, snapshot)
    return snapshot


def hunk_matches(text: str, hunk: str, line: int | None) -> bool:
    """All RIGHT-side lines of the hunk must agree with the original commit blob."""
    lines = text.splitlines()
    position, observed = None, set()
    for row in hunk.splitlines():
        match = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', row)
        if match:
            position = int(match[1])
        elif position is not None and row.startswith((' ', '+')):
            if not 1 <= position <= len(lines) or lines[position - 1] != row[1:]:
                return False
            observed.add(position)
            position += 1
    return bool(observed) and line in observed


def materialize(root: Path, samples: list[dict], limits: dict, max_snapshots: int = 12) -> dict:
    cache, failures = {}, {}
    for sample in samples:
        sha = sample.get('original_commit_id')
        key = (sample['repo_id'], sha)
        # Recompute transient snapshot reasons; a formerly unavailable ref may now succeed.
        transient = {'snapshot_pending', 'snapshot_unavailable_or_budget', 'anchor_file_unavailable', 'original_hunk_mismatch', 'unsupported_left_side_or_missing_sha'}
        reasons = [r for r in sample['eligibility_reasons'] if r not in transient]
        sample.update(snapshot_status='unavailable', snapshot_id=None, strict_eligible=False)
        if sample['side'] != 'RIGHT' or not sha:
            reasons.append('unsupported_left_side_or_missing_sha')
        else:
            if key not in cache and key not in failures and len(cache) + len(failures) < max_snapshots:
                try:
                    cache[key] = fetch_snapshot(root, key[0], key[1], limits)
                except (requests.RequestException, ValueError, tarfile.TarError) as exc:
                    failures[key] = type(exc).__name__
            snapshot = cache.get(key)
            file = snapshot and snapshot['files'].get(sample['path'])
            if not snapshot:
                reasons.append('snapshot_unavailable_or_budget')
            elif not file:
                reasons.append('anchor_file_unavailable')
            elif not hunk_matches(file['text'], sample['diff_hunk'], sample['original_line']):
                reasons.append('original_hunk_mismatch')
            else:
                sample['snapshot_id'] = snapshot['id']
                sample['snapshot_status'] = 'partial' if snapshot['partial'] else 'exact'
        sample['eligibility_reasons'] = sorted(set(reasons))
        sample['strict_eligible'] = sample['snapshot_id'] is not None and not reasons
    write_jsonl(root / 'normalized' / 'samples.jsonl', samples)
    result = {'snapshots': len(cache), 'snapshot_failures': [{'repo': k[0], 'sha': k[1], 'error': v} for k, v in failures.items()],
              'available_samples': sum(s['snapshot_id'] is not None for s in samples), 'strict_eligible': sum(s['strict_eligible'] for s in samples)}
    write_json(root / 'manifests' / 'snapshots.json', result)
    return result
