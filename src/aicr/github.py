from __future__ import annotations

import os
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .io import digest, now, read_json, write_json, write_jsonl


class GitHubClient:
    def __init__(self, root: Path, config: dict):
        self.root, self.config, self.requests_used = root, config, 0
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'aicr-research-prototype'})
        if os.environ.get('GITHUB_TOKEN'):
            self.session.headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']

    def get(self, route: str, *, refresh: bool = False):
        if not route.startswith('/') or route.startswith('//'):
            raise ValueError('GitHub route must be relative')
        cache = self.root / 'raw' / 'github' / (digest(route) + '.json')
        if cache.exists() and not refresh:
            return read_json(cache)['body']
        for attempt in range(3):
            if self.requests_used >= self.config['max_requests']:
                raise RuntimeError('GitHub request budget exhausted')
            self.requests_used += 1
            response = self.session.get('https://api.github.com' + route, timeout=self.config['timeout_seconds'])
            if response.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                delay = min(float(response.headers.get('Retry-After', 2 ** attempt)), 30)
                time.sleep(delay)
                continue
            response.raise_for_status()
            body = response.json()
            write_json(cache, {'route': route, 'captured_at': now(), 'etag': response.headers.get('ETag'),
                               'rate_remaining': response.headers.get('X-RateLimit-Remaining'), 'body': body})
            return body
        raise RuntimeError('GitHub retries exhausted')

    def pages(self, route: str) -> tuple[list, bool]:
        values = []
        sep = '&' if '?' in route else '?'
        for page in range(1, self.config['max_pages'] + 1):
            batch = self.get(f'{route}{sep}per_page=100&page={page}')
            if not isinstance(batch, list):
                raise ValueError('Expected paginated list')
            values.extend(batch)
            if len(batch) < 100:
                return values, True
        return values, False


def blind_body(body: str) -> str:
    """Versioned removal of bot labels/instructions, with raw source retained elsewhere."""
    text = body.split('<details>', 1)[0]
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    lines = [s for s in text.splitlines() if not (s.strip().startswith('_') and ('|' in s or 'Potential issue' in s))]
    text = '\n'.join(lines).strip()
    text = re.split(r'<a\s+href=', text, maxsplit=1)[0].strip()
    return text


def normalize_comment(repo: str, pr: int, c: dict, captured_at: str) -> dict:
    body_hash = digest(c['body'])
    sid = 'gh-' + digest([repo, 'review_comment', c['id'], body_hash])[:24]
    same_version = c['created_at'] == c['updated_at']
    return {'id': sid, 'provider': 'github', 'repo_id': repo, 'pr_number': pr, 'comment_kind': 'review_comment',
            'comment_id': c['id'], 'body': c['body'], 'body_hash': body_hash, 'comment_text': blind_body(c['body']),
            'extraction_version': 'strip-bot-metadata-v1', 'generator_rationale': None, 'rationale_provenance': 'unavailable',
            'created_at': c['created_at'], 'updated_at': c['updated_at'], 'captured_at': captured_at,
            'parent_id': c.get('in_reply_to_id'), 'author_type': c['user']['type'], 'author_login': c['user']['login'],
            'source_url': c['html_url'], 'path': c['path'], 'diff_hunk': c.get('diff_hunk', ''),
            'original_commit_id': c.get('original_commit_id'), 'commit_id': c.get('commit_id'),
            'side': c.get('side', 'RIGHT'), 'original_line': c.get('original_line'),
            'original_start_line': c.get('original_start_line'), 'line': c.get('line'),
            'snapshot_id': None, 'snapshot_status': 'unavailable', 'body_history_status': 'exact_at_t0' if same_version else 'current_only',
            'strict_eligible': False, 'eligibility_reasons': ['snapshot_pending'] + ([] if same_version else ['edited_body_history_unavailable'])}


