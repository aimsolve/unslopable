"""The gates' state files in a document's `.gates/`: read, and changed under a lock with an atomic replace, so the hook
and several collectors running at once never lose each other's writes or leave half a file."""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


def read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@contextmanager
def locked(state: Path):
    """Hold the lock of the state folder `state` (not reentrant: never call `update` on it while holding it)."""
    state.mkdir(parents=True, exist_ok=True)
    with open(state / "lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update(path: Path, change) -> dict:
    """Read the JSON at `path`, let `change(data)` modify it in place, write it back atomically; returns the data."""
    with locked(path.parent):
        data = read(path)
        change(data)
        write(path, data)
        return data


def write(path: Path, data) -> None:
    """Write JSON atomically (the caller holds the folder's lock)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
