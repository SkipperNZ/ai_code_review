"""Offline blinded human packets and explicit reference scoring; never generate human labels."""
import copy
import re
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from .ambiguity_contracts import outside_local
from .contracts import chunk
from .io import ROOT, digest, now, read_json, read_jsonl, safe_repo_path, write_json, write_jsonl

AUDIT_PROTOCOL = 'ambiguity-human-audit-1.0.1'
ANNOTATION_SCHEMA = 'schemas/ambiguity-audit-annotation.schema.json'


def _unchanged_json(path: Path, value):
    if path.exists():
        if read_json(path) != value:
            raise ValueError('Existing audit artifact differs: ' + str(path))
    else:
        write_json(path, value)


def export_audit(directories: list[Path], output: Path) -> dict:
    """Export every available case, including non-candidates, with a separate private index."""
    if not directories or len({p.resolve() for p in directories}) != len(directories):
        raise ValueError('Unique run directories required')
    records, source_runs = [], []
    seen = set()
    for directory in sorted(directories, key=lambda p: str(p.resolve())):
        manifest = read_json(directory / 'manifest.json')
        identity = manifest['identity']
        if not identity['protocol'].startswith('ambiguity-1.') or digest(identity)[:12] != manifest['id'].rsplit('-', 1)[1]:
            raise ValueError('Invalid ambiguity run identity')
        hashes = read_json(directory / 'case-hashes.json')
        samples = {s['id']: s for s in read_jsonl(Path(manifest['data_root']) / 'normalized/samples.jsonl')}
        source_runs.append({'run_id': manifest['id'], 'identity_hash': digest(identity),
                            'selected': identity['selected'], 'case_hashes': hashes})
        for sid in identity['selected']:
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', sid):
                raise ValueError('Unsafe sample identity')
            path = directory / sid / 'case.json'
            if not path.exists():
                continue
            row = read_json(path)
            if digest(row) != hashes.get(sid) or row['run_id'] != manifest['id'] or row['sample_id'] != sid:
                raise ValueError('Case changed before audit export')
            sample = samples[sid]
            if digest(sample) != identity['sample_hashes'][sid]:
                raise ValueError('Sample changed before audit export')
            if not row.get('local_chunks') or not row.get('core_claim'):
                continue
            snapshot_id = sample['snapshot_id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', snapshot_id):
                raise ValueError('Unsafe snapshot identity')
            snapshot_path = Path(manifest['data_root']) / 'snapshots' / (snapshot_id + '.json')
            if digest(snapshot_path.read_text(encoding='utf-8')) != identity['snapshot_hashes'][snapshot_id]:
                raise ValueError('Snapshot changed before audit export')
            snapshot = read_json(snapshot_path)
            if snapshot['id'] != snapshot_id or snapshot['commit_sha'] != sample['original_commit_id']:
                raise ValueError('Snapshot identity changed')
            for local in row['local_chunks']:
                if local != chunk(snapshot, local['path'], local['start_line'], local['end_line']):
                    raise ValueError('Noncanonical local audit context')
            if any(not safe_repo_path(p) or digest(f['text']) != f['text_sha256'] for p, f in snapshot['files'].items()):
                raise ValueError('Invalid snapshot contents')
            # Repeating the same sample across detector versions is not another independent example.
            key = digest([sample['comment_text'], row['core_claim'], row['local_chunks'], digest(snapshot)])
            if key in seen:
                raise ValueError('Duplicate audit input across runs; select one detector version per example')
            seen.add(key)
            records.append((manifest, row, sample, snapshot, key))
    if not records:
        raise ValueError('No exportable cases; an identified claim and canonical local snippet are required')
    annotation_schema = read_json(ROOT / ANNOTATION_SCHEMA)
    predictions = [{'input_key': key, 'run_id': manifest['id'], 'sample_id': sample['id'],
                    'case_hash': digest(row), 'snapshot_hash': digest(snapshot),
                    'synthetic': sample.get('provider') == 'synthetic_fixture',
                    'selection_annotator_key': row['human'].get('annotator_key'), 'candidate': row['candidate'],
                    'model_confirmed': row['conclusion'] == 'model_supported_context_dependency',
                    'detector_status': row['status']} for manifest, row, sample, snapshot, key in records]
    audit_identity = {'protocol': AUDIT_PROTOCOL, 'source_runs': source_runs, 'input_keys': sorted(seen),
                      'prediction_snapshot': sorted(predictions, key=lambda p: p['input_key']),
                      'annotation_schema_hash': digest(annotation_schema)}
    audit_id = 'audit-' + digest(audit_identity)[:24]
    _unchanged_json(output / 'annotation.schema.json', annotation_schema)
    local_packets, repo_packets, index = [], [], []
    for manifest, row, sample, snapshot, key in records:
        packet_id = digest([audit_id, key])[:24]
        base = {'audit_id': audit_id, 'packet_id': packet_id, 'scale_id': row['scale_id'],
                'comment': sample['comment_text'], 'core_claim': row['core_claim'], 'chunks': row['local_chunks']}
        local_packets.append({**copy.deepcopy(base), 'condition': 'local'})
        snapshot_name = digest(snapshot) + '.json'
        repo_packets.append({**copy.deepcopy(base), 'condition': 'repository', 'snapshot_partial': snapshot['partial'],
                             'snapshot_ref': 'snapshots/' + snapshot_name,
                             'inventory': [{'path': p, 'lines': len(f['text'].splitlines()), 'text_sha256': f['text_sha256']}
                                           for p, f in sorted(snapshot['files'].items())]})
        _unchanged_json(output / 'repository' / 'snapshots' / snapshot_name, snapshot)
        index.append({'packet_id': packet_id, 'run_id': manifest['id'], 'sample_id': sample['id'],
                      'case_hash': digest(row), 'snapshot_hash': digest(snapshot),
                      'synthetic': sample.get('provider') == 'synthetic_fixture',
                      'selection_annotator_key': row['human'].get('annotator_key'),
                      'candidate': row['candidate'],
                      'model_confirmed': row['conclusion'] == 'model_supported_context_dependency',
                      'detector_status': row['status']})
    for folder, packets in [('local', local_packets), ('repository', repo_packets)]:
        packets.sort(key=lambda p: digest([audit_id, p['packet_id']]))
        path = output / folder / 'packets.jsonl'
        if path.exists() and read_jsonl(path) != packets:
            raise ValueError('Existing audit packets differ')
        if not path.exists():
            write_jsonl(path, packets)
        _unchanged_json(output / folder / 'manifest.json', {'audit_id': audit_id, 'protocol': AUDIT_PROTOCOL,
                         'condition': folder, 'packets_hash': digest(packets)})
    index.sort(key=lambda row: row['packet_id'])
    _unchanged_json(output / 'private/index.json', index)
    result = {'audit_id': audit_id, 'identity': audit_identity, 'packets': len(records),
              'planned_source_cases': sum(len(r['selected']) for r in source_runs),
              'local_packets_hash': digest(local_packets), 'repository_packets_hash': digest(repo_packets),
              'private_index_hash': digest(index),
              'annotation_schema_hash': digest(annotation_schema),
              'instructions': 'Distribute local/ and repository/ separately. Keep private/ and manifest.json away from reviewers. '
                              'Record local judgments before opening repository context. Do not disclose model results or H signals.'}
    _unchanged_json(output / 'manifest.json', result)
    return {'audit_id': audit_id, 'directory': str(output.resolve()), 'packets': len(records),
            'model_requests': 0, 'human_annotations_created': 0}


