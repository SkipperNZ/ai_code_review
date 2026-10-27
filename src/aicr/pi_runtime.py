"""Generic Pi transport for versioned experiments; no label interpretation here."""
import json
import os
import subprocess
import time
from pathlib import Path

from .io import ROOT, atomic_text, model_secret, read_json, write_json


def execute_pi(job: dict, config: dict, directory: Path, execution_root: Path | None = None) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / 'input.json', {k: v for k, v in job.items() if k != 'snapshot'})
    allowed = {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'COMSPEC', 'PATHEXT', 'USERPROFILE'}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    secret = model_secret(config['model'])
    env.update(AICR_MODEL_KEY=secret, NO_PROXY='*')
    start = time.monotonic()
    timeout = False
    try:
        result = subprocess.run(['node', str((execution_root or ROOT) / 'worker/main.ts')],
                                input=json.dumps(job, ensure_ascii=False), encoding='utf-8', errors='replace',
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=env,
                                timeout=job['limits']['wall_seconds'] + 30)
        output, stderr = result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ''
        if isinstance(output, bytes):
            output = output.decode('utf-8', errors='replace')
        stderr, timeout = 'External wall timeout; worker process terminated.', True
    if secret:
        output, stderr = output.replace(secret, '[REDACTED]'), stderr.replace(secret, '[REDACTED]')
    atomic_text(directory / 'trace.jsonl', output)
    atomic_text(directory / 'stderr.txt', stderr)
    events = []
    for line in output.split('\n'):
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    final = next((e['data'] for e in reversed(events) if e.get('type') == 'finished'), None)
    if final:
        write_json(directory / 'shown-chunks.json', final['shown_chunks'])
        if final.get('assessment') is not None:
            write_json(directory / 'raw-candidate.json', final['assessment'])
    return {'final': final, 'events': events, 'transport_status': 'timeout' if timeout else None,
            'wall_seconds': round(time.monotonic() - start, 3)}
