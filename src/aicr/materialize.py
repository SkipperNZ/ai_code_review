"""Compile model-selected evidence anchors into canonical records; never change verdicts."""
import copy

from jsonschema import Draft202012Validator

from .contracts import aggregate, chunk


def compile_response(raw: dict, schema: dict, snapshot: dict, shown: list[dict], sample_id: str, run_id: str, mode: str) -> tuple[dict | None, dict]:
    errors = [f'{"/".join(map(str, e.path))}: {e.message}' for e in Draft202012Validator(schema).iter_errors(raw)]
    if errors:
        return None, {'raw_schema_valid': False, 'schema_valid': False, 'semantic_valid': False, 'evidence_valid': False, 'errors': errors}
    sources = {c['source_chunk_id']: c for c in shown}
    result = copy.deepcopy(raw)
    result.update(schema_version='0.1.0', sample_id=sample_id, run_id=run_id, context_mode=mode, evidence=[])
    result['severity']['scale_id'] = 'severity-nit-minor-serious-critical-v1'
    result['complexity']['scale_id'] = 'complexity-1-5-v1'
    for i, claim in enumerate(result['claims'], 1):
        claim['claim_id'] = f'c{i}'
        claim['evidence_ids'] = []
        for link in claim.pop('evidence_links', []):
            source = sources.get(link['source_chunk_id'])
            if not source:
                errors.append(f'c{i}: chunk was not shown')
                continue
            start, end = link.get('start_line', source['start_line']), link.get('end_line', source['end_line'])
            if not source['start_line'] <= start <= end <= source['end_line']:
                errors.append(f'c{i}: selected range outside shown chunk')
                continue
            try:
                citation = chunk(snapshot, source['path'], start, end)
                # Identity of the source chunk is retained, even when selecting a subrange.
                citation['source_chunk_id'] = source['source_chunk_id']
                eid = f'e{len(result["evidence"]) + 1}'
                result['evidence'].append({**citation, 'evidence_id': eid, 'claim_id': claim['claim_id'], 'relation': link['relation']})
                claim['evidence_ids'].append(eid)
            except (ValueError, KeyError):
                errors.append(f'c{i}: absent source blob or range')
    if errors:
        return None, {'raw_schema_valid': True, 'schema_valid': False, 'semantic_valid': False, 'evidence_valid': False, 'errors': errors}
    result['correctness']['value'] = aggregate(result['claims'])
    return result, {'raw_schema_valid': True, 'errors': []}
