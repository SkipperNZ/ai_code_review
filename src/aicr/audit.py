from collections import Counter
from pathlib import Path

from .contracts import validate_record
from .io import digest, read_json, read_jsonl, safe_repo_path, write_json


def signal_state(signal: dict) -> str:
    votes = {e['content'] for e in signal['events'] if e.get('reactor_type') == 'User' and e.get('is_self') is False and e['content'] in ('+1', '-1')}
    if len(votes) == 2:
        return 'conflicting'
    ambiguous_actor = any(e['content'] in ('+1', '-1') and
                          (e.get('reactor_type') not in ('User', 'Bot') or
                           (e.get('reactor_type') == 'User' and not isinstance(e.get('is_self'), bool)))
                          for e in signal['events'])
    if not signal['reactions_complete'] or ambiguous_actor:
        return 'incomplete'
    return 'positive' if votes == {'+1'} else 'negative' if votes == {'-1'} else 'no_observed_human_thumb'


def audit_data(data: Path) -> dict:
    errors, counts = [], Counter()
    samples = read_jsonl(data / 'normalized/samples.jsonl')
    signals = read_jsonl(data / 'signals/user-signals.jsonl')
    ids = {s['id'] for s in samples}
    for kind, rows in [('sample', samples), ('signal', signals)]:
        for r in rows:
            key = r.get('id', r.get('sample_id'))
            errors += [f'{kind}/{key}: {e}' for e in validate_record(kind, r)]
            counts[kind] += 1
    for s in samples:
        if digest(s['body']) != s['body_hash']:
            errors.append(f'{s["id"]}: body hash mismatch')
        if s['strict_eligible'] and (s['body_history_status'] != 'exact_at_t0' or not s['snapshot_id'] or s['eligibility_reasons']):
            errors.append(f'{s["id"]}: incorrect strict eligibility')
    for s in signals:
        if s['sample_id'] not in ids:
            errors.append(f'{s["sample_id"]}: orphan signal')
    for path in (data / 'snapshots').glob('*.json'):
        snapshot = read_json(path)
        errors += [f'{path.name}: {e}' for e in validate_record('snapshot', snapshot)]
        for name, f in snapshot['files'].items():
            if not safe_repo_path(name) or digest(f['text']) != f['text_sha256']:
                errors.append(f'{path.name}/{name}: path or content hash invalid')
        counts['snapshot'] += 1
    result = {'valid': not errors, 'counts': dict(counts), 'errors': errors,
              'signal_states': dict(Counter(signal_state(s) for s in signals)),
              'availability': dict(Counter(s['snapshot_status'] for s in samples)),
              'body_history': dict(Counter(s['body_history_status'] for s in samples)),
              'strict_eligible': sum(s['strict_eligible'] for s in samples)}
    write_json(data / 'manifests/data-audit.json', result)
    return result
