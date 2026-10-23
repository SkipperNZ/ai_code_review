from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
import re
import shutil
from pathlib import Path

import requests

from .context import build_context
from .contracts import validate_assessment
from .materialize import compile_response
from .io import ROOT, digest, model_secret, now, read_json, write_json, atomic_text, queue_lock


def doctor(config: dict) -> dict:
    session = requests.Session()
    session.trust_env = False
    key = model_secret(config['model'])
    if key:
        session.headers['Authorization'] = 'Bearer ' + key
    result = {'checked_at': now(), 'expected_model': config['model']['id'], 'runtime': 'pi-sdk',
              'pi_version': read_json(ROOT / 'node_modules/@earendil-works/pi-coding-agent/package.json')['version'],
              'weight_fingerprint': None, 'weight_fingerprint_status': 'not_exposed'}
    try:
        response = session.get(config['model']['base_url'].rstrip('/') + '/models', timeout=(5, 15))
        result['http_status'] = response.status_code
        response.raise_for_status()
        models = response.json().get('data', [])
        result['model_ids'] = [m['id'] for m in models]
        result['ok'] = config['model']['id'] in result['model_ids']
        result['server_model_metadata'] = next((m for m in models if m['id'] == config['model']['id']), None)
        result['deployment_fingerprint'] = digest(result['server_model_metadata'])
    except requests.RequestException as exc:
        result.update(ok=False, error=type(exc).__name__)
    return result


def source_files() -> list[Path]:
    return sorted([*ROOT.joinpath('src').rglob('*.py'), *ROOT.joinpath('worker').glob('*.ts'),
                   *ROOT.joinpath('schemas').glob('*.json'), *ROOT.joinpath('prompts').glob('*.txt'), ROOT / 'package-lock.json'])


def code_hash() -> str:
    return digest({str(p.relative_to(ROOT)): digest(p.read_text(encoding='utf-8')) for p in source_files()})


