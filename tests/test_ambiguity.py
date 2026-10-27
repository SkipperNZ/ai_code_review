"""Controlled fixtures and scripted judges; these are not human-labelled real samples."""
import copy
import itertools
import json
from pathlib import Path

import pytest

from aicr import ambiguity
from aicr.ambiguity_contracts import (SCALE, candidate_rule, load_humans, outside_local,
                                    reaction_proxy, snippet_for, validate_stage)
from aicr.contracts import chunk
from aicr.io import ROOT, digest, read_json, write_json, write_jsonl


def fixture_data(tmp_path, guarded=True, sid='case'):
    texts = {'target.py': 'def render(user):\n    return user.name\n',
             'caller.py': 'user = lookup()\n' + ('if user is not None:\n    render(user)\n' if guarded else 'render(user)\n# lookup may return None\n')}
    snapshot = {'id': 'snap-' + sid, 'commit_sha': 'a' * 40, 'partial': False,
                'files': {p: {'text': t, 'text_sha256': digest(t)} for p, t in texts.items()}}
    sample = {'id': sid, 'provider': 'synthetic_fixture', 'repo_id': 'fixture/' + sid, 'created_at': '2026-01-01T00:00:00Z',
              'path': 'target.py', 'original_line': 2, 'original_commit_id': snapshot['commit_sha'],
              'snapshot_id': snapshot['id'], 'strict_eligible': True, 'source_url': 'https://example.invalid/' + sid,
              'comment_text': 'This function can receive None and crash; add a guard.',
              'body': 'UNTRUSTED_BODY_LABEL_SENTINEL', 'generator_rationale': 'RATIONALE_MUST_NOT_LEAK',
              'student_snippet': {'path': 'target.py', 'start_line': 1, 'end_line': 2}}
    data = tmp_path / 'data'
    write_jsonl(data / 'normalized/samples.jsonl', [sample])
    write_json(data / 'snapshots' / (snapshot['id'] + '.json'), snapshot)
    human = {'sample_id': sid, 'scale_id': SCALE, 'label': 'reject' if guarded else 'accept',
             'source_kind': 'synthetic_reference', 'source_ref': 'SYNTHETIC_HIDDEN_H_SIGNAL', 'annotator_key': None}
    human_file = data / 'human.jsonl'
    write_jsonl(human_file, [human])
    return data, sample, snapshot, human_file


def assessment(decision, source=None):
    return {'decision': decision, 'evaluability': 'insufficient' if decision == 'unknown' else 'sufficient',
            'rationale': 'Fixture decision, not a real model reference.',
            'missing_context': ['Callers and guards'] if decision == 'unknown' else [],
            'evidence_links': [] if source is None else [{'source_chunk_id': source['source_chunk_id'],
                'relation': 'supports' if decision == 'accept' else 'refutes'}]}


def test_all_candidate_combinations_and_unknown_is_not_a_negative():
    for l, r, h in itertools.product(['accept', 'reject', 'unknown'], repeat=3):
        out = candidate_rule({'decision': l}, {'decision': r}, {'scale_id': SCALE, 'label': h})
        assert out['candidate'] == (h != 'unknown' and r != 'unknown' and h == r and h != l)
    assert not candidate_rule(None, {'decision': 'accept'}, {'scale_id': SCALE, 'label': 'accept'})['candidate']
    assert not candidate_rule({'decision': 'reject'}, {'decision': 'accept'}, {'scale_id': 'factual', 'label': 'accept'})['candidate']


def test_snippet_is_exact_and_never_implicitly_expanded(tmp_path):
    _, sample, snapshot, _ = fixture_data(tmp_path)
    c, policy = snippet_for(sample, snapshot)
    assert c['excerpt'] == snapshot['files']['target.py']['text'].rstrip('\n')
    assert policy == 'explicit_student_range_v1'
    sample.pop('student_snippet')
    sample['diff_hunk'] = '@@ -1,2 +1,2 @@\n def render(user):\n-    return old\n+    return user.name'
    hunk, policy = snippet_for(sample, snapshot)
    assert hunk == c and policy == 'exact_right_diff_hunk_v1'
    sample['diff_hunk'] = sample['diff_hunk'].replace('user.name', 'future.name')
    with pytest.raises(ValueError, match='historical|original'):
        snippet_for(sample, snapshot)


