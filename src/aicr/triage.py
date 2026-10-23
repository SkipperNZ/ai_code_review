"""Post-hoc audit links. These records never become model inputs or corrected labels."""
from collections import Counter
from pathlib import Path

from .audit import signal_state
from .evaluation import latest_results
from .io import digest, now, read_json, read_jsonl, write_json, write_jsonl


def audit_flags(state: str, assessment: dict | None) -> list[str]:
    flags = []
    if state in ('conflicting', 'incomplete', 'unavailable'):
        flags.append('human_signal_' + state)
    if state == 'no_observed_human_thumb':
        flags.append('no_observed_human_thumb')
    if assessment is None:
        return flags + ['assessment_unavailable']
    verdict = assessment['correctness']['value']
    if state == 'positive' and verdict == 'refuted':
        flags.append('human_positive_teacher_refuted')
    if state == 'negative' and verdict == 'supported':
        flags.append('human_negative_teacher_supported')
    if assessment['evaluability']['status'] == 'insufficient' or any(
        c['verdict'] == 'unverifiable' for c in assessment['claims']
    ):
        flags.append('context_unresolved')
    if any(c['kind'] == 'preference' for c in assessment['claims']):
        flags.append('preference_present')
    return flags


def triage(directory: Path, data: Path, mode: str = 'agent') -> dict:
    manifest = read_json(directory / 'manifest.json')
    samples = {s['id']: s for s in read_jsonl(data / 'normalized/samples.jsonl')}
    signals_path = data / 'signals/user-signals.jsonl'
    signals = {s['sample_id']: s for s in read_jsonl(signals_path)}
    results = {r['sample_id']: r for r in latest_results(directory) if r['mode'] == mode}
    if mode not in manifest['modes']:
        raise ValueError('Mode is absent from this run')
    rows = []
    for sid in manifest['selected']:
        sample = samples[sid]
        if digest(sample) != manifest['sample_hashes'][sid]:
            raise ValueError('Sample capture differs from the run manifest')
        signal, result = signals.get(sid), results.get(sid)
        state = signal_state(signal) if signal is not None else 'unavailable'
        assessment = None
        if result and result['status'] == 'ok':
            assessment = read_json(result['assessment_ref'])
            if (assessment['sample_id'], assessment['run_id'], assessment['context_mode']) != (sid, manifest['id'], mode):
                raise ValueError('Assessment identity differs from run/sample/mode')
        rows.append({
            'schema_version': 'audit-link-0.1.0', 'sample_id': sid, 'run_id': manifest['id'],
            'mode': mode, 'source_url': sample['source_url'], 'strict_eligible': sample['strict_eligible'],
            'signal_state': state, 'signal_ref': str(signals_path.resolve()),
            'signal_hash': digest(signal) if signal is not None else None,
            'signal_window': 'all_observed_events_not_fixed_horizon',
            'attempt_status': result['status'] if result else 'not_completed',
            'assessment_ref': result['assessment_ref'] if assessment else None,
            'assessment_hash': digest(assessment) if assessment else None,
            'teacher_correctness': assessment['correctness']['value'] if assessment else None,
            'teacher_action': assessment['utility']['recommended_action'] if assessment else None,
            'missing_context': assessment['evaluability']['missing_context'] if assessment else [],
            'flags': audit_flags(state, assessment), 'explanation_status': 'unresolved',
            'reaction_error': None, 'human_adjudication_ref': None,
            'interpretation': 'observed_signal_and_model_assessment; no_user_intent_or_label_correction',
        })
    path = directory / ('audit-links-' + mode + '.jsonl')
    write_jsonl(path, rows)
    report = {'run_id': manifest['id'], 'mode': mode, 'created_at': now(), 'records': len(rows),
              'completed_assessments': sum(r['assessment_ref'] is not None for r in rows),
              'signal_states': dict(Counter(r['signal_state'] for r in rows)),
              'flags': dict(Counter(f for r in rows for f in r['flags'])),
              'output': str(path), 'model_requests': 0, 'source_labels_modified': False,
              'reaction_noise_estimate': None, 'human_reference_available': False}
    write_json(directory / ('triage-' + mode + '.json'), report)
    return report
