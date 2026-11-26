"""Why a kept version of a document's file changed, for the viewer: read from the Claude Code session transcripts.

The gate hook's answer to each write (its PostToolUse additional context: which script gates failed) and the model's
own words between its writes are recorded nowhere in the document; Claude Code records both in the session's
transcript, `<config>/projects/<slug>/<session>.jsonl` (config: `$CLAUDE_CONFIG_DIR` or `~/.claude`; slug: the
session's working folder with every character but A-Z a-z 0-9 turned into `-`). A document's sessions are those of
its own folder and of the folders above it (a session started higher up writes into it too).

`reasons(folder, writes)` gives, for each kept version (history.writes), the write call that made it — matched by the
content it left in the file, else by time — and from that call's session: the script gate failures the hook reported
on the previous write of the same file (`gates`, the hook's whole text in `gates_text`) and the model's text since
the previous write of any file of the document (`said`).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
from pathlib import Path

WRITE_TOOLS = ("Write", "Edit", "MultiEdit")
_SLUG = re.compile(r"[^A-Za-z0-9]")
_SCRIPTS = re.compile(r"SCRIPT GATES — NOT PASSED \(\d+\):\n((?:.+\n?)+)")
_NUMBER = re.compile(r"^\s*\d+\.\s+")
_HOOK_HEAD = "unslopable gates on "
_SLACK = 2.0  # seconds around a write call within which its file's mtime may fall
SAID_MAX = 5  # the model's last texts kept for a version (a session's first write would carry all it said before)
_CACHE: dict = {}  # transcript path -> ((mtime_ns, size, folder), calls)


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def transcripts(folder: Path, since: float = 0.0) -> list[Path]:
    """The top-level transcripts of the sessions of `folder` and of the folders above it, touched since `since`."""
    root = config_dir() / "projects"
    out, seen = [], set()
    for f in dict.fromkeys([str(Path(folder).absolute()), os.path.realpath(folder)]):
        p = Path(f)
        for d in [p, *p.parents]:
            slug = _SLUG.sub("-", str(d))
            if slug in seen:
                continue
            seen.add(slug)
            for t in sorted((root / slug).glob("*.jsonl")):
                try:
                    if t.stat().st_mtime >= since:
                        out.append(t)
                except OSError:
                    pass
    return out


def _local(ts: str) -> float:
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(x if isinstance(x, str) else (x.get("text") or "") for x in content
                         if isinstance(x, (str, dict)))
    return ""


def script_lines(hook: str) -> list[str]:
    """The script gate failures a gate hook's text lists, each without its number."""
    m = _SCRIPTS.search(hook or "")
    return [_NUMBER.sub("", ln).strip() for ln in m.group(1).splitlines() if ln.strip()] if m else []


def _after(tool: str, ti: dict, result: dict):
    """The file's whole content after a write call, when the call and its result tell it."""
    if not isinstance(result, dict):
        result = {}
    if tool == "Write":
        c = ti.get("content")
        return c if isinstance(c, str) else result.get("content")
    before = result.get("originalFile")
    if not isinstance(before, str):
        return None
    edits = ti.get("edits") if tool == "MultiEdit" else [ti]
    for e in edits or []:
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or old not in before:
            return None
        before = before.replace(old, new) if e.get("replace_all") else before.replace(old, new, 1)
    return before


