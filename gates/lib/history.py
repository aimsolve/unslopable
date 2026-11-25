"""Every version of every file of a document, kept for the document's timeline (viewer/).

The gate hook calls `track` on every Write/Edit/MultiEdit and Bash call, before its gates run. It keeps each file of
each affected document whose content changed since its last kept version, whoever wrote it: the Write/Edit tool, a
script run through Bash (research.py writes FACTS.md that way), or anything else (kept on the next call; only the
file a Write/Edit wrote carries its tool). A file of a document is every regular file under
its folder with no path component starting with "." (`.gates/`, `.images/` … are the plugin's own state), at most
MAX_BYTES big. Affected documents: for Write/Edit, the folder of the written path (the nearest ancestor with a
BRIEF.md); for Bash, every document a path in the command names or lies in, the one the command runs in (`cwd`), and
every document listed in the cache's `documents.json` (a file a background job wrote is caught on the next Bash
call; its time is the file's own mtime).

`<doc>/.gates/history/index.json` is `{"writes": [{n, file, time, kept, blob, deleted, tool, scripts, judges, noted},
…]}` in write order: `file` relative to the folder, `time` the file's mtime, `kept` when it was kept, `blob` the name of its copy in `blobs/` (the
sha1 of its bytes with the file's suffix, so the same content is stored once; null for a deleted file). A gated
file (PLAN.md or TEXT.md written by Write/Edit, a figure) is kept with `noted` false; the hook notes the outcome of
its gates on it (`note`: the script gate failures, or every judge it asked for or found standing) and `noted` turns
true, so a write whose gates are still running, or crashed, is told from one whose gates found nothing. A Write/Edit
of PLAN.md or TEXT.md is kept even when its content did not change, so its gates' outcome has a place.
`.gates/history/files.json` remembers each file's mtime, size and sha1, so an unchanged file is not read again.

Every document a version is kept for is listed in `<cache>/documents.json` (folder -> time of its last kept version),
where the viewer finds the documents to pick from; the cache is `$UNSLOPABLE_CACHE`, else `~/.cache/unslopable`.

Nothing here may break a write: every function swallows any error.
"""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import tempfile
import time
from pathlib import Path

import state as gstate

HISTORY = "history"
INDEX = "index.json"
FILES = "files.json"
BLOBS = "blobs"
MAX_BYTES = 20 * 1024 * 1024
MAX_FILES = 5000  # a folder with more files is no document of the plugin: it is not copied
MARKS = ("MATERIAL.md", "GATES.md", "PLAN.md", ".gates")  # next to BRIEF.md: what the plugin's stages leave
GATED_TEXT = ("PLAN.md", "TEXT.md")
_FIGURE_SUFFIXES = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif")
KEPT: dict = {}  # (folder, rel) -> write number, of this hook call: the gates note their outcome on it


def history_dir(folder: Path) -> Path:
    return folder / ".gates" / HISTORY


def cache_dir() -> Path:
    """The plugin's cache: `$UNSLOPABLE_CACHE`, else `~/.cache/unslopable`; read at call time (tests point it to a
    temp folder)."""
    return Path(os.environ.get("UNSLOPABLE_CACHE") or Path.home() / ".cache" / "unslopable")


def registry() -> Path:
    return cache_dir() / "documents.json"


def _stamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def _gated(rel: str, tool: str) -> bool:
    """Whether the hook gates this file on this call (and notes the outcome on its write)."""
    if rel in GATED_TEXT:
        return tool in ("Write", "Edit", "MultiEdit")
    return rel.startswith("figures/") and rel.lower().endswith(_FIGURE_SUFFIXES)


def is_document_file(folder: Path, p: Path) -> bool:
    try:
        rel = p.relative_to(folder)
    except ValueError:
        return False
    return not any(part.startswith(".") for part in rel.parts) and p.is_file() and not p.is_symlink()


def is_document(d: Path) -> bool:
    """A folder the plugin made a document in: a BRIEF.md and something its stages leave next to it (a folder that
    only happens to have a BRIEF.md is not one, and is never copied)."""
    try:
        return (d / "BRIEF.md").is_file() and any((d / m).exists() for m in MARKS)
    except OSError:
        return False


def document_of(path: Path) -> Path | None:
    """The document folder `path` is in, or is: the nearest ancestor (or itself) that is_document."""
    for d in [path, *path.parents][:12]:
        if is_document(d):
            return d
    return None


# ---------------------------------------------------------------- keeping