def test_no_silent_truncation_or_missing_anchor(tmp_path):
    _, sample, snapshot, _ = fixture_data(tmp_path)
    with pytest.raises(ValueError, match='max_local_lines'):
        snippet_for(sample, snapshot, 1)
    sample['original_line'] = 50
    with pytest.raises(ValueError, match='anchor'):
        snippet_for(sample, snapshot)


def test_main_claim_cannot_be_hallucinated(tmp_path):
    _, sample, snapshot, _ = fixture_data(tmp_path)
    value = {'status': 'identified', 'claim_excerpt': 'An invented finding', 'rationale': 'fixture'}
    assert not validate_stage('claim', value, snapshot, [], [], sample['comment_text'])['consistency_valid']


def test_new_chunk_id_over_local_lines_is_not_outside_context(tmp_path):
    _, sample, snapshot, _ = fixture_data(tmp_path)
    local = chunk(snapshot, 'target.py', 1, 2)
    narrower = chunk(snapshot, 'target.py', 2, 2)
    assert local['source_chunk_id'] != narrower['source_chunk_id']
    assert not outside_local(narrower, [local])
    value = {'outcome': 'context_dependency_supported', 'resolved_decision': 'reject',
             'missing_local_premise': 'A guard exists', 'local_insufficiency_explanation': 'Caller unavailable locally',
             'rationale': 'fixture', 'decisive_links': [{'source_chunk_id': narrower['source_chunk_id'], 'relation': 'refutes'}]}
    v = validate_stage('verification', value, snapshot, [local, narrower], [local], sample['comment_text'])
    assert not v['evidence_valid']


def test_unshown_and_forged_sources_are_rejected(tmp_path):
    _, sample, snapshot, _ = fixture_data(tmp_path)
    local = chunk(snapshot, 'target.py', 1, 2)
    a = assessment('accept', {**local, 'source_chunk_id': 'not-shown'})
    assert not validate_stage('assessment', a, snapshot, [local], [local], sample['comment_text'])['evidence_valid']
    forged = {**local, 'excerpt': 'fabricated'}
    a = assessment('accept', forged)
    assert not validate_stage('assessment', a, snapshot, [forged], [local], sample['comment_text'])['evidence_valid']


def test_verifier_can_cite_local_background_only_in_separate_context_links(tmp_path):
    _, sample, snapshot, _ = fixture_data(tmp_path)
    local, outside = chunk(snapshot, 'target.py', 1, 2), chunk(snapshot, 'caller.py', 1, 3)
    value = {'outcome': 'context_dependency_supported', 'resolved_decision': 'reject',
             'missing_local_premise': 'Whether a caller guards the value',
             'local_insufficiency_explanation': 'The caller is not in the local snippet.', 'rationale': 'fixture',
             'decisive_links': [{'source_chunk_id': outside['source_chunk_id'], 'relation': 'refutes'}],
             'context_links': [{'source_chunk_id': local['source_chunk_id'], 'relation': 'context'}]}
    state = validate_stage('verification', value, snapshot, [local, outside], [local], sample['comment_text'])
    assert state['schema_valid'] and state['evidence_valid'] and state['consistency_valid']
    value['decisive_links'].append(value['context_links'][0])
    assert not validate_stage('verification', value, snapshot, [local, outside], [local], sample['comment_text'])['schema_valid']


def test_proxy_reactions_conflicts_self_and_missing_stay_distinct():
    bot = {'content': '-1', 'reactor_type': 'Bot', 'is_self': True}
    human = {'content': '+1', 'reactor_type': 'User', 'is_self': False}
    proxy = reaction_proxy('s', {'reactions_complete': True, 'events': [bot, human]}, 'fixture')
    assert proxy['label'] == 'accept' and not proxy['human_verified'] and proxy['source_kind'] == 'thumb_proxy'
    assert reaction_proxy('s', None, 'fixture')['label'] == 'unknown'
    signal = {'reactions_complete': True, 'events': [human, {**human, 'content': '-1'}]}
    assert reaction_proxy('s', signal, 'fixture')['signal_state'] == 'conflicting'
    assert reaction_proxy('s', signal, 'fixture')['label'] == 'unknown'