def _read_audit(directory: Path):
    manifest = read_json(directory / 'manifest.json')
    if manifest['audit_id'] != 'audit-' + digest(manifest['identity'])[:24]:
        raise ValueError('Audit identity changed')
    local = read_jsonl(directory / 'local/packets.jsonl')
    repo = read_jsonl(directory / 'repository/packets.jsonl')
    index = read_json(directory / 'private/index.json')
    for content, key in [(local, 'local_packets_hash'), (repo, 'repository_packets_hash'), (index, 'private_index_hash')]:
        if digest(content) != manifest[key]:
            raise ValueError('Audit artifact changed: ' + key)
    if digest(read_json(directory / 'annotation.schema.json')) != manifest['annotation_schema_hash']:
        raise ValueError('Audit annotation schema changed')
    if manifest['annotation_schema_hash'] != manifest['identity']['annotation_schema_hash']:
        raise ValueError('Audit schema identity changed')
    ids = [p['packet_id'] for p in local]
    if len(set(ids)) != len(ids) or set(ids) != {p['packet_id'] for p in repo} or set(ids) != {p['packet_id'] for p in index}:
        raise ValueError('Audit packet identities differ')
    if any(p['audit_id'] != manifest['audit_id'] for p in local + repo):
        raise ValueError('Packet audit identity changed')
    expected = [{**{k: v for k, v in p.items() if k != 'input_key'},
                 'packet_id': digest([manifest['audit_id'], p['input_key']])[:24]}
                for p in manifest['identity']['prediction_snapshot']]
    if sorted(index, key=lambda p: p['packet_id']) != sorted(expected, key=lambda p: p['packet_id']):
        raise ValueError('Private predictions differ from frozen audit identity')
    for p in local:
        key = digest([p['comment'], p['core_claim'], p['chunks'], next(i['snapshot_hash'] for i in index if i['packet_id'] == p['packet_id'])])
        if key not in manifest['identity']['input_keys'] or digest([manifest['audit_id'], key])[:24] != p['packet_id']:
            raise ValueError('Audit input differs from frozen identity')
    by_id = {p['packet_id']: p for p in local}
    for p in repo:
        if any(p[k] != by_id[p['packet_id']][k] for k in ['comment', 'core_claim', 'chunks', 'scale_id']):
            raise ValueError('Local and repository audit inputs differ')
    return manifest, {p['packet_id']: p for p in local}, {p['packet_id']: p for p in repo}, {p['packet_id']: p for p in index}


