"""L/R/H contracts and mechanical checks, never a verifier of factual truth."""
import re

from jsonschema import Draft202012Validator

from .audit import signal_state
from .contracts import chunk
from .io import ROOT, digest, read_json, read_jsonl

SCALE = 'comment-endorsement-v1'
PROTOCOL = 'ambiguity-1.0.2'
STAGES = {'E': 'claim', 'L': 'assessment', 'R': 'assessment', 'V': 'verification',
          'L_repeat': 'assessment', 'L_plus_context': 'assessment'}


def schema_for(kind: str, root=ROOT) -> dict:
    if kind not in {'claim', 'assessment', 'verification', 'human'}:
        raise ValueError('Unknown ambiguity contract')
    return read_json(root / f'schemas/ambiguity-{kind}.schema.json')


def snippet_for(sample: dict, snapshot: dict, max_lines=160) -> tuple[dict, str]:
    """No implicit +/- window: use the supplied exact range or the anchored RIGHT hunk."""
    provided = sample.get('student_snippet')
    if provided is not None:
        if not isinstance(provided, dict) or set(provided) - {'path', 'start_line', 'end_line', 'excerpt'}:
            raise ValueError('Invalid student_snippet envelope')
        if provided.get('path', sample['path']) != sample['path']:
            raise ValueError('Student snippet must use the comment anchor path')
        c = chunk(snapshot, sample['path'], provided['start_line'], provided['end_line'])
        if 'excerpt' in provided and provided['excerpt'] != c['excerpt']:
            raise ValueError('Student snippet differs from the historical blob')
        policy = 'explicit_student_range_v1'
    else:
        if sample.get('side', 'RIGHT') != 'RIGHT':
            raise ValueError('Only RIGHT historical hunks are supported')
        rows = sample.get('diff_hunk', '').splitlines()
        headers = [i for i, row in enumerate(rows) if row.startswith('@@')]
        if headers != [0]:
            raise ValueError('A single exact diff hunk or explicit student_snippet is required')
        match = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', rows[0])
        if not match:
            raise ValueError('Malformed diff hunk header')
        visible = []
        for row in rows[1:]:
            if row.startswith((' ', '+')):
                visible.append(row[1:])
            elif row.startswith(('-', '\\')):
                continue
            else:
                raise ValueError('Malformed diff hunk row')
        start = int(match.group(1))
        c = chunk(snapshot, sample['path'], start, start + len(visible) - 1)
        if c['excerpt'] != '\n'.join(visible):
            raise ValueError('Diff snippet differs from the original SHA blob')
        policy = 'exact_right_diff_hunk_v1'
    anchor = sample.get('original_line')
    if anchor is None or not c['start_line'] <= anchor <= c['end_line']:
        raise ValueError('Historical comment anchor is outside the snippet')
    if c['end_line'] - c['start_line'] + 1 > max_lines:
        raise ValueError('Snippet exceeds max_local_lines; provide the actual student range, do not truncate silently')
    if not c['excerpt'].strip():
        raise ValueError('Empty local snippet')
    return c, policy


def outside_local(c: dict, local: list[dict]) -> bool:
    return not any(c['path'] == s['path'] and c['start_line'] <= s['end_line'] and s['start_line'] <= c['end_line'] for s in local)


