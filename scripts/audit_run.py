"""Offline attempt/repair audit; never calls a model or changes assessments."""
import argparse
import csv
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from aicr.evaluation import latest_results
from aicr.io import atomic_text, digest, now, read_json, write_json


def parse_text(event):
    text = ''.join(c.get('text', '') for c in event['data']['content'] if c.get('type') == 'text')
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except ValueError:
        return None


def repair_audit(result):
    events = [json.loads(line) for line in Path(result['trace_ref']).read_text(encoding='utf-8').splitlines()]
    rejected = next((i for i, e in enumerate(events) if e['type'] == 'format_rejected'), None)
    before_events = [e for e in events[:rejected] if e['type'] == 'assistant'] if rejected is not None else []
    after_events = [e for e in events[rejected + 1:] if e['type'] == 'assistant'] if rejected is not None else []
    before = parse_text(before_events[-1]) if before_events else None
    after = parse_text(after_events[-1]) if after_events else None
    row = {'sample_id': result['sample_id'], 'mode': result['mode'], 'status': result['status'],
           'before_parseable': before is not None, 'after_parseable': after is not None,
           'compared_fields': [], 'changed_fields': []}
    if before is None or after is None:
        return row
    for field, names in [('evaluability', ['status', 'required_context']), ('severity', ['value', 'basis']),
                         ('complexity', ['value']), ('utility', ['recommended_action'])]:
        for name in names:
            b, a = before.get(field), after.get(field)
            if isinstance(b, dict) and isinstance(a, dict) and name in b and name in a:
                label = field + '.' + name
                row['compared_fields'].append(label)
                if b[name] != a[name]:
                    row['changed_fields'].append(label)
    bc, ac = before.get('claims'), after.get('claims')
    if isinstance(bc, list) and isinstance(ac, list) and all(isinstance(c, dict) for c in bc + ac):
        row['compared_fields'].append('claim_text_kind_verdict_sequence')
        projection = lambda claims: [(c.get('text'), c.get('kind'), c.get('verdict')) for c in claims]
        if projection(bc) != projection(ac):
            row['changed_fields'].append('claim_text_kind_verdict_sequence')
        elif all('evidence_links' in c for c in bc + ac):
            row['compared_fields'].append('claim_evidence_links')
            if [c['evidence_links'] for c in bc] != [c['evidence_links'] for c in ac]:
                row['changed_fields'].append('claim_evidence_links')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    results = latest_results(args.directory)
    manifest = read_json(args.directory / 'manifest.json')
    repairs = [repair_audit(r) for r in results if r.get('format_repair')]
    failures = [{'sample_id': r['sample_id'], 'mode': r['mode'], 'status': r['status'],
                 'errors': r.get('validation', {}).get('errors', []), 'runner_error': r.get('error'),
                 'trace_ref': r['trace_ref']} for r in results if r['status'] != 'ok']
    report = {'run_id': manifest['id'], 'audited_at': now(), 'audit_script_sha256': digest(Path(__file__).read_text(encoding='utf-8')),
              'completed': len(results), 'planned': len(manifest['selected']) * len(manifest['modes']),
              'status_counts': dict(Counter(r['status'] for r in results)),
              'repair_audit': {'count': len(repairs), 'parseable_pairs': sum(r['before_parseable'] and r['after_parseable'] for r in repairs),
                               'pairs_with_changed_compared_fields': sum(bool(r['changed_fields']) for r in repairs), 'rows': repairs,
                               'scope': 'Only listed fields present before and after repair; no semantic equivalence or factual truth claim.'},
              'failures': failures, 'assessments_modified': False, 'model_requests': 0}
    write_json(args.directory / 'diagnostics.json', report)
    out = io.StringIO(newline='')
    columns = ['sample_id', 'mode', 'status', 'wall_seconds', 'strict_eligible', 'format_repair',
               'requests', 'tool_calls', 'generated_tokens', 'raw_schema_valid', 'schema_valid', 'semantic_valid', 'evidence_valid']
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    for result in results:
        row = {**result, **result.get('validation', {})}
        writer.writerow({k: row.get(k) for k in columns})
    atomic_text(args.directory / 'attempt-summary.csv', out.getvalue())
    print(json.dumps({k: v for k, v in report.items() if k not in ['failures', 'repair_audit']} | {
        'format_repairs': len(repairs), 'repair_field_changes': report['repair_audit']['pairs_with_changed_compared_fields']}, indent=2))


if __name__ == '__main__':
    main()
