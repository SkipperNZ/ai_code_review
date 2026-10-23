from __future__ import annotations

from jsonschema import Draft202012Validator, FormatChecker

from .io import ROOT, digest, read_json


def validate_record(kind: str, value: dict) -> list[str]:
    schema = read_json(ROOT / 'schemas/records.schema.json')
    if kind not in schema['$defs']:
        raise ValueError('Unknown record kind')
    schema['$ref'] = '#/$defs/' + kind
    return [f'{"/".join(map(str, e.path))}: {e.message}' for e in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)]


def chunk(snapshot: dict, path: str, start: int, end: int) -> dict:
    file = snapshot['files'][path]
    lines = file['text'].splitlines()
    if not 1 <= start <= end <= len(lines):
        raise ValueError('chunk line range out of bounds')
    text = '\n'.join(lines[start - 1:end])
    chunk_id = digest('\n'.join([snapshot['id'], path, str(start), str(end), text]))[:24]
    return {'source_chunk_id': chunk_id, 'snapshot_id': snapshot['id'], 'commit_sha': snapshot['commit_sha'],
            'path': path, 'start_line': start, 'end_line': end, 'excerpt': text}


def aggregate(claims: list[dict]) -> str:
    values = {c['verdict'] for c in claims if c['kind'] == 'factual'}
    if not values:
        return 'not_applicable'
    if len(values) == 1:
        return next(iter(values))
    if 'supported' in values or 'partially_supported' in values:
        return 'partially_supported'
    return 'unverifiable'


def validate_assessment(value: dict, snapshot: dict, shown: list[dict], *, sample_id: str, run_id: str, mode: str, schema_override: dict | None = None) -> dict:
    """Validate shape and provenance, never claim to validate semantic truth."""
    validator = Draft202012Validator(schema_override or read_json(ROOT / 'schemas/assessment.schema.json'))
    shape = [f'{"/".join(map(str, e.path))}: {e.message}' for e in validator.iter_errors(value)]
    if shape:
        return {'schema_valid': False, 'semantic_valid': False, 'evidence_valid': False, 'errors': shape}
    semantic, evidence_errors = [], []
    for key, expected in [('sample_id', sample_id), ('run_id', run_id), ('context_mode', mode)]:
        if value[key] != expected:
            semantic.append(f'{key}: mismatched identity')
    claims = {c['claim_id']: c for c in value['claims']}
    evidence = {e['evidence_id']: e for e in value['evidence']}
    chunks = {c['source_chunk_id']: c for c in shown}
    for source in shown:
        try:
            expected_source = chunk(snapshot, source['path'], source['start_line'], source['end_line'])
            if source != expected_source:
                evidence_errors.append('shown chunk does not match the canonical snapshot')
        except (KeyError, ValueError, TypeError):
            evidence_errors.append('invalid shown chunk')
    if len(claims) != len(value['claims']) or len(evidence) != len(value['evidence']):
        semantic.append('duplicate claim/evidence IDs')
    for ev in evidence.values():
        if ev['claim_id'] not in claims:
            semantic.append('evidence has unknown claim')
        source = chunks.get(ev['source_chunk_id'])
        if not source:
            evidence_errors.append(f'{ev["evidence_id"]}: chunk was not shown')
            continue
        if any(ev[k] != source[k] for k in ('snapshot_id', 'commit_sha', 'path')):
            evidence_errors.append(f'{ev["evidence_id"]}: source identity mismatch')
            continue
        if not source['start_line'] <= ev['start_line'] <= ev['end_line'] <= source['end_line']:
            evidence_errors.append(f'{ev["evidence_id"]}: outside shown range')
            continue
        try:
            actual = chunk(snapshot, ev['path'], ev['start_line'], ev['end_line'])
            if ev['excerpt'] != actual['excerpt']:
                evidence_errors.append(f'{ev["evidence_id"]}: excerpt does not match blob')
        except (KeyError, ValueError):
            evidence_errors.append(f'{ev["evidence_id"]}: absent blob/range')
    for c in claims.values():
        linked = [evidence[k] for k in c['evidence_ids'] if k in evidence]
        if len(linked) != len(c['evidence_ids']) or any(e['claim_id'] != c['claim_id'] for e in linked):
            semantic.append(f'{c["claim_id"]}: bad evidence reference')
        if c['kind'] == 'preference' and c['verdict'] != 'not_applicable':
            semantic.append('preference verdict must be not_applicable')
        if c['kind'] == 'factual' and c['verdict'] == 'not_applicable':
            semantic.append('factual verdict cannot be not_applicable')
        required = {'supported': 'supports', 'refuted': 'refutes', 'partially_supported': 'supports'}.get(c['verdict'])
        if required and not any(e['relation'] == required for e in linked):
            semantic.append(f'{c["claim_id"]}: missing {required} evidence')
    if value['correctness']['value'] != aggregate(value['claims']):
        semantic.append('incorrect claim aggregation')
    if value['evaluability']['status'] == 'insufficient' and (not value['evaluability']['missing_context'] or not value['uncertainty_reasons']):
        semantic.append('insufficient context needs missing_context and uncertainty reason')
    if any(c['verdict'] == 'unverifiable' for c in claims.values()) and not value['uncertainty_reasons']:
        semantic.append('unverifiable needs uncertainty reason')
    if any(c['verdict'] == 'unverifiable' for c in claims.values()) and not value['evaluability']['missing_context']:
        semantic.append('unverifiable needs concrete missing context')
    severity = value['severity']
    if severity['basis'] == 'verified' and value['correctness']['value'] not in ('supported', 'partially_supported'):
        semantic.append('verified severity on unsupported factual problem')
    if (severity['value'] is None) != (severity['basis'] == 'not_assessable'):
        semantic.append('null severity and not_assessable basis must agree')
    if value['utility']['recommended_action'] == 'publish':
        if value['correctness']['value'] != 'supported':
            semantic.append('publish requires supported factual claims, including a policy claim for preference')
        if value['evaluability']['status'] != 'sufficient':
            semantic.append('publish requires sufficient context')
    return {'schema_valid': True, 'semantic_valid': not semantic, 'evidence_valid': not evidence_errors,
            'errors': semantic + evidence_errors}