def _calls(path: Path, folder: str) -> list[dict]:
    """One transcript's entries in order: the model's texts ({"said": text}) and its calls that may have written into
    `folder` — Write/Edit/MultiEdit of a file in it (file, the content's sha1 after it, the gate hook's text after
    it) and every Bash call (`names`: its command, matched by time only); each with the time of the
    call and of its result."""
    try:
        st = path.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size, folder)
    hit = _CACHE.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    calls: list[dict] = []
    by_id: dict[str, dict] = {}
    base = folder.rstrip("/") + "/"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        return []
    if base not in raw and folder not in raw:
        _CACHE[str(path)] = (key, [])
        return []
    for line in raw.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("isSidechain"):
            continue
        kind, ts = r.get("type"), r.get("timestamp") or ""
        msg = r.get("message") if isinstance(r.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        if kind == "assistant":
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    calls.append({"said": b["text"].strip()})
                elif b.get("type") == "tool_use" and b.get("name") in WRITE_TOOLS + ("Bash",):
                    ti = b.get("input") if isinstance(b.get("input"), dict) else {}
                    fp = ti.get("file_path") or ""
                    if b["name"] == "Bash":
                        fp, names = "", str(ti.get("command") or "")
                    elif not fp.startswith(base):
                        continue
                    else:
                        names = ""
                    c = {"id": b.get("id"), "file": fp[len(base):] if fp else "", "names": names, "tool": b["name"],
                         "input": ti, "start": _local(ts), "end": None, "sha": None, "hook": "", "session": path.stem}
                    calls.append(c)
                    by_id[c["id"]] = c
        elif kind == "user":
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in by_id:
                    c = by_id[b["tool_use_id"]]
                    c["end"] = _local(ts)
                    if c["tool"] == "Bash":
                        continue
                    after = None if b.get("is_error") else _after(c["tool"], c["input"], r.get("toolUseResult"))
                    if after is not None:
                        c["sha"] = hashlib.sha1(after.encode("utf-8")).hexdigest()
        elif kind == "attachment":
            a = r.get("attachment") if isinstance(r.get("attachment"), dict) else {}
            c = by_id.get(a.get("toolUseID"))
            if c is not None and a.get("hookEvent", "PostToolUse") == "PostToolUse":
                t = _text(a.get("content")) or _text(a.get("blockingError")) or ""
                if _HOOK_HEAD in t:
                    c["hook"] = (c["hook"] + "\n\n" + t).strip() if c["hook"] else t
    for c in calls:
        c.pop("input", None)
        c.pop("id", None)
    _CACHE[str(path)] = (key, calls)
    return calls


def _stamp(t: str) -> float:
    try:
        return datetime.datetime.strptime(t, "%Y-%m-%d %H:%M:%S").timestamp()
    except (ValueError, TypeError):
        return 0.0


def reasons(folder: Path, writes: list[dict]) -> dict[int, dict]:
    """history write `n` -> {gates, gates_text, said, session} for every kept version a session's call made."""
    if not writes:
        return {}
    since = min(_stamp(w.get("time", "")) for w in writes) - 60
    sessions = [s for s in (_calls(t, str(Path(folder).absolute())) for t in transcripts(folder, since)) if s]
    calls = [(s, k) for s in sessions for k, c in enumerate(s) if "tool" in c]
    if not calls:
        return {}
    by_sha: dict[tuple, list] = {}
    for s, k in calls:
        if s[k]["sha"]:
            by_sha.setdefault((s[k]["file"], s[k]["sha"]), []).append((s, k))
    made: dict[int, tuple] = {}  # history n -> (session, index of the call that made it)
    used: set = set()

    def near(t: float, c: dict) -> bool:
        return c["start"] - _SLACK <= t <= (c["end"] or c["start"]) + _SLACK

    for w in writes:
        rel, t = w.get("file", ""), _stamp(w.get("time", ""))
        sha = (w.get("blob") or "").split(".", 1)[0]
        free = lambda x: (id(x[0]), x[1]) not in used  # noqa: E731
        cands = [x for x in by_sha.get((rel, sha), []) if free(x)]
        if not cands:  # no call left this content: the write call whose time the file's mtime falls in
            cands = [x for x in calls if free(x) and x[0][x[1]]["file"] == rel and near(t, x[0][x[1]])]
        if not cands:  # else a shell command that names the file, at that time
            cands = [x for x in calls if free(x) and x[0][x[1]]["tool"] == "Bash" and near(t, x[0][x[1]])
                     and Path(rel).name in x[0][x[1]]["names"]]
        if cands:
            best = min(cands, key=lambda x: abs(x[0][x[1]]["start"] - t))
            used.add((id(best[0]), best[1]))
            made[w.get("n")] = best
    made_file = {(id(s), k): w.get("file", "") for w in writes if w.get("n") in made for s, k in [made[w.get("n")]]}
    out: dict[int, dict] = {}
    for w in writes:
        if w.get("n") not in made:
            continue
        s, k = made[w.get("n")]
        rel = w.get("file", "")
        said, hook = [], ""
        for j in range(k - 1, -1, -1):  # back to the call before that wrote into the document
            e = s[j]
            if "said" in e:
                said.insert(0, e["said"])
            elif e["tool"] != "Bash" or (id(s), j) in used:
                break
        for j in range(k - 1, -1, -1):  # what the gate hook said on the write before of the same file
            e = s[j]
            if e.get("file") == rel or made_file.get((id(s), j)) == rel:
                hook = e.get("hook") or ""  # a shell write the hook did not gate: nothing said on it
                break
        out[w.get("n")] = {"gates": script_lines(hook), "gates_text": hook, "said": said[-SAID_MAX:], "session": s[k]["session"]}
    return out
