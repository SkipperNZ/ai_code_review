"""Import an explicit public GitHub connector capture using the existing collector, offline."""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
from aicr.github import collect
from aicr.io import digest, read_json, write_json

ROUTE = re.compile(r'^/repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/pulls/(?:([1-9][0-9]*)/comments|comments/[1-9][0-9]*/reactions)\?per_page=100&page=([1-9][0-9]*))?$')


def import_capture(capture_path: Path, data: Path, bots: list[str]) -> dict:
    if data.exists():
        raise ValueError('Use a new data directory; existing captures must not be overwritten')
    capture = read_json(capture_path)
    datetime.fromisoformat(capture['captured_at'].replace('Z', '+00:00'))
    if not bots or any(not b.strip() for b in bots):
        raise ValueError('Explicit bot logins required')
    routes, seeds, repos, pages = {}, set(), set(), []
    for response in capture['responses']:
        route, body = response['route'], response['body']
        match = ROUTE.fullmatch(route)
        if not match:
            raise ValueError('Unsupported public capture route: ' + route)
        if route in routes:
            raise ValueError('Duplicate raw route in capture')
        repo, pr, page = match.groups()
        repos.add(repo)
        if pr:
            seeds.add((repo, int(pr)))
        if page:
            pages.append(int(page))
            if not isinstance(body, list) or len(body) > 100:
                raise ValueError('Expected a single bounded API page')
        routes[route] = body
    if not seeds:
        raise ValueError('No pull-request comment pages in capture')
    for repo in repos:
        meta = routes.get('/repos/' + repo)
        if not isinstance(meta, dict) or meta.get('private') is not False or meta.get('full_name') != repo:
            raise ValueError('Explicit public repository metadata required for ' + repo)
    for route, body in routes.items():
        write_json(data / 'raw/github' / (digest(route) + '.json'), {
            'route': route, 'body': body, 'captured_at': capture['captured_at'],
            'capture_transport': capture.get('capture_transport', 'user_supplied_capture'),
            'etag': None, 'rate_remaining': None})
    config = read_json(root / 'configs/default.example.json')
    config.update(bot_logins=bots, seeds=[{'repo': repo, 'pr': pr} for repo, pr in sorted(seeds)])
    config['github'].update(max_requests=0, max_pages=max(pages or [1]))
    write_json(data / 'manifests/import.json', {'source_capture_hash': digest(capture),
        'source_capture_path': str(capture_path.resolve()), 'captured_at': capture['captured_at'],
        'selection': capture.get('selection'), 'source_errors': capture.get('errors', []),
        'raw_routes': sorted(routes), 'bot_logins': bots, 'network_requests_allowed': 0,
        'missing_reaction_pages': 'remain incomplete/unknown, never synthesized from summary counts'})
    return collect(data, config)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path); parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--bot', action='append', required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(import_capture(args.capture, args.data, args.bot), ensure_ascii=False, indent=2))