def discover(root: Path, config: dict, query: str, limit: int = 20) -> dict:
    if not 1 <= limit <= 100:
        raise ValueError('Discovery limit must be between 1 and 100')
    api = GitHubClient(root, config['github'])
    result = api.get('/search/issues?' + urlencode({'q': query + ' is:pr is:public', 'per_page': limit, 'page': 1, 'sort': 'updated', 'order': 'desc'}))
    candidates = []
    for item in result.get('items', []):
        match = re.fullmatch(r'https://github.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/(\d+)', item.get('html_url', ''))
        if match:
            candidates.append({'repo': match[1], 'pr': int(match[2]), 'url': item['html_url']})
    audit = {'captured_at': now(), 'query': query, 'limit': limit, 'total_matches': result.get('total_count'),
             'search_incomplete': result.get('incomplete_results', False), 'selection_policy': 'bounded_search_not_random',
             'inline_bot_presence': 'not_yet_verified', 'reaction_availability': 'not_yet_verified', 'candidates': candidates}
    write_json(root / 'manifests/discovery.json', audit)
    return audit


def collect(root: Path, config: dict) -> dict:
    api = GitHubClient(root, config['github'])
    samples, signals, audit = [], [], []
    for seed in config['seeds']:
        repo, pr = seed['repo'], seed['pr']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo) or not isinstance(pr, int) or pr < 1:
            raise ValueError('Invalid public GitHub seed identity')
        try:
            meta = api.get(f'/repos/{repo}')
            if meta.get('private'):
                raise ValueError('Only public repositories are allowed')
            comments, complete = api.pages(f'/repos/{repo}/pulls/{pr}/comments')
            selected = []
            for c in comments:
                if c.get('in_reply_to_id') or c.get('user', {}).get('type') != 'Bot' or c['user']['login'] not in config['bot_logins']:
                    continue
                sample = normalize_comment(repo, pr, c, now())
                if len(sample['comment_text']) < 50:
                    continue
                samples.append(sample)
                selected.append(sample['id'])
                summary = c.get('reactions', {})
                reactions, reactions_complete, error = [], False, None
                if summary.get('total_count') == 0:
                    reactions_complete = True
                else:
                    try:
                        reactions, reactions_complete = api.pages(f'/repos/{repo}/pulls/comments/{c["id"]}/reactions')
                    except (requests.RequestException, RuntimeError) as exc:
                        error = type(exc).__name__
                signals.append({'sample_id': sample['id'], 'object_kind': 'review_comment', 'source_object_id': c['id'],
                                'summary': summary, 'observed_at': now(), 'reactions_complete': reactions_complete,
                                'reaction_error': error, 'events': [{'id': r['id'], 'content': r['content'],
                                'created_at': r.get('created_at'), 'reactor_key': digest(str((r.get('user') or {}).get('id'))),
                                'reactor_type': (r.get('user') or {}).get('type'),
                                'is_self': (r.get('user') or {}).get('id') == c['user'].get('id')} for r in reactions]})
            audit.append({'repo': repo, 'pr': pr, 'comments': len(comments), 'selected': len(selected), 'pagination_complete': complete})
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            audit.append({'repo': repo, 'pr': pr, 'error': type(exc).__name__})
    samples = list({s['id']: s for s in samples}.values())
    signals = list({s['sample_id']: s for s in signals}.values())
    write_jsonl(root / 'normalized' / 'samples.jsonl', samples)
    write_jsonl(root / 'signals' / 'user-signals.jsonl', signals)
    result = {'captured_at': now(), 'samples': len(samples), 'requests_used': api.requests_used, 'sources': audit,
              'bot_counts': {b: sum(s['author_login'] == b for s in samples) for b in sorted({s['author_login'] for s in samples})},
              'samples_with_human_thumb': sum(any(e['reactor_type'] == 'User' and e['content'] in ('+1', '-1') and not e['is_self'] for e in s['events']) for s in signals)}
    write_json(root / 'manifests' / 'collection.json', result)
    return result
