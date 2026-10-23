import copy

from aicr.contracts import validate_assessment
from aicr.io import ROOT, read_json
from aicr.materialize import compile_response
from test_materialize import fixture


def compile_whole(raw, snapshot, c):
    return compile_response(raw, read_json(ROOT / 'schemas/judge-response-whole-chunk.schema.json'),
                            snapshot, [c], 'synthetic', 'fixture', 'agent')


def test_whole_chunk_contract_keeps_exact_source_and_verdict():
    raw, snapshot, c = fixture()
    before = copy.deepcopy(raw)
    result, validation = compile_whole(raw, snapshot, c)
    assert validation['raw_schema_valid']
    assert result['evidence'][0]['excerpt'] == c['excerpt']
    assert (result['evidence'][0]['start_line'], result['evidence'][0]['end_line']) == (c['start_line'], c['end_line'])
    assert raw == before
    state = validate_assessment(result, snapshot, [c], sample_id='synthetic', run_id='fixture', mode='agent')
    assert all(state[k] for k in ('schema_valid', 'semantic_valid', 'evidence_valid'))


def test_whole_chunk_contract_rejects_subranges_instead_of_silently_dropping_them():
    raw, snapshot, c = fixture()
    raw['claims'][0]['evidence_links'][0].update(start_line=1, end_line=2)
    result, validation = compile_whole(raw, snapshot, c)
    assert result is None and not validation['raw_schema_valid']


def test_whole_chunk_contract_still_rejects_unshown_sources_and_missing_support():
    raw, snapshot, c = fixture()
    raw['claims'][0]['evidence_links'][0]['source_chunk_id'] = 'not-shown'
    result, validation = compile_whole(raw, snapshot, c)
    assert result is None and not validation['evidence_valid']
    raw['claims'][0]['evidence_links'][0] = {'source_chunk_id': c['source_chunk_id'], 'relation': 'context'}
    result, _ = compile_whole(raw, snapshot, c)
    state = validate_assessment(result, snapshot, [c], sample_id='synthetic', run_id='fixture', mode='agent')
    assert state['evidence_valid'] and not state['semantic_valid']