def _blob(folder: Path, data: bytes, rel: str) -> str:
    blob = hashlib.sha1(data).hexdigest() + Path(rel).suffix.lower()
    blobs = history_dir(folder) / BLOBS
    blobs.mkdir(parents=True, exist_ok=True)
    if not (blobs / blob).exists():  # a temp file of its own: two hooks may keep the same content at once
        fd, tmp = tempfile.mkstemp(dir=str(blobs), prefix=".tmp-")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, blobs / blob)
    return blob


def _scan(folder: Path, tool: str, only: Path | None = None, always: bool = False, written: str = "",
          figures: bool = True, regate: bool = False) -> dict:
    """Keep the files of `folder` that changed (only `only` when given). `written`: the file the Write/Edit call
    wrote, the only one kept with `tool` (the others changed outside it) and, with `always`, kept even unchanged.
    `figures`: whether this call gates the figures it keeps (else they are noted at once: no gate will note them).
    `regate`: `only` is being gated again (a figure whose prompt changed): kept with no tool, its gates to note.
    A version kept although its content did not change has `same` true.

    Decided and recorded under the history's lock, so hooks running at once keep each change once; the index is
    written before the manifest, so a version the index lost is found again on the next call."""
    hist = history_dir(folder)
    if only is not None:
        paths = [only] if only.exists() else []
    else:
        paths = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            paths += [Path(root) / f for f in files if not f.startswith(".")]
            if len(paths) > MAX_FILES:
                return {}  # no document of the plugin is this big: a folder it should not copy
    with gstate.locked(hist):
        manifest = gstate.read(hist / FILES)
        if not isinstance(manifest, dict):
            manifest = {}
        names = {only.relative_to(folder).as_posix()} if only is not None else set(manifest)
        entries, seen, files, now = [], set(), {}, _stamp(time.time())
        for p in paths:
            try:
                rel = p.relative_to(folder).as_posix()
                if p.is_symlink():
                    seen.add(rel)
                    if not manifest.get(rel) or manifest[rel][2] is not None:
                        files[rel] = [0, 0, None, "a link, not kept"]
                    continue
                if not is_document_file(folder, p):
                    continue
                seen.add(rel)
                st = p.stat()
                old = manifest.get(rel)
                forced = always and (not written or rel == written)
                if old and old[:2] == [st.st_mtime_ns, st.st_size] and not forced:
                    continue
                if st.st_size > MAX_BYTES:
                    files[rel] = [st.st_mtime_ns, st.st_size, None, f"over {MAX_BYTES // 2 ** 20} MB, not kept"]
                    continue
                data = p.read_bytes()
            except OSError:  # gone or unreadable since the walk: the others are still kept
                continue
            sha = hashlib.sha1(data).hexdigest()
            files[rel] = [st.st_mtime_ns, st.st_size, sha]
            if old and old[2] == sha and not forced:
                continue
            by = (tool or None) if not written or rel == written else None
            gated = regate or bool(by) and _gated(rel, by) and (rel in GATED_TEXT or figures)
            entries.append({"file": rel, "time": _stamp(st.st_mtime), "kept": now, "blob": _blob(folder, data, rel),
                            "deleted": False, "tool": None if regate else by, "scripts": [], "judges": [],
                            "noted": not gated, "gated": gated, "same": bool(old) and old[2] == sha})
        for rel in names - seen:  # gone since it was kept
            if rel in manifest and not os.path.lexists(folder / rel):
                files[rel] = None
                if manifest[rel][2] is not None:
                    entries.append({"file": rel, "time": now, "kept": now, "blob": None, "deleted": True,
                                    "tool": (tool or None) if not written else None, "scripts": [], "judges": [],
                                    "noted": True, "gated": False})
        if not entries and not files:
            return {}
        ns: list[int] = []
        if entries:
            index = gstate.read(hist / INDEX)
            if not isinstance(index, dict) or not isinstance(index.get("writes"), list):
                index = {"writes": []}
            writes = index["writes"]
            for e in entries:
                e["n"] = len(writes) + 1
                writes.append(e)
                ns.append(e["n"])
            gstate.write(hist / INDEX, index)
        for rel, v in files.items():
            if v is None:
                manifest.pop(rel, None)
            else:
                manifest[rel] = v
        gstate.write(hist / FILES, manifest)
    if entries:
        register(folder, max(e["time"] for e in entries))
    return {(str(folder), e["file"]): n for e, n in zip(entries, ns)}


def skipped(folder: Path) -> dict[str, str]:
    """The files of the document not kept, and why (a link, too big)."""
    m = gstate.read(history_dir(folder) / FILES)
    return {rel: v[3] for rel, v in m.items() if isinstance(v, list) and len(v) > 3 and v[2] is None} \
        if isinstance(m, dict) else {}