def _repository_snapshot(directory: Path, packet: dict) -> dict:
    if not re.fullmatch(r'snapshots/[0-9a-f]{64}\.json', packet['snapshot_ref']):
        raise ValueError('Unsafe audit snapshot reference')
    snapshot = read_json(directory / packet['snapshot_ref'])
    if digest(snapshot) != Path(packet['snapshot_ref']).stem:
        raise ValueError('Snapshot changed')
    inventory = [{'path': p, 'lines': len(f['text'].splitlines()), 'text_sha256': f['text_sha256']}
                 for p, f in sorted(snapshot['files'].items())]
    if packet['snapshot_partial'] != snapshot['partial'] or packet['inventory'] != inventory:
        raise ValueError('Repository scope metadata differs from snapshot')
    return snapshot


def read_audit_chunk(directory: Path, packet_id: str, path: str, start: int, end: int) -> dict:
    # Reviewers receive only repository/, with no private prediction index or H information.
    if (directory / 'packets.jsonl').exists():
        public = read_json(directory / 'manifest.json')
        packets = read_jsonl(directory / 'packets.jsonl')
        if public['condition'] != 'repository' or digest(packets) != public['packets_hash']:
            raise ValueError('Not an unchanged repository audit packet directory')
        matches = [p for p in packets if p['packet_id'] == packet_id and p['audit_id'] == public['audit_id']]
        if len(matches) != 1:
            raise ValueError('Packet identity is missing or ambiguous')
        snapshot = _repository_snapshot(directory, matches[0])
    else:
        _, _, repo, index = _read_audit(directory)
        snapshot = _repository_snapshot(directory / 'repository', repo[packet_id])
        if digest(snapshot) != index[packet_id]['snapshot_hash']:
            raise ValueError('Snapshot differs from audit identity')
    if not safe_repo_path(path):
        raise ValueError('Unsafe repository path')
    return chunk(snapshot, path, start, end)


def _annotations(path, phase, audit, packets, schema, *, allow_synthetic):
    result = {}
    validator = Draft202012Validator(schema)
    for row in read_jsonl(path):
        errors = list(validator.iter_errors(row))
        if errors:
            raise ValueError('Invalid audit annotation: ' + errors[0].message)
        pid = row['packet_id']
        if row['audit_id'] != audit['audit_id'] or row['phase'] != phase or pid not in packets:
            raise ValueError('Annotation does not belong to this audit/phase')
        if pid in result:
            raise ValueError('Duplicate annotation; explicit adjudication required')
        if not row['annotator_key'].strip() or not row['rationale'].strip():
            raise ValueError('Nonempty annotator and rationale required')
        if row['source_kind'] != 'human_manual' and not allow_synthetic:
            raise ValueError('Synthetic audit fixtures require the explicit allow-synthetic-test option')
        if phase == 'local' and ((row['decision'] == 'unknown') != (row['evaluability'] == 'insufficient')):
            raise ValueError('Local unknown requires insufficient evaluability; known decisions require sufficient')
        result[pid] = row
    return result