def validate_stage(kind: str, value: dict, snapshot: dict, shown: list[dict], local: list[dict], comment: str, schema: dict | None = None) -> dict:
    shape = [f'{"/".join(map(str, e.path))}: {e.message}' for e in Draft202012Validator(schema or schema_for(kind)).iter_errors(value)]
    if shape:
        return {'schema_valid': False, 'evidence_valid': False, 'consistency_valid': False, 'errors': shape}
    errors, source_errors = [], []
    sources = {c['source_chunk_id']: c for c in shown}
    for c in shown:
        try:
            if c != chunk(snapshot, c['path'], c['start_line'], c['end_line']):
                source_errors.append('Shown chunk differs from canonical snapshot')
        except (KeyError, TypeError, ValueError):
            source_errors.append('Invalid shown source')
    if kind == 'claim':
        excerpt = value['claim_excerpt']
        if value['status'] == 'identified' and (not excerpt or not excerpt.strip() or excerpt not in comment):
            errors.append('Main claim must be an exact nonempty excerpt of the comment')
        if value['status'] == 'not_identified' and excerpt is not None:
            errors.append('not_identified requires null claim_excerpt')
        links = []
    else:
        links = value['evidence_links'] if kind == 'assessment' else value['decisive_links'] + value.get('context_links', [])
    for link in links:
        source = sources.get(link['source_chunk_id'])
        if source is None:
            source_errors.append('Evidence chunk was not shown')
        elif not source['excerpt'].strip():
            source_errors.append('Empty evidence chunk')
    if kind == 'assessment':
        decision = value['decision']
        if decision == 'unknown':
            if value['evaluability'] != 'insufficient' or not value['missing_context']:
                errors.append('Unknown requires insufficient evaluability and concrete missing context')
        else:
            expected = 'supports' if decision == 'accept' else 'refutes'
            if value['evaluability'] != 'sufficient' or not any(e['relation'] == expected for e in links):
                errors.append('Known decision requires sufficient context and matching evidence relation')
    if kind == 'verification' and value['outcome'] == 'context_dependency_supported':
        decisive = value['decisive_links']
        decision = value['resolved_decision']
        expected = 'supports' if decision == 'accept' else 'refutes'
        if decision == 'unknown' or not value['missing_local_premise'] or not value['local_insufficiency_explanation']:
            errors.append('Context dependency requires a resolved decision and concrete missing premise/explanation')
        if not decisive or not any(e['relation'] == expected for e in decisive):
            errors.append('Context dependency requires decisive matching evidence')
        for link in decisive:
            source = sources.get(link['source_chunk_id'])
            if source and not outside_local(source, local):
                source_errors.append('Decisive chunk must be entirely outside the local snippet; a new ID is insufficient')
    return {'schema_valid': True, 'evidence_valid': not source_errors, 'consistency_valid': not errors,
            'errors': errors + source_errors}


def materialize_links(value: dict, shown: list[dict], local: list[dict]) -> list[dict]:
    sources = {c['source_chunk_id']: c for c in shown}
    groups = [(value.get('evidence_links', []), 'assessment'), (value.get('decisive_links', []), 'decisive'),
              (value.get('context_links', []), 'context')]
    return [{**sources[e['source_chunk_id']], 'relation': e['relation'], 'evidence_role': role,
             'entirely_outside_local': outside_local(sources[e['source_chunk_id']], local)}
            for links, role in groups for e in links]


def reaction_proxy(sample_id: str, signal: dict | None, source_ref: str) -> dict:
    state = signal_state(signal) if signal is not None else 'unavailable'
    label = {'positive': 'accept', 'negative': 'reject'}.get(state, 'unknown')
    return {'sample_id': sample_id, 'scale_id': SCALE, 'label': label, 'source_kind': 'thumb_proxy',
            'mapping_id': 'human-thumb-endorsement-proxy-v1', 'source_ref': source_ref,
            'signal_hash': digest(signal) if signal is not None else None, 'signal_state': state,
            'observation_window': 'all_observed_not_fixed_horizon', 'human_verified': False}


def load_humans(path, *, allow_synthetic=False) -> dict:
    rows = {}
    for row in read_jsonl(path):
        errors = list(Draft202012Validator(schema_for('human')).iter_errors(row))
        if errors:
            raise ValueError('Invalid human endorsement envelope: ' + errors[0].message)
        if row['sample_id'] in rows:
            raise ValueError('Duplicate sample in human file; supply an explicitly adjudicated label, not a silent majority vote')
        if row['source_kind'] == 'manual' and not row['annotator_key']:
            raise ValueError('Manual annotation requires annotator_key')
        if row['source_kind'] == 'synthetic_reference' and not allow_synthetic:
            raise ValueError('Synthetic references require the explicit synthetic-demo option')
        rows[row['sample_id']] = {**row, 'human_verified': row['source_kind'] == 'manual'}
    return rows


def candidate_rule(local: dict | None, repository: dict | None, human: dict) -> dict:
    if human.get('scale_id') != SCALE:
        return {'candidate': False, 'reason': 'incompatible_scale', 'kind': None}
    if not local or not repository:
        return {'candidate': False, 'reason': 'assessment_unavailable', 'kind': None}
    h, l, r = human['label'], local['decision'], repository['decision']
    if h == 'unknown':
        return {'candidate': False, 'reason': 'human_unknown_or_conflicting', 'kind': None}
    if r == 'unknown':
        return {'candidate': False, 'reason': 'repository_unresolved', 'kind': None}
    candidate = h == r and h != l
    kind = ('resolved_local_uncertainty' if l == 'unknown' else 'reversed_local_judgment') if candidate else None
    return {'candidate': candidate, 'reason': 'H_equals_R_differs_from_L' if candidate else 'pattern_not_matched', 'kind': kind}