_ABS_PATH = re.compile(r"(?<![\w.])(?:~|/)[^\s'\"(),;|&<>=`]+")


def _command_folders(command: str, cwd: str) -> list[Path]:
    """Documents a Bash command names a path in (or a path inside)."""
    try:
        toks = shlex.split(command)
    except ValueError:
        toks = command.split()
    out: list[Path] = []
    toks += _ABS_PATH.findall(command)  # a path inside a quoted argument (python3 -c "open('/…/FACTS.md')")
    for t in toks:
        t = t.split("=", 1)[-1].strip("\"'();|&<>")
        if "/" not in t and t not in (".", ".."):
            continue
        t = os.path.expandvars(os.path.expanduser(t))
        p = Path(t) if os.path.isabs(t) else Path(cwd or ".") / t
        d = document_of(Path(os.path.realpath(p)))
        if d and d not in out:
            out.append(d)
    return out


def track(data: dict) -> dict:
    """Keep what this tool call changed in every document it may have touched; returns {(folder, rel): n} and sets
    KEPT, where the gates find the write to note their outcome on."""
    KEPT.clear()
    try:
        tool = data.get("tool_name") or ""
        ti = data.get("tool_input") or {}
        if tool in ("Write", "Edit", "MultiEdit") and ti.get("file_path"):
            p = Path(os.path.realpath(os.path.expanduser(ti["file_path"])))
            folder = document_of(p.parent)
            if folder is None and p.name == "BRIEF.md" and tool == "Write" and not history_dir(p.parent).exists():
                folder = p.parent  # a Write of a BRIEF.md where no document is yet starts one (the brief stage)
            if folder and is_document_file(folder, p):
                rel = p.relative_to(folder).as_posix()
                KEPT.update(_scan(folder, tool, always=rel in GATED_TEXT, written=rel))
        elif tool == "Bash":
            cwd, command = data.get("cwd") or "", ti.get("command") or ""
            named = _command_folders(command, cwd)
            folders = list(named)
            here = document_of(Path(os.path.realpath(cwd))) if cwd else None
            for f in ([here] if here else []) + [Path(f) for f in gstate.read(registry())]:
                if f not in folders and (f / "BRIEF.md").is_file():
                    folders.append(f)
            for folder in folders:
                try:  # the figure gates run on a Bash call only for a document it names with "figures" in it
                    KEPT.update(_scan(folder, tool, figures="figures" in command and folder in named))
                except Exception:  # noqa: BLE001 — one document's trouble does not stop the others
                    pass
    except Exception:  # noqa: BLE001 — the write and its gates go on without the history
        pass
    return dict(KEPT)


def entry(folder: Path, rel: str) -> int | None:
    """The write this hook call kept for `rel`, or a new one (a figure gated again with unchanged content)."""
    n = KEPT.get((os.path.realpath(folder), rel))
    if n:
        return n
    try:
        return _scan(folder, "", only=folder / rel, always=True, regate=True).get((str(folder), rel))
    except Exception:  # noqa: BLE001
        return None


def note(folder: Path, n: int | None, scripts: list[str], judges: list[str]) -> None:
    """Note what the gates said on write `n`."""
    if not n:
        return

    def change(d: dict) -> None:
        for w in d.get("writes", []):
            if isinstance(w, dict) and w.get("n") == n:
                w["scripts"] = list(scripts)
                w["judges"] = list(dict.fromkeys(judges))
                w["noted"] = True

    try:
        gstate.update(history_dir(folder) / INDEX, change)
    except Exception:  # noqa: BLE001
        pass


def register(folder: Path, when: str) -> None:
    """List the folder among the documents, and drop the ones that are no document folder any more."""
    def change(d: dict) -> None:
        for f in [f for f in d if not (Path(f) / "BRIEF.md").is_file()]:
            del d[f]
        d[str(folder)] = max(when, str(d.get(str(folder), "")))

    try:
        gstate.update(registry(), change)
    except Exception:  # noqa: BLE001
        pass


def writes(folder: Path) -> list[dict]:
    """The kept writes, oldest first; [] when there are none or the index is not what this module writes."""
    data = gstate.read(history_dir(folder) / INDEX)
    w = data.get("writes") if isinstance(data, dict) else None
    return [x for x in w if isinstance(x, dict)] if isinstance(w, list) else []


def blob_path(folder: Path, blob: str) -> Path:
    return history_dir(folder) / BLOBS / blob