def run_one(sample: dict, snapshot: dict, config: dict, mode: str, run_id: str, directory: Path, rationale_mode='present', execution_root: Path | None = None) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    source_root = execution_root or ROOT
    contract = config.get('response_contract', 'compact-0.2.1')
    response_files = {
        'compact-0.2.1': ('judge.txt', 'judge-response.schema.json'),
        'compact-0.3.0': ('judge-whole-chunk.txt', 'judge-response-whole-chunk.schema.json'),
    }
    if contract not in response_files:
        raise ValueError('Unsupported response contract')
    prompt_name, schema_name = response_files[contract]
    context = build_context(sample, snapshot, mode, rationale_mode)
    job = {'sample_id': sample['id'], 'run_id': run_id, 'mode': mode, 'context': context, 'snapshot': snapshot,
           'diff': {'path': sample['path'], 'hunk': sample.get('diff_hunk', ''), 'side': sample.get('side', 'RIGHT')},
           'model': {k: config['model'][k] for k in ('base_url', 'id', 'context_window', 'max_output_tokens', 'chat_template_kwargs') if k in config['model']},
           'limits': dict(config['limits']), 'system_prompt': (source_root / 'prompts' / prompt_name).read_text(encoding='utf-8'),
           'schema': read_json(source_root / 'schemas' / schema_name), 'runtime_dir': str((directory / 'runtime').resolve())}
    if mode != 'agent':
        job['limits']['max_turns'] = 2
        job['limits']['max_tool_calls'] = 0
        job['limits']['wall_seconds'] = min(180, job['limits']['wall_seconds'])
    # Only the blinded job is accessible to the worker. The model can access code solely through in-memory tools.
    write_json(directory / 'input.json', {k: v for k, v in job.items() if k != 'snapshot'})
    env = {k: v for k, v in os.environ.items() if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'USERPROFILE'}}
    env['AICR_MODEL_KEY'] = model_secret(config['model'])
    env['NO_PROXY'] = '*'
    start = time.monotonic()
    result = {'id': directory.name, 'run_id': run_id, 'sample_id': sample['id'], 'mode': mode, 'started_at': now(),
              'strict_eligible': sample['strict_eligible'], 'status': 'endpoint_error', 'assessment_ref': None}
    try:
        completed = subprocess.run(['node', str(source_root / 'worker/main.ts')], input=json.dumps(job, ensure_ascii=False),
                                   encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=ROOT, env=env, timeout=job['limits']['wall_seconds'] + 30)
        output, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        output = (exc.stdout or b'').decode('utf-8', errors='replace') if isinstance(exc.stdout, bytes) else (exc.stdout or '')
        stderr = 'External wall timeout. Worker process killed.'
        result['status'] = 'timeout'
    # Defense in depth: never retain a credential echoed by an unexpected provider exception.
    secret = env['AICR_MODEL_KEY']
    if secret:
        output = output.replace(secret, '[REDACTED]')
        stderr = stderr.replace(secret, '[REDACTED]')
    atomic_text(directory / 'trace.jsonl', output)
    atomic_text(directory / 'stderr.txt', stderr)
    events = []
    for line in output.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    final = next((e['data'] for e in reversed(events) if e.get('type') == 'finished'), None)
    if final:
        result.update({k: final[k] for k in ('status', 'format_repair', 'requests', 'tool_calls', 'generated_tokens', 'usage', 'error')})
        write_json(directory / 'shown-chunks.json', final['shown_chunks'])
        if final.get('assessment') is not None:
            raw = final['assessment']
            write_json(directory / 'raw-candidate.json', raw)
            candidate, validation = compile_response(raw, job['schema'], snapshot, final['shown_chunks'], sample['id'], run_id, mode)
            result['response_contract'] = config.get('response_contract', 'compact-0.2.1')
            result['evidence_materialization'] = 'canonical_text_from_model_selected_shown_anchors'
            if candidate is not None:
                write_json(directory / 'candidate.json', candidate)
                validation = {**validate_assessment(candidate, snapshot, final['shown_chunks'], sample_id=sample['id'], run_id=run_id, mode=mode,
                              schema_override=read_json(source_root / 'schemas/assessment.schema.json')), 'raw_schema_valid': True}
            result['validation'] = validation
            if not validation.get('raw_schema_valid', False):
                result['status'] = 'json_invalid'
            elif not validation['evidence_valid']:
                result['status'] = 'evidence_invalid'
            elif not validation['semantic_valid']:
                result['status'] = 'semantic_invalid'
            else:
                result['status'] = 'ok'
                write_json(directory / 'assessment.json', candidate)
                result['assessment_ref'] = str((directory / 'assessment.json').resolve())
    result.update(finished_at=now(), wall_seconds=round(time.monotonic() - start, 3), trace_ref=str((directory / 'trace.jsonl').resolve()))
    write_json(directory / 'result.json', result)
    return result


def select_samples(samples: list[dict], limit: int, strict: bool = False) -> list[dict]:
    """Deterministic repo round-robin; selection precedes teacher and signal inspection."""
    groups: dict[str, list] = {}
    seen = set()
    for s in sorted(samples, key=lambda s: (not s['strict_eligible'], s['created_at'], s['id'])):
        if s['snapshot_id'] and (not strict or s['strict_eligible']):
            duplicate = digest([s['repo_id'], s['path'], ' '.join(s['comment_text'].split())])
            if duplicate in seen:
                continue
            seen.add(duplicate)
            groups.setdefault(s['repo_id'], []).append(s)
    selected = []
    while len(selected) < limit and any(groups.values()):
        for repo in sorted(groups):
            if groups[repo] and len(selected) < limit:
                selected.append(groups[repo].pop(0))
    return selected


def run_batch(data: Path, runs: Path, samples: list[dict], config: dict, name: str, modes: list[str], limit: int, strict=False, retry_failed=False):
    with queue_lock(runs / '.queue.lock'):
        return _run_batch(data, runs, samples, config, name, modes, limit, strict, retry_failed)