def _rates(rows, prediction):
    counts = Counter(('tp' if r[prediction] else 'fn') if r['reference'] else ('fp' if r[prediction] else 'tn') for r in rows)
    tp, fp, fn, tn = (counts[k] for k in ('tp', 'fp', 'fn', 'tn'))
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
            'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'scope': 'only independently audited exported cases; not population performance'}


def score_audit(directory: Path, local_file: Path, repository_file: Path, *, allow_synthetic=False) -> dict:
    audit, local, repo, index = _read_audit(directory)
    schema = read_json(directory / 'annotation.schema.json')
    lrows = _annotations(local_file, 'local', audit, local, schema, allow_synthetic=allow_synthetic)
    rrows = _annotations(repository_file, 'repository', audit, repo, schema, allow_synthetic=allow_synthetic)
    rows = []
    for pid, prediction in index.items():
        l, r = lrows.get(pid), rrows.get(pid)
        row = {'packet_id': pid, 'candidate': prediction['candidate'], 'model_confirmed': prediction['model_confirmed'],
               'reference': None, 'reference_source': None, 'exclusion': None, 'human_decision_changed': None}
        if l is None or r is None:
            row['exclusion'] = 'incomplete_pair'
        else:
            row['human_decision_changed'] = l['decision'] != r['decision']
            if prediction['selection_annotator_key'] in {l['annotator_key'], r['annotator_key']}:
                row['exclusion'] = 'selection_annotator_reused'
            if l['source_kind'] != r['source_kind']:
                raise ValueError('Mixed human and synthetic audit pair')
            evidence = []
            for link in r['evidence']:
                c = read_audit_chunk(directory, pid, link['path'], link['start_line'], link['end_line'])
                if c['excerpt'] != link['excerpt']:
                    raise ValueError('Human evidence quote differs from canonical snapshot')
                evidence.append(c)
            if r['context_dependency'] in {'required', 'not_required'}:
                if r['decision'] == 'unknown' or not evidence:
                    raise ValueError('Resolved context reference requires a known repository decision and canonical evidence')
                if r['context_dependency'] == 'required' and (not (r['missing_premise'] or '').strip() or
                        not any(outside_local(c, local[pid]['chunks']) for c in evidence)):
                    raise ValueError('Context-required reference needs a concrete missing premise and outside-local evidence')
                row['reference'] = r['context_dependency'] == 'required'
                row['reference_source'] = ('synthetic_test_fixture' if prediction['synthetic'] or r['source_kind'] != 'human_manual'
                                           else 'human_context_audit')
            else:
                if r['decision'] != 'unknown' or not (r['missing_premise'] or '').strip():
                    raise ValueError('External/unresolved context requires unknown and a concrete missing premise')
                row['exclusion'] = row['exclusion'] or r['context_dependency']
        rows.append(row)
    eligible = [r for r in rows if r['reference'] is not None and not r['exclusion']]
    human = [r for r in eligible if r['reference_source'] == 'human_context_audit']
    synthetic = [r for r in eligible if r['reference_source'] == 'synthetic_test_fixture']
    human_rates = {p: _rates(human, p) for p in ['candidate', 'model_confirmed']}
    # A candidates-only or incomplete audit cannot measure detector recall on the export.
    if len(human) != len(rows):
        for value in human_rates.values():
            value['recall'] = None
    identity = {'audit_id': audit['audit_id'], 'local_annotations_hash': digest(lrows), 'repository_annotations_hash': digest(rrows)}
    result = {'protocol': AUDIT_PROTOCOL, **identity, 'evaluated_at': now(), 'packets': len(rows),
              'paired': sum(r['human_decision_changed'] is not None for r in rows),
              'eligible_human_references': len(human), 'synthetic_test_references': len(synthetic),
              'excluded': dict(Counter(r['exclusion'] for r in rows if r['exclusion'])),
              'audit_fully_resolved_by_humans': len(human) == len(rows),
              'human_reference_coverage': len(human) / len(rows), 'population_performance_estimate': False,
              'human_context_audit': human_rates,
              'synthetic_diagnostics': {p: _rates(synthetic, p) for p in ['candidate', 'model_confirmed']},
              'source_labels_modified': False, 'model_requests': 0, 'classifier_trained': False}
    output = directory / 'evaluations' / digest(identity)[:24]
    _unchanged_json(output / 'local-annotations.json', lrows)
    _unchanged_json(output / 'repository-annotations.json', rrows)
    write_json(output / 'metrics.json', result)
    write_jsonl(output / 'cases.jsonl', rows)
    return {**result, 'directory': str(output.resolve())}
