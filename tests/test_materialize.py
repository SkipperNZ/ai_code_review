import copy

from aicr.contracts import chunk, validate_assessment
from aicr.io import ROOT, read_json, read_jsonl
from aicr.materialize import compile_response


def fixture():
    a = copy.deepcopy(read_jsonl(ROOT / 'examples/assessments.jsonl')[0])
    ev = a.pop('evidence')[0]
    snapshot = {'id': ev['snapshot_id'], 'commit_sha': ev['commit_sha'], 'files': {ev['path']: {'text': ev['excerpt']}}}
    c = chunk(snapshot, ev['path'], 1, 3)
    for k in ['schema_version', 'sample_id', 'run_id', 'context_mode']: a.pop(k)
    for k in ['severity', 'complexity']: a[k].pop('scale_id')
    a['correctness'].pop('value')
    for claim in a['claims']:
        claim.pop('claim_id'); claim.pop('evidence_ids')
        claim['evidence_links'] = [{'source_chunk_id': c['source_chunk_id'], 'relation': 'supports'}]
    return a, snapshot, c


def compile_fixture(a, snapshot, c):
    return compile_response(a, read_json(ROOT / 'schemas/judge-response.schema.json'), snapshot, [c], 'synthetic', 'fixture', 'agent')


def test_reused_chunk_materializes_distinct_claim_links_without_inventing_text():
    raw, snapshot, c = fixture()
    raw['claims'].append(copy.deepcopy(raw['claims'][0]))
    a, state = compile_fixture(raw, snapshot, c)
    assert state['raw_schema_valid']
    assert [e['claim_id'] for e in a['evidence']] == ['c1', 'c2']
    assert [e['excerpt'] for e in a['evidence']] == [c['excerpt'], c['excerpt']]
    assert a['claims'][0]['verdict'] == raw['claims'][0]['verdict']
    v = validate_assessment(a, snapshot, [c], sample_id='synthetic', run_id='fixture', mode='agent')
    assert v['schema_valid'] and v['semantic_valid'] and v['evidence_valid']


def test_unknown_chunk_and_outside_range_never_materialize():
    raw, snapshot, c = fixture()
    link = raw['claims'][0]['evidence_links'][0]
    link['source_chunk_id'] = 'invented'
    a, state = compile_fixture(raw, snapshot, c)
    assert a is None and state['raw_schema_valid'] and not state['evidence_valid']
    link.update(source_chunk_id=c['source_chunk_id'], start_line=1, end_line=4)
    a, state = compile_fixture(raw, snapshot, c)
    assert a is None and not state['evidence_valid']


def test_claim_verdict_is_not_repaired_by_compiler():
    raw, snapshot, c = fixture()
    raw['claims'][0]['verdict'] = 'refuted'  # supports link and verified severity now contradict this
    a, _ = compile_fixture(raw, snapshot, c)
    assert a['claims'][0]['verdict'] == a['correctness']['value'] == 'refuted'
    v = validate_assessment(a, snapshot, [c], sample_id='synthetic', run_id='fixture', mode='agent')
    assert not v['semantic_valid']


def test_preference_may_omit_citations_but_factual_claim_may_not():
    raw, snapshot, c = fixture()
    preference = copy.deepcopy(raw['claims'][0])
    preference.update(kind='preference', verdict='not_applicable')
    preference.pop('evidence_links')
    raw['claims'].append(preference)
    a, state = compile_fixture(raw, snapshot, c)
    assert state['raw_schema_valid'] and a['claims'][1]['evidence_ids'] == []
    raw['claims'][0].pop('evidence_links')
    a, state = compile_fixture(raw, snapshot, c)
    assert a is None and not state['raw_schema_valid']
