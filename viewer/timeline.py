"""A document's timeline, for the viewer (viewer/serve.py): everything that happened to the document, in time order.

Events: every kept version of every file of the document (gates/lib/history.py) with its word diff from the file's
version before, and, for TEXT.md and PLAN.md, the elements and plan levels it changed (an attempt of the plan belongs
to its level) with their own diffs; the script gate failures of a write; every verdict of a gate judge,
at the time it was recorded, a complaint (NOT PASSED) with its text. A complaint stays in the timeline when a later
verdict passes the same place. A kept version also carries `why`, what drove it, from the Claude Code session that
wrote it (viewer/reasons.py): the script gates' answer on the file's version before and the model's own words.

A document made before its versions were kept is rebuilt from what is on disk, each rebuilt event marked
`reconstructed`: the text of each element and each plan level as its judges saw it (`.gates/inputs/<judge>.md`, whose
mtime is when that version was first judged), the gate hook's log (`<cache>/gate_run.log`: when PLAN.md, TEXT.md or a
figure was written and whether its script gates failed) and every other file as it is now. What is not on disk is
listed in `missing`, never made up.

A judge's `unit` is a free string the gate code writes («element S1.e1 at TEXT.md line 2», «section S1», «PLAN.md
sections», «figures/x.png»…); a judge is attached to every unit whose plan id the string names, to a plan level
when it names one, to the element that shows a figure it names, else to the whole plan or the whole text.
"""
from __future__ import annotations

import difflib
import os
import re
import sys
import time
from pathlib import Path

LIB = Path(__file__).resolve().parent.parent / "gates" / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

import docs  # noqa: E402
import history  # noqa: E402
import state as gstate  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reasons  # noqa: E402

PLAN, TEXT = docs.PLAN_FILE, docs.TEXT_FILE
_TOKEN = re.compile(r"[A-Za-z0-9_.:\-]+")
_FIGURE_PATH = re.compile(r"figures/[^\s)\]>\"'(]+")
_LINE_NO = re.compile(r"\s*(?:at\s+)?(?:TEXT\.md\s+)?line\s+\d+")
_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")
KIND_OF_LEVEL = {1: "section", 2: "subsection", 3: "element"}


# ---------------------------------------------------------------- splitting the files into units

def text_elements(text: str) -> list[tuple[str, str]]:
    """(element id, its text) in file order: the lines after a `<!-- id -->` marker up to the next marker or
    heading, stripped."""
    out: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        m = docs._MARKER.match(line)
        if m:
            out.append((m.group(1), []))
        elif docs._HEADING.match(line):
            if out:
                out.append(("", []))  # closes the element; dropped below
        elif out:
            out[-1][1].append(line)
    seen: dict[str, str] = {}
    for eid, lines in out:
        if eid and eid not in seen:
            seen[eid] = "\n".join(lines).strip()
    return list(seen.items())


def text_headings(text: str) -> dict[str, str]:
    """element id -> the heading the element stands under (the closest one before it)."""
    heading, out = "", {}
    for line in text.splitlines():
        h = docs._HEADING.match(line)
        if h:
            heading = docs.plain(h.group(2))
            continue
        m = docs._MARKER.match(line)
        if m and m.group(1) not in out:
            out[m.group(1)] = heading
    return out


def plan_versions(text: str) -> dict[str, str]:
    """level key -> that level of this version of PLAN.md, its items as its judges see them. An attempt of the plan
    belongs to a level: a write that changed a level is that level's attempt."""
    plans, _ = docs.read_plan(text)
    return {f"plan:level:{name}": docs.level_text(plans[lvl]).rstrip("\n")
            for lvl, name in docs.LEVELS.items() if plans.get(lvl)}


def plan_line(r) -> str:
    """One plan item as the plan writes it (a tiles element with its tiles)."""
    return "\n".join(["- " + docs._item(r, False)] + ["  - " + docs._tile_item(t) for t in r.tiles])


# ---------------------------------------------------------------- diff

_WORDS = re.compile(r"\s+|\w+|[^\w\s]", re.U)
_DIFFS: dict = {}  # (old, new) -> diff, kept across requests: old versions do not change
_WORD_LIMIT = 4000  # tokens on each side of a changed block diffed word by word; a longer one, line by line