def _run_batch(data: Path, runs: Path, samples: list[dict], config: dict, name: str, modes: list[str], limit: int, strict=False, retry_failed=False):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name) or limit < 1:
        raise ValueError('Run name must be 1-64 ASCII letters/digits/_/- and limit must be positive')
    if len(set(modes)) != len(modes):
        raise ValueError('Modes must be unique')
    health = doctor(config)
    if not health['ok']:
        raise RuntimeError('Model preflight failed: ' + json.dumps(health))
    selected = select_samples(samples, limit, strict)
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', s['id']) for s in selected):
        raise ValueError('Unsafe sample ID')
    snapshot_hashes = {s['snapshot_id']: digest((data / 'snapshots' / (s['snapshot_id'] + '.json')).read_text(encoding='utf-8')) for s in selected}
    manifest = {'config': config, 'code_hash': code_hash(), 'deployment': health['deployment_fingerprint'],
                'selected': [s['id'] for s in selected], 'sample_hashes': {s['id']: digest(s) for s in selected},
                'snapshot_hashes': snapshot_hashes, 'modes': modes, 'strict_only': strict}
    run_id = name + '-' + digest(manifest)[:12]
    directory = runs / run_id
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / 'manifest.json', {**manifest, 'id': run_id, 'doctor': health})
    execution_root = (directory / 'execution').resolve()
    for source in source_files():
        target = execution_root / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
        elif digest(target.read_text(encoding='utf-8')) != digest(source.read_text(encoding='utf-8')):
            raise RuntimeError('Frozen execution bundle was modified')
    db = sqlite3.connect(runs / 'queue.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (key TEXT PRIMARY KEY, status TEXT NOT NULL, attempt INTEGER NOT NULL, result_path TEXT)')
    count = 0
    for sample in selected:
        snapshot_path = data / 'snapshots' / (sample['snapshot_id'] + '.json')
        if digest(snapshot_path.read_text(encoding='utf-8')) != manifest['snapshot_hashes'][sample['snapshot_id']]:
            raise RuntimeError('Snapshot changed during run')
        snapshot = read_json(snapshot_path)
        for mode in modes:
            key = digest([run_id, sample['id'], mode])
            row = db.execute('SELECT status, attempt FROM jobs WHERE key=?', (key,)).fetchone()
            if row and row[0] == 'running':
                # The OS queue lock proves no other batch owns this queue. A crash can
                # happen either before result.json or between its atomic write and DB commit.
                previous_result = directory / sample['id'] / mode / f'attempt-{row[1]}' / 'result.json'
                if previous_result.exists():
                    saved = read_json(previous_result)
                    identity = (saved.get('run_id'), saved.get('sample_id'), saved.get('mode'))
                    terminal = {'ok', 'json_invalid', 'semantic_invalid', 'evidence_invalid', 'budget_exhausted', 'timeout', 'endpoint_error'}
                    if identity != (run_id, sample['id'], mode) or saved.get('status') not in terminal:
                        raise RuntimeError('Interrupted queue result has invalid identity or status')
                    row = (saved['status'], row[1])
                    db.execute('UPDATE jobs SET status=? WHERE key=?', (row[0], key)); db.commit()
                    print(json.dumps({'event': 'recovered_completed_result', 'sample_id': sample['id'], 'mode': mode, 'status': row[0]}), flush=True)
                else:
                    print(json.dumps({'event': 'retry_interrupted_attempt', 'sample_id': sample['id'], 'mode': mode, 'previous_attempt': row[1]}), flush=True)
            if row and row[0] != 'running' and (row[0] == 'ok' or not retry_failed):
                print(json.dumps({'event': 'skip', 'sample_id': sample['id'], 'mode': mode, 'status': row[0]}), flush=True)
                continue
            attempt = row[1] + 1 if row else 1
            attempt_dir = directory / sample['id'] / mode / f'attempt-{attempt}'
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?)', (key, 'running', attempt, str(attempt_dir / 'result.json')))
            db.commit()
            result = run_one(sample, snapshot, config, mode, run_id, attempt_dir, execution_root=execution_root)
            db.execute('UPDATE jobs SET status=? WHERE key=?', (result['status'], key))
            db.commit()
            count += 1
            print(json.dumps({'event': 'result', 'completed': count, 'sample_id': sample['id'], 'mode': mode,
                              'status': result['status'], 'seconds': result['wall_seconds']}), flush=True)
    db.close()
    return {'run_id': run_id, 'directory': str(directory), 'selected': len(selected), 'completed_now': count}
