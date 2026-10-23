"""Derive the compact model response contract; final assessment schema stays stable."""
import argparse
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--whole-chunk', action='store_true', help='Emit the separate compact-0.3.0 contract without model-selected subranges')
args = parser.parse_args()
s = json.loads((root / 'schemas/assessment.schema.json').read_text(encoding='utf-8'))
s['$id'] = 'urn:aicr:judge-response:0.2.1'
s['title'] = 'Compact model response v0.2'
s['description'] = 'Model supplies judgments and references to shown chunks. Harness assigns identities and materializes exact citations.'
for name in ['schema_version', 'sample_id', 'run_id', 'context_mode', 'evidence']:
    s['required'].remove(name); s['properties'].pop(name)
for name in ['severity', 'complexity']:
    s['properties'][name]['required'].remove('scale_id')
    s['properties'][name]['properties'].pop('scale_id')
claim = s['properties']['claims']['items']
for name in ['claim_id', 'evidence_ids']:
    claim['required'].remove(name); claim['properties'].pop(name)
claim['allOf'] = [{'if': {'properties': {'kind': {'const': 'factual'}}}, 'then': {'required': ['evidence_links']}}]
claim['properties']['evidence_links'] = {'type': 'array', 'items': {
    'type': 'object', 'additionalProperties': False, 'required': ['source_chunk_id', 'relation'],
    'properties': {'source_chunk_id': {'type': 'string', 'minLength': 1},
                   'relation': {'enum': ['supports', 'refutes', 'context']},
                   'start_line': {'type': 'integer', 'minimum': 1}, 'end_line': {'type': 'integer', 'minimum': 1}},
    'dependentRequired': {'start_line': ['end_line'], 'end_line': ['start_line']}}}
for key in ['value']:
    s['properties']['correctness']['required'].remove(key)
    s['properties']['correctness']['properties'].pop(key)
output = 'judge-response.schema.json'
if args.whole_chunk:
    s['$id'] = 'urn:aicr:judge-response:0.3.0'
    s['title'] = 'Compact model response v0.3, whole shown chunks'
    s['description'] = 'Model supplies judgments and references to whole shown chunks. No model-selected line subranges; canonical assessment schema is unchanged.'
    link = claim['properties']['evidence_links']['items']
    link['properties'].pop('start_line'); link['properties'].pop('end_line'); link.pop('dependentRequired')
    output = 'judge-response-whole-chunk.schema.json'
(root / 'schemas' / output).write_text(json.dumps(s, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
