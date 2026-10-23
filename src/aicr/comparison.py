"""Paired engineering regression comparison; no inference of factual accuracy."""
from collections import Counter
from pathlib import Path

from .evaluation import latest_results
from .io import atomic_text, now, read_json, write_json


def compare_runs(baseline: Path, candidate: Path, mode: str = 'agent') -> dict:
    before, after = read_json(baseline / 'manifest.json'), read_json(candidate / 'manifest.json')
    if mode not in before['modes'] or mode not in after['modes']:
        raise ValueError('Requested mode must be planned in both runs')
    common = sorted(set(before['selected']) & set(after['selected']))
    if not common:
        raise ValueError('Runs have no common selected samples')
    for sid in common:
        if not before.get('sample_hashes', {}).get(sid) or before['sample_hashes'][sid] != after.get('sample_hashes', {}).get(sid):
            raise ValueError(f'Sample capture changed or hash is missing: {sid}')
    # Fail closed if any shared snapshot changed; comparison never substitutes current files.
    shared_snapshots = set(before['snapshot_hashes']) & set(after['snapshot_hashes'])
    if not shared_snapshots or any(not before['snapshot_hashes'][sid] or before['snapshot_hashes'][sid] != after['snapshot_hashes'][sid] for sid in shared_snapshots):
        raise ValueError('Shared snapshot hashes changed or are missing')
    sides = []
    for directory, manifest in [(baseline, before), (candidate, after)]:
        rows = {r['sample_id']: r for r in latest_results(directory) if r['mode'] == mode and r['sample_id'] in common}
        if any(r['run_id'] != manifest['id'] for r in rows.values()):
            raise ValueError('Result belongs to a different run')
        sides.append(rows)
    pairs = [{'sample_id': sid, 'baseline_status': sides[0].get(sid, {}).get('status', 'pending'),
              'candidate_status': sides[1].get(sid, {}).get('status', 'pending')} for sid in common]
    completed = [p for p in pairs if 'pending' not in (p['baseline_status'], p['candidate_status'])]
    summary = {}
    for side, rows in zip(['baseline', 'candidate'], sides):
        subset = [rows[p['sample_id']] for p in completed]
        summary[side] = {
            'statuses': dict(Counter(p[side + '_status'] for p in pairs)),
            'completed_pairs_ok': sum(r['status'] == 'ok' for r in subset),
            'completed_pairs_raw_schema_valid': sum(r.get('validation', {}).get('raw_schema_valid', False) for r in subset),
            'completed_pairs_evidence_valid': sum(r.get('validation', {}).get('evidence_valid', False) for r in subset),
            'completed_pairs_wall_seconds': round(sum(r['wall_seconds'] for r in subset), 3),
            'completed_pairs_tool_calls': sum(r.get('tool_calls', 0) for r in subset),
        }
    result = {
        'created_at': now(), 'baseline_run': before['id'], 'candidate_run': after['id'], 'mode': mode,
        'scope': 'paired_engineering_regression_only_not_factual_accuracy',
        'selection_caution': 'Selection may depend on baseline failures; this is not a holdout or population estimate.',
        'planned_common': len(common), 'completed_pairs': len(completed),
        'baseline_only_selected': len(set(before['selected']) - set(common)),
        'candidate_only_selected': len(set(after['selected']) - set(common)),
        'same_reported_deployment': bool(before.get('deployment')) and before.get('deployment') == after.get('deployment'),
        'weight_identity_verified': False, 'code_changed': before.get('code_hash') != after.get('code_hash'),
        'model_quality_change': None,
        'recovered': sum(p['baseline_status'] != 'ok' and p['candidate_status'] == 'ok' for p in completed),
        'regressed': sum(p['baseline_status'] == 'ok' and p['candidate_status'] != 'ok' for p in completed),
        'status_transitions': dict(Counter(p['baseline_status'] + ' -> ' + p['candidate_status'] for p in completed)),
        'summary': summary, 'pairs': pairs,
    }
    write_json(candidate / f'comparison-{mode}.json', result)
    lines = ['# Парная инженерная проверка', '',
             f"Baseline: `{before['id']}`; candidate: `{after['id']}`; mode: `{mode}`.", '',
             f'Общих запланированных samples: {len(common)}; завершённых пар: {len(completed)}.', '',
             '| На завершённых парах | Baseline | Candidate |', '| --- | --- | --- |']
    for title, key in [('Принято всеми валидаторами', 'completed_pairs_ok'),
                       ('Evidence validation', 'completed_pairs_evidence_valid'),
                       ('Вызовов инструментов', 'completed_pairs_tool_calls'),
                       ('Суммарное время, s', 'completed_pairs_wall_seconds')]:
        lines.append(f"| {title} | {summary['baseline'][key]} | {summary['candidate'][key]} |")
    lines += ['', f"Восстановлено: {result['recovered']}; регрессий: {result['regressed']}.", '',
              'Это проверка формата, происхождения цитат и согласованности полей. Фактическая точность не измерена. '
              'Выборка может быть отобрана по прежним ошибкам; переносить доли на весь корпус нельзя. '
              'Совпадение deployment metadata не доказывает неизменность весов.']
    atomic_text(candidate / f'COMPARISON-{mode}.md', '\n'.join(lines) + '\n')
    return result