def diff(old: str, new: str) -> list[list[str]]:
    """Word diff: [op, text] pairs, op `=` kept, `-` removed, `+` added. The lines are matched first and only the
    changed ones are diffed word by word (a word diff of a whole level is quadratic), line against line where a
    changed block has as many lines on both sides."""
    key = (old, new)
    if key in _DIFFS:
        return [list(x) for x in _DIFFS[key]]
    out: list[list[str]] = []

    def put(op: str, s: str) -> None:
        if not s:
            return
        if out and out[-1][0] == op:
            out[-1][1] += s
        else:
            out.append([op, s])

    def words(a_text: str, b_text: str) -> None:
        a, b = _WORDS.findall(a_text), _WORDS.findall(b_text)
        if len(a) > _WORD_LIMIT or len(b) > _WORD_LIMIT:
            put("-", a_text)
            put("+", b_text)
            return
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                put("=", "".join(a[i1:i2]))
            else:
                put("-", "".join(a[i1:i2]))
                put("+", "".join(b[j1:j2]))

    la, lb = old.splitlines(keepends=True), new.splitlines(keepends=True)
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, la, lb, autojunk=False).get_opcodes():
        if tag == "equal":
            put("=", "".join(la[i1:i2]))
        elif tag == "replace" and i2 - i1 == j2 - j1:
            for x, y in zip(la[i1:i2], lb[j1:j2]):
                words(x, y)
        else:
            words("".join(la[i1:i2]), "".join(lb[j1:j2]))
    if len(_DIFFS) > 5000:
        _DIFFS.clear()
    _DIFFS[key] = [tuple(x) for x in out]
    return out


# ---------------------------------------------------------------- reading