def test_synthetic_reference_cannot_masquerade_as_human(tmp_path):
    _, _, _, humans = fixture_data(tmp_path)
    with pytest.raises(ValueError, match='synthetic-demo'):
        load_humans(humans)
    assert load_humans(humans, allow_synthetic=True)['case']['source_kind'] == 'synthetic_reference'


def test_conflicting_human_file_is_not_silently_aggregated(tmp_path):
    _, _, _, humans = fixture_data(tmp_path)
    rows = [json.loads(line) for line in humans.read_text().splitlines()]
    write_jsonl(humans, rows + [{**rows[0], 'label': 'accept'}])
    with pytest.raises(ValueError, match='Duplicate'):
        load_humans(humans, allow_synthetic=True)


def test_no_human_means_no_model_calls_when_filtering(tmp_path, monkeypatch):
    data, _, _, _ = fixture_data(tmp_path)
    def unexpected(_):
        pytest.fail('Endpoint must not be contacted for empty eligible selection')
    monkeypatch.setattr(ambiguity, 'doctor', unexpected)
    with pytest.raises(ValueError, match='No eligible'):
        ambiguity.run_ambiguity(data, tmp_path / 'runs', {}, only_with_human=True)


def fake_transport(calls, *, bad_repository=False, local_changed=False, disagree_verifier=False):
    def execute(job, config, directory, execution):
        stage = Path(job['runtime_dir']).parents[1].name
        calls.append((stage, copy.deepcopy(job)))
        visible = json.dumps({k: job[k] for k in ['task', 'sample_id', 'run_id', 'mode', 'context', 'system_prompt', 'schema']})
        for marker in ['UNTRUSTED_BODY_LABEL_SENTINEL', 'RATIONALE_MUST_NOT_LEAK', 'SYNTHETIC_HIDDEN_H_SIGNAL']:
            assert marker not in visible
        snapshot = job['snapshot']
        local = chunk(snapshot, 'target.py', 1, 2)
        outside = chunk(snapshot, 'caller.py', 1, 3)
        decision = 'reject' if 'if user is not None:' in outside['excerpt'] else 'accept'
        shown = list(job['context']['chunks'])
        if stage == 'E':
            value = {'status': 'identified', 'claim_excerpt': job['context']['comment'], 'rationale': 'fixture extractor'}
        elif stage in ('R', 'V'):
            shown = [local, outside]
            if stage == 'R':
                value = assessment(decision, outside)
                if bad_repository:
                    value['evidence_links'][0]['source_chunk_id'] = 'not-shown'
            else:
                if disagree_verifier:
                    decision = 'accept' if decision == 'reject' else 'reject'
                value = {'outcome': 'context_dependency_supported', 'resolved_decision': decision,
                         'missing_local_premise': 'Whether the caller checks user',
                         'local_insufficiency_explanation': 'The local function does not show its callers.',
                         'rationale': 'Fixture evidence, not real validation.',
                         'decisive_links': [{'source_chunk_id': outside['source_chunk_id'], 'relation': 'refutes' if decision == 'reject' else 'supports'}]}
        elif stage == 'L_plus_context':
            value = assessment(decision, outside)
        elif stage == 'L_repeat' and local_changed:
            value = assessment(decision, local)
        else:
            value = assessment('unknown')
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / 'input.json', {k: v for k, v in job.items() if k != 'snapshot'})
        write_json(directory / 'shown-chunks.json', shown)
        return {'transport_status': None, 'wall_seconds': .01, 'events': [],
                'final': {'status': 'candidate', 'assessment': value, 'shown_chunks': shown, 'requests': 1,
                          'tool_calls': int(stage in ('R', 'V')), 'generated_tokens': 10, 'format_repair': False}}
    return execute


