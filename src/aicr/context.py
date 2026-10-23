from __future__ import annotations

from .contracts import chunk


def build_context(sample: dict, snapshot: dict, mode: str, rationale_mode: str = 'present') -> dict:
    """Allowlist construction: no reactions, labels, reply text or raw bot metadata."""
    lines = snapshot['files'][sample['path']]['text'].splitlines()
    anchor_start = sample.get('original_start_line') or sample['original_line']
    anchor_end = sample['original_line']
    start, end = max(1, anchor_start - 12), min(len(lines), anchor_end + 12)
    if end - start > 180:
        end = start + 180
    chunks = [chunk(snapshot, sample['path'], start, end)]
    if mode == 'static':
        start, end = max(1, anchor_start - 70), min(len(lines), anchor_end + 70)
        chunks = [chunk(snapshot, sample['path'], start, end)]
    rationale = sample.get('generator_rationale') if rationale_mode == 'present' else None
    return {'input_contract': 'blinded-context-0.2',
            'sample_id': sample['id'], 'comment': sample['comment_text'], 'generator_rationale': rationale,
            'comment_created_at': sample.get('created_at'),
            'body_history_status': sample.get('body_history_status', 'unknown'),
            'rationale_status': 'present' if rationale else ('masked' if sample.get('generator_rationale') else 'unavailable'),
            'snapshot_id': snapshot['id'], 'snapshot_partial': snapshot['partial'], 'anchor_path': sample['path'],
            'chunks': chunks, 'context_mode': mode}
