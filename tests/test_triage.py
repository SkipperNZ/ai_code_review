import copy

import pytest

from aicr.audit import signal_state
from aicr.io import ROOT, digest, read_jsonl, write_json, write_jsonl
from aicr.triage import audit_flags, triage


def test_disagreement_is_not_a_corrected_label(tmp_path):
    a = copy.deepcopy(read_jsonl(ROOT / 'examples/assessments.jsonl')[0])
    a.update(run_id='run', context_mode='agent', sample_id='synthetic-supported')
    a['correctness']['value'] = 'refuted'
    sid = a['sample_id']
    sample = {'id': sid, 'source_url': 'https://example.org/pr/1', 'strict_eligible': True}
    signal = {'sample_id': sid, 'reactions_complete': True, 'events': [
        {'content': '+1', 'reactor_type': 'User', 'is_self': False},
        {'content': '-1', 'reactor_type': 'Bot', 'is_self': True},
    ]}
    run, data = tmp_path / 'run', tmp_path / 'data'
    assessment_path = run / sid / 'agent/attempt-1/assessment.json'
    write_json(assessment_path, a)
    write_json(assessment_path.with_name('result.json'), {'sample_id': sid, 'mode': 'agent', 'status': 'ok',
        'finished_at': '2026-01-01T00:00:00Z', 'assessment_ref': str(assessment_path)})
    write_json(run / 'manifest.json', {'id': 'run', 'modes': ['agent'], 'selected': [sid], 'sample_hashes': {sid: digest(sample)}})
    write_jsonl(data / 'normalized/samples.jsonl', [sample])
    write_jsonl(data / 'signals/user-signals.jsonl', [signal])
    before = (data / 'signals/user-signals.jsonl').read_bytes()
    report = triage(run, data)
    row = read_jsonl(run / 'audit-links-agent.jsonl')[0]
    assert row['signal_state'] == 'positive'
    assert 'human_positive_teacher_refuted' in row['flags']
    assert row['reaction_error'] is None and row['explanation_status'] == 'unresolved'
    assert report['model_requests'] == 0 and report['reaction_noise_estimate'] is None
    assert (data / 'signals/user-signals.jsonl').read_bytes() == before
    write_jsonl(data / 'normalized/samples.jsonl', [{**sample, 'strict_eligible': False}])
    with pytest.raises(ValueError, match='capture differs'):
        triage(run, data)


def test_missing_or_conflicting_signal_never_becomes_negative():
    bot_only = {'reactions_complete': True, 'events': [
        {'content': v, 'reactor_type': 'Bot', 'is_self': True} for v in ['+1', '-1']]}
    assert signal_state(bot_only) == 'no_observed_human_thumb'
    assert audit_flags(signal_state(bot_only), None) == ['no_observed_human_thumb', 'assessment_unavailable']
    assert audit_flags('conflicting', None) == ['human_signal_conflicting', 'assessment_unavailable']
    assert audit_flags('incomplete', None) == ['human_signal_incomplete', 'assessment_unavailable']


def test_context_and_preference_are_independent_of_reaction_disagreement():
    a = {'correctness': {'value': 'supported'}, 'evaluability': {'status': 'insufficient'},
         'claims': [{'kind': 'factual', 'verdict': 'unverifiable'}, {'kind': 'preference', 'verdict': 'not_applicable'}]}
    assert audit_flags('negative', a) == ['human_negative_teacher_supported', 'context_unresolved', 'preference_present']
    assert audit_flags('positive', a) == ['context_unresolved', 'preference_present']


@pytest.mark.parametrize('event', [
    {'content': '-1', 'reactor_type': None, 'is_self': False},
    {'content': '-1', 'reactor_type': 'Mannequin', 'is_self': False},
    {'content': '-1', 'reactor_type': 'User', 'is_self': None},
])
def test_unknown_actor_never_becomes_an_unambiguous_positive(event):
    signal = {'reactions_complete': True, 'events': [
        {'content': '+1', 'reactor_type': 'User', 'is_self': False}, event]}
    assert signal_state(signal) == 'incomplete'
    assert 'human_signal_incomplete' in audit_flags(signal_state(signal), None)