@pytest.mark.parametrize('guarded', [True, False])
def test_full_protocol_same_local_input_different_project(tmp_path, monkeypatch, guarded):
    data, sample, _, humans = fixture_data(tmp_path, guarded)
    calls = []
    monkeypatch.setattr(ambiguity, 'execute_pi', fake_transport(calls))
    monkeypatch.setattr(ambiguity, 'doctor', lambda _: {'ok': True, 'deployment_fingerprint': 'fixture'})
    config = read_json(ROOT / 'configs/default.example.json')
    result = ambiguity.run_ambiguity(data, tmp_path / 'runs', config, human_file=humans, synthetic_demo=True)
    path = Path(result['directory']) / sample['id'] / 'case.json'
    case = read_json(path)
    assert case['candidate'] and case['conclusion'] == 'model_supported_context_dependency'
    assert case['ambiguity_gold_label'] is None
    assert [name for name, _ in calls] == ['E', 'L', 'R', 'L_repeat', 'V', 'L_plus_context']
    jobs = dict(calls)
    assert jobs['L']['context'] == jobs['L_repeat']['context']
    assert jobs['L']['system_prompt'] == jobs['R']['system_prompt']
    assert 'core_claim' in jobs['V']['context'] and 'decision' not in jobs['V']['context']
    assert result['metrics']['human_context_reference_available'] is False
    manifest_before = (Path(result['directory']) / 'manifest.json').read_bytes()
    again = ambiguity.run_ambiguity(data, tmp_path / 'runs', config, human_file=humans, synthetic_demo=True)
    assert again['run_id'] == result['run_id'] and len(calls) == 6
    assert again['executed_now'] == {'stages_executed_now': 0, 'model_requests_now': 0}
    assert (Path(result['directory']) / 'manifest.json').read_bytes() == manifest_before
    case['conclusion'] = 'modified'
    write_json(path, case)
    with pytest.raises(ValueError, match='contents changed'):
        ambiguity.evaluate_ambiguity(Path(result['directory']))


@pytest.mark.parametrize('option,conclusion', [('bad_repository', 'not_selected'),
                                             ('local_changed', 'local_instability_or_repeat_unavailable'),
                                             ('disagree_verifier', 'verifier_disagrees_with_repository')])
def test_protocol_cannot_confirm_on_invalid_or_unstable_assessments(tmp_path, monkeypatch, option, conclusion):
    data, sample, _, humans = fixture_data(tmp_path)
    calls = []
    monkeypatch.setattr(ambiguity, 'execute_pi', fake_transport(calls, **{option: True}))
    monkeypatch.setattr(ambiguity, 'doctor', lambda _: {'ok': True, 'deployment_fingerprint': 'fixture'})
    out = ambiguity.run_ambiguity(data, tmp_path / 'runs', read_json(ROOT / 'configs/default.example.json'),
                                  human_file=humans, synthetic_demo=True)
    case = read_json(Path(out['directory']) / sample['id'] / 'case.json')
    assert case['conclusion'] == conclusion and case['ambiguity_gold_label'] is None
    if option == 'bad_repository':
        assert not case['candidate'] and case['status'] == 'assessment_failure'
        assert 'V' not in dict(calls)


def test_unsafe_snapshot_is_rejected_before_read_or_preflight(tmp_path, monkeypatch):
    data, sample, _, _ = fixture_data(tmp_path)
    sample['snapshot_id'] = '../private'
    write_jsonl(data / 'normalized/samples.jsonl', [sample])
    monkeypatch.setattr(ambiguity, 'doctor', lambda _: pytest.fail('Unsafe snapshot reached preflight'))
    with pytest.raises(ValueError, match='Unsafe snapshot'):
        ambiguity.run_ambiguity(data, tmp_path / 'runs', {}, synthetic_demo=True, human_file=data / 'human.jsonl')


def test_changed_source_requires_fresh_process_before_preflight(tmp_path, monkeypatch):
    data, _, _, humans = fixture_data(tmp_path)
    monkeypatch.setattr(ambiguity, '_LOADED_SOURCE_HASH', 'stale-import')
    monkeypatch.setattr(ambiguity, 'doctor', lambda _: pytest.fail('Changed code reached the model preflight'))
    with pytest.raises(RuntimeError, match='fresh CLI'):
        ambiguity.run_ambiguity(data, tmp_path / 'runs', {}, synthetic_demo=True, human_file=humans)


def test_duplicate_sample_identity_is_rejected_before_selection(tmp_path, monkeypatch):
    data, sample, _, humans = fixture_data(tmp_path)
    write_jsonl(data / 'normalized/samples.jsonl', [sample, sample])
    monkeypatch.setattr(ambiguity, 'doctor', lambda _: pytest.fail('Duplicate reached preflight'))
    with pytest.raises(ValueError, match='Duplicate normalized'):
        ambiguity.run_ambiguity(data, tmp_path / 'runs', {}, synthetic_demo=True, human_file=humans)
