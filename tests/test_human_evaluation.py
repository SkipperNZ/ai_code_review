import copy

from aicr.contracts import chunk
from aicr.evaluation import compare_humans
from aicr.io import ROOT, digest, read_jsonl, write_json, write_jsonl


def test_human_reference_rejects_blanks_and_keeps_disagreements(tmp_path):
    a = copy.deepcopy(read_jsonl(ROOT / 'examples/assessments.jsonl')[0])
    a['context_mode'] = 'agent'
    e = a['evidence'][0]
    snapshot = {'id': e['snapshot_id'], 'commit_sha': e['commit_sha'], 'files': {e['path']: {'text': e['excerpt']}}}
    c = chunk(snapshot, e['path'], 1, 3)
    e['source_chunk_id'] = c['source_chunk_id']
    row = {'sample_id': a['sample_id'], 'snapshot_id': snapshot['id'], 'annotation_source': 'human',
           'annotation_stage': 'repository', 'annotator_key': 'person-a', 'assessment': a, 'shown_chunks': [c]}
    write_json(tmp_path / 'snapshots' / (snapshot['id'] + '.json'), snapshot)
    write_jsonl(tmp_path / 'normalized/samples.jsonl', [{'id': a['sample_id'], 'snapshot_id': snapshot['id']}])
    annotation_path = tmp_path / 'human.jsonl'
    write_jsonl(annotation_path, [row, {**row, 'assessment': None}])
    r = compare_humans(annotation_path, {(a['sample_id'], 'agent'): a}, [a['sample_id']], tmp_path)
    assert r['accepted_annotations'] == 1 and len(r['rejected']) == 1
    assert r['modes']['agent']['correctness_agreement'] == 1
    other = copy.deepcopy(row)
    other['annotator_key'] = 'person-b'
    b = other['assessment']
    b['correctness']['value'] = b['claims'][0]['verdict'] = 'refuted'
    b['evidence'][0]['relation'] = 'refutes'
    b['severity'].update(value=None, basis='not_assessable')
    b['utility']['recommended_action'] = 'discard'
    write_jsonl(annotation_path, [row, other])
    r = compare_humans(annotation_path, {}, [a['sample_id']], tmp_path)
    assert r['disputed_samples'] == [a['sample_id']] and r['consensus_samples'] == 0