def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _blob_text(folder: Path, blob: str) -> str | None:
    try:
        return history.blob_path(folder, blob).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def signature(folder: Path) -> str:
    """Changes whenever anything the viewer shows changes; the page polls with it."""
    parts = []
    for p in (folder / TEXT, folder / PLAN, folder / ".gates" / "verdicts.json", folder / ".gates" / "due.json",
              folder / ".gates" / "last_run.json", history.history_dir(folder) / history.INDEX):
        try:
            st = p.stat()
            parts.append(f"{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append("-")
    return "|".join(parts)


def _side(unit: str, meta: dict) -> str:
    f = meta.get("file", "")
    if f.endswith("/" + PLAN) or f == PLAN or unit.startswith(PLAN):
        return "plan"
    return "text"


def _slot(gate: str, unit: str) -> str:
    """A judge's place, the same across writes: its gate and unit without line numbers."""
    return f"{gate}|{_LINE_NO.sub('', unit).strip()}"


def _targets(unit: str, side: str, plan_ids: set, text_ids: set, images: dict, keys) -> list[str]:
    """The keys of the units a judge's `unit` string (or a script failure line) names; `keys` holds the units the
    document has now, so a level the plan no longer has goes to the whole plan."""
    if side == "plan":
        rest = unit[len(PLAN):] if unit.startswith(PLAN) else unit
        ids = [t for t in dict.fromkeys(_TOKEN.findall(rest)) if t in plan_ids]
        if ids:
            return [f"plan:{i}" for i in ids]
        for name in docs.LEVELS.values():
            if re.search(rf"\b{name}\b", rest) and f"plan:level:{name}" in keys:
                return [f"plan:level:{name}"]
        return ["plan:document"]
    found = [images[p] for p in _FIGURE_PATH.findall(unit) if p in images]
    found += [t for t in _TOKEN.findall(unit) if t in text_ids]
    found = list(dict.fromkeys(found))
    return [f"text:{i}" for i in found] if found else ["text:document"]


# ---------------------------------------------------------------- the document's units (the filter tree)

def _units(plan_now: str, text_now: str):
    """The plan and the text unit by unit, in the document's order; and the figure path -> element that shows it."""
    plans, _ = docs.read_plan(plan_now)
    rows = {r.id: r for lvl in docs.LEVELS for r in plans.get(lvl, [])}
    units: list[dict] = []

    def unit(key, side, kind, uid, label, depth, parent=""):
        units.append({"key": key, "side": side, "kind": kind, "id": uid, "label": label, "depth": depth,
                      "parent": parent, "complaints": 0, "verdicts": 0, "failing": False})

    unit("plan:document", "plan", "document", "", "The whole plan", 0)
    for lvl, name in docs.LEVELS.items():
        if plans.get(lvl):
            unit(f"plan:level:{name}", "plan", "level", name, f"Level {lvl}: {name}", 0)
    kids: dict[str, list] = {}
    for lvl in (2, 3):
        for r in plans.get(lvl, []):
            kids.setdefault(r.get("parent"), []).append(r)

    def put(r, depth: int) -> None:
        kind = KIND_OF_LEVEL[r.level] if r.level < 3 else (r.get("kind") or "element")
        unit(f"plan:{r.id}", "plan", kind, r.id, r.get("heading") or r.get("says") or r.id, depth,
             f"plan:{r.get('parent')}" if r.get("parent") else "")
        units[-1]["line"] = plan_line(r)
        units[-1]["level"] = f"plan:level:{docs.LEVELS[r.level]}"
        for k in kids.get(r.id, []):
            put(k, depth + 1)
    for r in plans.get(1, []):
        put(r, 1)

    unit("text:document", "text", "document", "", "The whole text", 0)
    headings = text_headings(text_now)
    images: dict[str, str] = {}
    shown: set = set()
    for eid, body in text_elements(text_now):
        chain, r = [], rows.get(eid)
        while r is not None and r.get("parent") and r.get("parent") in rows:
            r = rows[r.get("parent")]
            chain.insert(0, r)
        for depth, p in enumerate(chain, 1):
            if p.id not in shown:
                shown.add(p.id)
                label = (headings.get(eid) if p is chain[-1] else "") or p.get("heading") or p.id
                unit(f"text:{p.id}", "text", KIND_OF_LEVEL.get(p.level, "section"), p.id, label, depth,
                     f"text:{chain[depth - 2].id}" if depth > 1 else "")
        row = rows.get(eid)
        unit(f"text:{eid}", "text", (row.get("kind") if row else "") or "element", eid,
             (docs.plain(body).strip() or "(empty)")[:140], len(chain) + 1, f"text:{chain[-1].id}" if chain else "")
        for m in _IMAGE.finditer(body):
            images[m.group(1).lstrip("./")] = eid
    level_of = {f"plan:{i}": f"plan:level:{docs.LEVELS[r.level]}" for i, r in rows.items() if r.level in docs.LEVELS}
    return units, images, set(rows), level_of


def _pieces(name: str, text: str) -> dict[str, str]:
    """The pieces of a version of TEXT.md (its elements) or PLAN.md (its levels) that the timeline diffs one by one."""
    if name == TEXT:
        return {f"text:{eid}": body for eid, body in text_elements(text)}
    if name == PLAN:
        return plan_versions(text)
    return {}


TEXT_CAP = 30000  # characters of a first version sent with the timeline; the page fetches the rest from its blob


def _cap(text: str | None) -> str | None:
    return text if text is None or len(text) <= TEXT_CAP else text[:TEXT_CAP]


# ---------------------------------------------------------------- the timeline

def read_timeline(folder: Path) -> dict:
    folder = Path(folder)
    gates = folder / ".gates"
    verdicts = gstate.read(gates / "verdicts.json")
    index = gstate.read(gates / "requests.json")
    due = gstate.read(gates / "due.json")
    writes = history.writes(folder)
    plan_now, text_now = _read(folder / PLAN), _read(folder / TEXT)
    units, images, plan_ids, level_of = _units(plan_now, text_now)
    by_key = {u["key"]: u for u in units}
    text_ids = {u["id"] for u in units if u["side"] == "text" and u["id"]}

    # ------------------------------------------------ every judge: its place, file and the units it names
    ids = list(dict.fromkeys(list(verdicts) + [j for w in writes for j in w.get("judges", []) if j in index]
                             + [j for run in due.values() if isinstance(run, dict) for j in run.get("all", [])
                                if j in index]))
    meta_of, targets_of = {}, {}
    for jid in ids:
        v, meta = verdicts.get(jid, {}), index.get(jid, {})
        gate, u = v.get("gate") or meta.get("gate", ""), v.get("unit") or meta.get("unit", "")
        side = _side(u, meta)
        f = meta.get("file", "")
        rel = os.path.relpath(f, folder) if f and os.path.isabs(f) else (f or (PLAN if side == "plan" else TEXT))
        meta_of[jid] = (gate, u, side, rel)
        targets_of[jid] = list(dict.fromkeys(k if k in by_key else f"{side}:document"
                                             for k in _targets(u, side, plan_ids, text_ids, images, by_key)))

    current = _current(writes, due, verdicts, ids, meta_of, targets_of, level_of)
    for jid in ids:
        v = verdicts.get(jid)
        for key in targets_of[jid]:
            u = by_key[key]
            if v:
                u["verdicts"] += 1
                u["complaints"] += v.get("verdict") == "NOT PASSED"
            if jid in current and (v or {}).get("verdict") == "NOT PASSED":
                u["failing"] = True

    # ------------------------------------------------ events
    events: list[dict] = []
    # the history began when its first version was kept (a file kept then may be older: its time is its mtime)
    began = min((w.get("kept") or w.get("time", "") for w in writes), default="")
    missing: list[dict] = []
    last: dict[str, str] = {}
    last_n: dict[str, int] = {}
    disk: dict[str, tuple[str, bool]] = {}
    rebuilt = _reconstruct(folder, index, meta_of, targets_of, began, plan_now, text_now, events, missing,
                           bool(writes), last, last_n, disk)
    for key, (body, seen) in disk.items():
        if key in by_key:
            by_key[key]["disk"] = body
            by_key[key]["disk_note"] = DISK_SEEN if seen else DISK_NEVER
    events += _kept_events(folder, writes, last, last_n)
    try:  # transcripts are another program's files: a shape it changes must not take the timeline down
        drove = reasons.reasons(folder, writes)
    except Exception:  # noqa: BLE001
        drove = {}
    for e in events:
        if e["id"].startswith("w:"):
            e["why"] = drove.get(int(e["id"][2:])) if e["id"][2:].isdigit() else None
    missing += [{"file": rel, "what": why} for rel, why in sorted(history.skipped(folder).items())]
    for jid, v in verdicts.items():
        gate, u, side, rel = meta_of[jid]
        events.append({"id": f"v:{jid}", "kind": "verdict", "time": v.get("time", ""), "file": rel, "gate": gate,
                       "verdict": v.get("verdict", ""), "complaint": v.get("text", ""), "judge": jid,
                       "prompt": (gates / "inputs" / f"{jid}.md").exists(), "unit": u, "units": targets_of[jid],
                       "current": jid in current, "reconstructed": False})
    events.sort(key=lambda e: (e["time"], e["kind"] != "write", e.get("seq", 0)))
    for e in events:
        e.pop("seq", None)

    files: dict[str, int] = {}
    for e in events:  # numbered in time order, so kept versions go on from the rebuilt ones
        if e["kind"] == "write":
            files[e["file"]] = files.get(e["file"], 0) + 1
            e["n"] = files[e["file"]]
    if writes:
        state = "mixed" if rebuilt else "kept"
    else:
        state = "reconstructed" if rebuilt else "none"
    return {"folder": str(folder), "name": folder.name, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "signature": signature(folder), "history": state,
            "files": [{"file": f, "versions": n} for f, n in sorted(files.items())],
            "units": units, "gates": sorted({m[0] for m in meta_of.values() if m[0]}),
            "events": events, "missing": missing}


def _current(writes, due, verdicts, ids, meta_of, targets_of, level_of) -> set:
    """The judges of the latest gate run of each file: of its newest kept write the gates ran on and finished with its script
    gates passed; a file with no such write, its run in due.json. PLAN.md leaves out the levels approved as they
    stand (they are not judged again): a judge of such a level keeps its last verdict."""
    newest: dict[str, dict] = {}
    for w in writes:
        if w.get("gated", True) and w.get("noted", True) and not w.get("scripts") and not w.get("deleted"):
            newest[w.get("file", "")] = w
    latest = {j for w in newest.values() for j in w.get("judges", [])}
    for key, run in due.items():
        if isinstance(run, dict) and not any(f.strip() in newest for f in key.split(",")):
            latest |= set(run.get("all", []))
    judged = {level_of.get(k, k) for j in latest if j in targets_of and meta_of[j][2] == "plan" for k in targets_of[j]}
    slots: dict[str, list[str]] = {}
    for jid in ids:
        gate, u, side, _ = meta_of[jid]
        levels = {level_of.get(k, k) for k in targets_of[jid]}
        if side == "plan" and levels and all(k.startswith("plan:level:") and k not in judged for k in levels):
            slots.setdefault(_slot(gate, u), []).append(jid)
    current = set(latest)
    for group in slots.values():
        if not any(j in latest for j in group):
            done = [j for j in group if j in verdicts]
            if done:
                current.add(max(done, key=lambda j: verdicts[j].get("time", "")))
    return current


def _write_event(eid: str, time_: str, rel: str, n: int, **kw) -> dict:
    e = {"id": eid, "kind": "write", "time": time_, "file": rel, "n": n, "reconstructed": False, "tool": None,
         "diff": None, "text": None, "binary": False, "blob": None, "deleted": False, "pieces": [], "scripts": [],
         "script_count": 0, "outcome": "unknown", "gated": rel in (PLAN, TEXT) or rel.startswith("figures/"),
         "note": None, "same": False, "why": None}
    e.update(kw)
    return e


def _kept_events(folder: Path, writes: list[dict], rebuilt: dict, rebuilt_n: dict) -> list[dict]:
    """The events of the kept versions; `rebuilt` holds each piece's last version rebuilt from before the history
    began, so a first kept version shows only what changed since."""
    out: list[dict] = []
    last_text: dict[str, str] = {}
    last_piece: dict[str, str] = dict(rebuilt)
    piece_n: dict[str, int] = dict(rebuilt_n)
    count: dict[str, int] = {}
    for k, w in enumerate(writes):
        rel = w.get("file", "")
        count[rel] = count.get(rel, 0) + 1
        scripts = list(w.get("scripts") or [])
        outcome = "unknown" if not w.get("noted", True) else ("failed" if scripts else "passed")
        e = _write_event(f"w:{w.get('n')}", w.get("time", ""), rel, count[rel], tool=w.get("tool"),
                         same=bool(w.get("same")),
                         blob=w.get("blob"), deleted=bool(w.get("deleted")), scripts=scripts,
                         script_count=len(scripts), outcome=outcome, seq=k)
        text = None if w.get("deleted") or not w.get("blob") else _blob_text(folder, w["blob"])
        if w.get("blob") and text is None:
            e["binary"] = True
        if text is not None:
            if rel in last_text:
                e["diff"] = diff(last_text[rel], text)
            else:
                e["text"], e["cut"] = _cap(text), len(text) > TEXT_CAP
            last_text[rel] = text
            pieces = _pieces(rel, text)
            for key, body in pieces.items():
                if last_piece.get(key) == body or key in rebuilt and _bare(last_piece[key]) == _bare(body):
                    continue
                piece_n[key] = piece_n.get(key, 0) + 1
                e["pieces"].append({"unit": key, "n": piece_n[key], "text": body,
                                    "diff": diff(last_piece[key], body) if key in last_piece else None})
                last_piece[key] = body
            prefix = {TEXT: "text:", PLAN: "plan:level:"}.get(rel)
            for key in [k for k in last_piece if prefix and k.startswith(prefix) and k not in pieces]:
                piece_n[key] = piece_n.get(key, 0) + 1  # an element or level this version no longer has
                e["pieces"].append({"unit": key, "n": piece_n[key], "text": "", "removed": True,
                                    "diff": diff(last_piece.pop(key), "")})
        elif w.get("deleted"):
            last_text.pop(rel, None)
        out.append(e)
    return out


# ---------------------------------------------------------------- rebuilding a document made before its versions were kept

_SECTION = re.compile(r"^## (.+?)\n\n(.*?)(?=\n## |\Z)", re.S | re.M)
_ELEMENT_UNIT = re.compile(r"^element (\S+) at ")
_LEVEL_HEAD = re.compile(r"^The (sections|subsections|elements) of the plan \(the level being checked\)$")
_LOG = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (/.+?) (PLAN\.md|TEXT\.md|figures/.+?): (\d+) (script failures|"
                  r"judges due|judges asked)")


def _input_pieces(folder: Path, index: dict) -> list[tuple[str, str, str]]:
    """(time first judged, unit key, text) of every element text and plan level a judge's input holds."""
    out = []
    for p in sorted((folder / ".gates" / "inputs").glob("*.md")):
        jid = p.stem
        if jid not in index:
            continue
        try:
            body = p.read_text(encoding="utf-8")
            t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
        except (OSError, UnicodeDecodeError):
            continue
        for head, text in _SECTION.findall(body):
            text = text.strip()
            if head == "The element's text":
                m = _ELEMENT_UNIT.match(index[jid].get("unit", ""))
                if m:  # by the id the unit names, so an element the text no longer has keeps its versions
                    out.append((t, f"text:{m.group(1)}", text))
            else:
                m = _LEVEL_HEAD.match(head)
                if m:
                    out.append((t, f"plan:level:{m.group(1)}", text))
    return sorted(out)


def _log_lines(folder: Path) -> list[tuple[str, str, int, bool]]:
    """(time, file, N, whether its script gates failed) of every gate hook run on this document, from its log."""
    out, real = [], os.path.realpath(folder)
    try:
        with open(history.cache_dir() / "gate_run.log", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _LOG.match(line)
                if m and os.path.realpath(m.group(2)) == real:
                    for rel in m.group(3).split(", "):  # one line names every figure a call gated
                        out.append((m.group(1), rel, int(m.group(4)), m.group(5) == "script failures"))
    except OSError:
        pass
    return out


def _reconstruct(folder: Path, index, meta_of, targets_of, before: str, plan_now: str, text_now: str,
                 events: list, missing: list, kept: bool, last: dict, piece_n: dict, disk: dict) -> bool:
    """Rebuild the events before `before` (when the history began; '' when none) from what is on disk. Appends to
    `events` and `missing`, leaves each rebuilt piece's last version in `last` and, in `disk`, each piece of PLAN.md
    or TEXT.md on disk that no judge saw (key -> (text, whether a judge saw an earlier version)); returns whether
    anything was rebuilt."""
    def early(t: str) -> bool:
        return not before or t < before

    samples = [s for s in _input_pieces(folder, index) if early(s[0])]
    log = [ln for ln in _log_lines(folder) if early(ln[0])]
    if not samples and not log and kept:
        return False
    last_run = gstate.read(folder / ".gates" / "last_run.json")
    rebuilt: list[dict] = []
    count: dict[str, int] = {}
    for k, (t, rel, n, failed) in enumerate(log):
        count[rel] = count.get(rel, 0) + 1
        scripts = []
        if failed and last_run.get("file") == rel and last_run.get("status") == "script failures" \
                and abs(_secs(last_run.get("time", "")) - _secs(t)) <= 2:
            scripts = list(last_run.get("items") or [])
        rebuilt.append(_write_event(f"r:{k}", t, rel, count[rel], reconstructed=True, scripts=scripts,
                                    script_count=n if failed else 0, outcome="failed" if failed else "passed",
                                    judges_due=0 if failed else n, seq=k))
    # every version of an element or plan level goes to the first hook run of its file at or after it was judged
    for t, key, text in samples:
        if last.get(key) == text:
            continue
        piece_n[key] = piece_n.get(key, 0) + 1
        piece = {"unit": key, "n": piece_n[key], "text": text,
                 "diff": diff(last[key], text) if key in last else None}
        last[key] = text
        rel = PLAN if key.startswith("plan:") else TEXT
        host = next((e for e in rebuilt if e["file"] == rel and e["time"] >= t and not e["script_count"]), None)
        if host is None:
            count[rel] = count.get(rel, 0) + 1
            host = _write_event(f"r:p{len(rebuilt)}", t, rel, count[rel], reconstructed=True, seq=len(rebuilt))
            rebuilt.append(host)
        host["pieces"].append(piece)
    # the files as they are now (with kept versions, their first kept one is the first shown)
    gated_now = {TEXT: text_now, PLAN: plan_now}
    for p in sorted(_document_files(folder)):
        rel = p.relative_to(folder).as_posix()
        if kept:
            missing.append({"file": rel, "what": f"versions before {before} were not kept"})
            continue
        if rel in gated_now:
            # its pieces as on disk now are no event: when they were written was not kept (the mtime dates only the
            # last write of the whole file); the units carry them instead (`disk`)
            for key, body in _pieces(rel, gated_now[rel]).items():
                if key in last and _bare(last[key]) == _bare(body):
                    continue  # a judge sees a fenced block without its `:::` lines: the same version
                if last.get(key) != body:
                    disk[key] = (body, key in last)
            continue
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime))
        count[rel] = count.get(rel, 0) + 1
        e = _write_event(f"r:f:{rel}", t, rel, count[rel], reconstructed=True, seq=len(rebuilt), file_now=True)
        try:
            text = p.read_text(encoding="utf-8")
            e["text"], e["cut"] = _cap(text), len(text) > TEXT_CAP
        except UnicodeDecodeError:
            e["binary"] = True
        rebuilt.append(e)
    for e in rebuilt:  # a write nothing shows the text of says so, and why
        if not e["pieces"] and not e.get("file_now"):
            e["note"] = _unknown_note(e)
        e.pop("judges_due", None)
    events += rebuilt
    _missing(folder, rebuilt, log, samples, text_now, plan_now, missing, kept)
    return True


