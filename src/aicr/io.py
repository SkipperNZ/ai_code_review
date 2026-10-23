from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[2]


@contextmanager
def queue_lock(path: Path):
    """OS advisory lock: automatically released on crash, no stale PID heuristic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0'); handle.flush()
        handle.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def digest(value: Any) -> str:
    data = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path: str | Path, value: Any) -> None:
    atomic_text(Path(path), json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            f.write(value)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def write_jsonl(path: str | Path, values: list[dict]) -> None:
    atomic_text(Path(path), ''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))


def safe_repo_path(path: str) -> bool:
    return bool(path) and not path.startswith('/') and '\\' not in path and ':' not in path and all(p not in ('', '.', '..') for p in path.split('/'))


def model_secret(config: dict) -> str:
    secret = os.environ.get(config.get('api_key_env', 'MB_JUDGE_API_KEY'))
    if secret:
        return secret.strip()
    path = config.get('api_key_file')
    return Path(path).read_text(encoding='utf-8').strip() if path and Path(path).is_file() else ''