DISK_NEVER = "Never judged; this is only the text on disk now, its history was not kept."
DISK_SEEN = ("This is the text on disk now. It differs from the last version a judge saw, and when it changed was "
             "not kept.")


def _unknown_note(e: dict) -> str:
    """Why a rebuilt write of PLAN.md or TEXT.md shows nothing of what it wrote, in plain words."""
    piece = "plan level" if e["file"] == PLAN else "element"
    start = f"What this write changed is not known: {e['file']} itself was not kept then, and "
    if e["script_count"]:
        return start + "its script checks failed, so no judge saw its text."
    if not e.get("judges_due"):
        return start + "it called no judge, so no judge's prompt holds its text."
    return start + f"no judge's prompt left from this write shows a changed {piece} (later judges of the same " \
                   f"{piece}s replaced the rest)."


def _missing(folder, rebuilt, log, samples, text_now, plan_now, missing, kept) -> None:
    judged = {key for _, key, _ in samples}
    if not kept:
        for p in sorted(_document_files(folder)):
            rel = p.relative_to(folder).as_posix()
            if rel in (TEXT, PLAN):
                continue
            image = rel.startswith("figures/") and rel.lower().endswith(history._FIGURE_SUFFIXES)
            what = ("earlier versions of the image were not kept, only the one on disk" if image
                    else "earlier versions, if any, were not kept: only the one on disk")
            missing.append({"file": rel, "what": what})
    for rel, now in ((PLAN, plan_now), (TEXT, text_now)):
        if not now:
            continue
        what = "the whole file was not kept, only " + ("each level" if rel == PLAN else "each element") + \
            " as its judges saw it"
        missing.append({"file": rel, "what": what})
        failed = [t for t, f, _, bad in log if f == rel and bad]
        if failed:
            missing.append({"file": rel, "what": f"{len(failed)} write{'s' if len(failed) > 1 else ''} failed "
                                                 f"script gates ({', '.join(t[11:] for t in failed)}): what "
                                                 "they wrote was not kept"})
        never = [k for k in _pieces(rel, now) if k not in judged]
        if never:
            missing.append({"file": rel, "what": "never judged, so only as on disk now: "
                                                 + ", ".join(k.split(":", 1)[1] for k in never)})
    if not log:
        missing.append({"file": "", "what": "the gate hook's log has no line for this document: the times of its "
                                            "writes are those of the judges' inputs"})


_FENCE_LINE = re.compile(r"^[ \t]*:::.*\n?", re.M)


def _bare(text: str) -> str:
    return _FENCE_LINE.sub("", text).strip()


def _document_files(folder: Path) -> list[Path]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        out += [Path(root) / f for f in files if not f.startswith(".") and not (Path(root) / f).is_symlink()]
    return out


def _secs(t: str) -> float:
    try:
        return time.mktime(time.strptime(t, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0.0
