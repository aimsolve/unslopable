"""Tests of the document timeline: the versions the gate hook keeps of every file of a document
(`gates/lib/history.py`, driven by `hooks/gate_run.py`), the reader `viewer/timeline.py` that turns them and the
gates' verdicts into one timeline of the document, and the local server `viewer/serve.py`.

  SKIP_SPACY=1 python3 -m unittest tests.test_viewer -v      (system Python 3.9, as the hooks run)

The plugin's cache (`$UNSLOPABLE_CACHE`: `gate_run.log`, `documents.json`) is a temp folder (tests/isolate.py); every
subprocess here inherits it. The documents are copies of the fixture `tests/fixtures/doc` with a Polish brief, so the
English-only spaCy gates do not run.

The cases, by what the author sees:
  1. KeptVersions      every file of a document keeps every version, from Write/Edit and from Bash
  2. KeptTimeline      a document with kept versions reads as one timeline: writes with word diffs, verdicts
  3. Filtering         the history of one file, one element / plan level, one gate
  4. UnitsOfJudges     which element or plan level a judge's verdict belongs to
  5. Reconstructed     a document made before versions were kept: rebuilt from what is on disk, gaps listed
  6. HookToTimeline    end to end: the hook keeps the writes, the reader shows them with the verdicts
  7. Server            the viewer's local server: documents, timeline, live updates, files, the page
  Also: NotADocument (BRIEF.md alone is no document), Concurrent (hooks at once keep one version), NotKept
  (symlinks and files over history.MAX_BYTES), RemovedElement (an element gone from the text), CacheIsolation,
  BriefOnly (an Edit of a lone BRIEF.md starts nothing), UngatedVersion (a version no gate ran on keeps the element
  failing), SameContent (an unchanged gated write is marked same).
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import hashlib
import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "doc"
HOOK = ROOT / "hooks" / "gate_run.py"
RECORDED = ROOT / "tests" / "fixtures" / "hook_posttooluse_write.json"
SERVE = ROOT / "viewer" / "serve.py"
CACHE = Path(os.environ["UNSLOPABLE_CACHE"])
FMT = "%Y-%m-%d %H:%M:%S"
TIME = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")
RUN_WORD = re.compile(r"\bruns?\b", re.I)

sys.path.insert(0, str(ROOT / "gates" / "lib"))
sys.path.insert(0, str(ROOT / "viewer"))
import docs  # noqa: E402  (gates/lib: the plan parser, to build a level judge's input as the hook does)


# ================================================================ texts

FIXTURE_TEXT = (FIXTURE / "TEXT.md").read_text(encoding="utf-8")
FIXTURE_PLAN = (FIXTURE / "PLAN.md").read_text(encoding="utf-8")
FIXTURE_TERMS = (FIXTURE / "TERMS.md").read_text(encoding="utf-8")
FIXTURE_GATES = (FIXTURE / "GATES.md").read_text(encoding="utf-8")
BRIEF_PL = (FIXTURE / "BRIEF.md").read_text(encoding="utf-8").replace("English.", "Polish.")

E1_A = FIXTURE_TEXT.split("<!-- S1.e1 -->\n", 1)[1].split("\n", 1)[0]
E1_B = E1_A.replace("A family opens", "A household opens")  # a one-word change of element S1.e1
CUTOFF = "A low water cutoff stops the pump when the well runs low."
LONG = ("A low water cutoff stops the pump when the well runs low and the owner who lives in the house is away on a "
        "long trip abroad.")  # over GATES.md sentence_max_words (20)
assert E1_B != E1_A and CUTOFF in FIXTURE_TEXT

# the timeline's text shows its figure under figures/, as the writer puts it
TEXT_A = FIXTURE_TEXT.replace("(fig1.png)", "(figures/S1.e2.png)")
TEXT_B = TEXT_A.replace(E1_A, E1_B)
TEXT_C = TEXT_A.replace(CUTOFF, LONG)
PLAN_A = FIXTURE_PLAN
PLAN_B = FIXTURE_PLAN.replace("keeps the pump primed", "keeps the pump full")  # one word of the elements level
TERMS_A = FIXTURE_TERMS
TERMS_B = FIXTURE_TERMS.replace("- tap — known", "- tap — explain")
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(256))
assert PLAN_B != PLAN_A and TERMS_B != TERMS_A and "figures/S1.e2.png" in TEXT_A


# ================================================================ helpers

def stamp(ts: float) -> str:
    return time.strftime(FMT, time.localtime(ts))


def epoch(s: str) -> float:
    return time.mktime(time.strptime(s, FMT))


class Doc:
    """A document in a temp dir: a copy of the fixture with a Polish brief (or an empty folder), and a scratch folder
    beside it that is no document."""

    def __init__(self, fixture: bool = True):
        self.tmp = Path(tempfile.mkdtemp(prefix="viewer-test-")).resolve()
        self.path = self.tmp / "doc"
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        if fixture:
            # without hidden folders: any Bash command that names the fixture leaves its own .gates/ there
            shutil.copytree(FIXTURE, self.path, ignore=shutil.ignore_patterns(".*"))
            self.write("BRIEF.md", BRIEF_PL)
        else:
            self.path.mkdir()
        self.gates = self.path / ".gates"

    def write(self, rel: str, body, when: str | None = None) -> Path:
        p = self.path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
        if when:
            os.utime(p, (epoch(when), epoch(when)))
        return p

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def run_hook(payload: dict, env: dict | None = None) -> tuple[int, str, str]:
    """The gate hook on one PostToolUse payload: (exit code, its context for the chat, stderr)."""
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=200, env=env)
    ctx = ""
    if r.stdout.strip():
        try:
            ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
        except (ValueError, KeyError, TypeError):
            ctx = r.stdout
    return r.returncode, ctx, r.stderr


def write_call(path: Path, tool: str = "Write", env: dict | None = None) -> str:
    """A Write/Edit of `path` as Claude Code reports it to the hook; returns the hook's context."""
    d = json.loads(RECORDED.read_text())
    d["tool_name"] = tool
    d["cwd"] = str(path.parent)
    d["tool_input"] = {"file_path": str(path), "content": "(the file's content)"} if tool == "Write" else \
        {"file_path": str(path), "old_string": "(old)", "new_string": "(new)"}
    d["tool_response"] = {"filePath": str(path), "success": True}
    code, ctx, err = run_hook(d, env)
    assert code == 0, f"the hook exited {code}: {err}"
    return ctx


def bash_call(command: str, cwd: Path, env: dict | None = None) -> str:
    """Runs `command` in a shell in `cwd`, as the Bash tool does, then the hook on that call; returns its context."""
    r = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"the command itself failed: {r.stderr}"
    d = json.loads(RECORDED.read_text())
    d["tool_name"] = "Bash"
    d["cwd"] = str(cwd)
    d["tool_input"] = {"command": command, "description": "a command of the test"}
    d["tool_response"] = {"stdout": r.stdout, "stderr": r.stderr, "interrupted": False}
    code, ctx, err = run_hook(d, env)
    assert code == 0, f"the hook exited {code}: {err}"
    return ctx


def kept_writes(test: unittest.TestCase, doc: Doc) -> list[dict]:
    index = doc.gates / "history" / "index.json"
    test.assertTrue(index.exists(), "the hook kept no .gates/history/index.json")
    return json.loads(index.read_text(encoding="utf-8"))["writes"]


def last_of(test: unittest.TestCase, ws: list[dict], rel: str) -> dict:
    found = [w for w in ws if w["file"] == rel]
    test.assertTrue(found, f"no kept version of {rel}: {[w['file'] for w in ws]}")
    return found[-1]


def blob(doc: Doc, name: str) -> bytes:
    return (doc.gates / "history" / "blobs" / name).read_bytes()


def sha_name(content, rel: str) -> str:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    return f"{hashlib.sha1(raw).hexdigest()}.{Path(rel).suffix.lstrip('.').lower()}"


def documents_json() -> dict:
    p = CACHE / "documents.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def read_timeline(test: unittest.TestCase, folder: Path) -> dict:
    try:
        import timeline
    except ImportError as e:
        test.fail(f"viewer/timeline.py cannot be imported: {e}")
    return timeline.read_timeline(folder)


def side(diff: list, ops: str) -> str:
    return "".join(t for op, t in diff if op in ops)


def words(diff: list, op: str) -> str:
    """The parts of one op, joined and with whitespace collapsed: the words that op holds."""
    return " ".join(side(diff, op).split())


def writes(tl: dict, file: str | None = None) -> list[dict]:
    return [e for e in tl["events"] if e["kind"] == "write" and (file is None or e["file"] == file)]


def verdicts_of(tl: dict) -> dict:
    return {e["judge"]: e for e in tl["events"] if e["kind"] == "verdict"}


def by_n(tl: dict) -> dict:
    """The write events of the kept document by the number of their kept write (kept_doc: every write has its own
    second)."""
    return {KEPT_N[e["time"]]: e for e in writes(tl) if e["time"] in KEPT_N}


def kn(e: dict) -> int | None:
    return KEPT_N.get(e["time"]) if e["kind"] == "write" else None


def piece(event: dict, unit: str) -> dict:
    found = [p for p in event["pieces"] if p["unit"] == unit]
    assert len(found) == 1, (unit, [p["unit"] for p in event["pieces"]])
    return found[0]


def unit_of(tl: dict, key: str) -> dict:
    found = [u for u in tl["units"] if u["key"] == key]
    assert len(found) == 1, (key, sorted(u["key"] for u in tl["units"]))
    return found[0]


def keys_with_run(obj) -> list[str]:
    """Every dict key, at any depth, that is the word run(s) or has it as a part (`run_id`, `runs`)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if re.search(r"(^|[_\W])runs?($|[_\W])", str(k), re.I):
                out.append(str(k))
            out += keys_with_run(v)
    elif isinstance(obj, list):
        for v in obj:
            out += keys_with_run(v)
    return out


def judge_state(doc: Doc, judges: dict, verdicts: dict, due: dict) -> None:
    """The gates' state as the hook and the gate runner leave it.
    judges: id -> (gate, unit, gated file relative to the folder, input text or None for no input file);
    verdicts: id -> (PASSED | NOT PASSED, complaint, time); due: gated file -> ids of its latest gate run."""
    (doc.gates / "inputs").mkdir(parents=True, exist_ok=True)
    index = {}
    for jid, (gate, unit, rel, prompt) in judges.items():
        index[jid] = {"gate": gate, "unit": unit, "agent": f"unslopable:gate-{gate}", "file": str(doc.path / rel)}
        if prompt is not None:
            (doc.gates / "inputs" / f"{jid}.md").write_text(prompt, encoding="utf-8")
    (doc.gates / "requests.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    out = {}
    for jid, (verdict, complaint, t) in verdicts.items():
        gate, unit = index[jid]["gate"], index[jid]["unit"]
        out[jid] = {"verdict": verdict, "answer": verdict, "text": f"{verdict}\n{complaint}".strip(), "gate": gate,
                    "unit": unit, "time": t}
    (doc.gates / "verdicts.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (doc.gates / "due.json").write_text(json.dumps(
        {f: {"time": "2026-11-20 10:00:00", "all": ids, "due": []} for f, ids in due.items()}), encoding="utf-8")


def keep_by_hand(doc: Doc, entries: list[tuple]) -> None:
    """`.gates/history` as the hook keeps it. entries: (file, time, content or None when deleted, tool, script failure
    lines, judge ids), in write order."""
    h = doc.gates / "history"
    (h / "blobs").mkdir(parents=True, exist_ok=True)
    index = []
    for n, (rel, t, content, tool, scripts, judges) in enumerate(entries, 1):
        name = None
        if content is not None:
            name = sha_name(content, rel)
            (h / "blobs" / name).write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        index.append({"n": n, "file": rel, "time": t, "blob": name, "deleted": content is None, "tool": tool,
                      "scripts": scripts, "judges": judges,
                      "noted": rel in ("PLAN.md", "TEXT.md") or bool(judges)})
    (h / "index.json").write_text(json.dumps({"writes": index}, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------- the document with kept versions

D = "2026-11-20"
P1, P2, P3 = "heading-names-topic-aaaaaaaaaaa1", "goals-covered-aaaaaaaaaaa2", "goals-covered-aaaaaaaaaaa3"
J1, J1B = "cliche-bbbbbbbbbbb1", "purple-prose-bbbbbbbbbbb2"
J2, J2B = "cliche-ccccccccccc1", "purple-prose-ccccccccccc2"
J3, J6 = "transition-elements-bbbbbbbbbbb3", "figure-marks-ddddddddddd6"
J7, J8 = "term-explained-bbbbbbbbbbb7", "flow-sections-bbbbbbbbbbb8"
SCRIPT_LINE = f"[sentence-max-words] TEXT.md line 21 «{LONG[:30]}» — 26 words, over 20"
EL1 = "element S1.e1 at TEXT.md line 6"

KEPT_JUDGES = {
    P1: ("heading-names-topic", "PLAN.md S1", "PLAN.md", "# Judge input · gate heading-names-topic · PLAN.md S1\n"),
    P2: ("goals-covered", "PLAN.md elements", "PLAN.md", "# Judge input · gate goals-covered · PLAN.md elements\n"),
    P3: ("goals-covered", "PLAN.md elements", "PLAN.md", "# Judge input · gate goals-covered · PLAN.md elements\n"),
    J1: ("cliche", EL1, "TEXT.md", f"# Judge input · gate cliche · {EL1}\n\n## The element's text\n\n{E1_A}\n"),
    J1B: ("purple-prose", EL1, "TEXT.md", f"# Judge input · gate purple-prose · {EL1}\n\n## The element's text\n\n{E1_A}\n"),
    J2: ("cliche", EL1, "TEXT.md", f"# Judge input · gate cliche · {EL1}\n\n## The element's text\n\n{E1_B}\n"),
    J2B: ("purple-prose", EL1, "TEXT.md", f"# Judge input · gate purple-prose · {EL1}\n\n## The element's text\n\n{E1_B}\n"),
    J3: ("transition-elements", "seam S1.e2 → S1.e3 at TEXT.md line 12", "TEXT.md", "# Judge input · seam\n"),
    J6: ("figure-marks", "figures/S1.e2.png", "figures/S1.e2.png", "# Judge input · figure marks\n"),
    J7: ("term-explained", "term «pressure switch»", "TEXT.md", None),  # no input file: no prompt to show
    J8: ("flow-sections", "section S2", "TEXT.md", "# Judge input · gate flow-sections · section S2\n"),
}
KEPT_VERDICTS = {
    J6: ("NOT PASSED", "The red arrow is not explained.", f"{D} 10:00:30"),
    P1: ("NOT PASSED", "The heading answers its topic instead of naming it.", f"{D} 10:01:00"),  # = the write's time
    P2: ("PASSED", "", f"{D} 10:01:30"),
    J1: ("NOT PASSED", "«at once» is a cliché.", f"{D} 10:02:30"),
    J1B: ("NOT PASSED", "«wants the water» is purple prose.", f"{D} 10:02:30"),
    J3: ("NOT PASSED", "The valve comes from nowhere after the figure.", f"{D} 10:02:30"),
    J7: ("PASSED", "", f"{D} 10:02:30"),
    J8: ("NOT PASSED", "The settings do not follow from when the pump runs.", f"{D} 10:02:30"),
    J2: ("PASSED", "", f"{D} 10:04:30"),
    J2B: ("PASSED", "", f"{D} 10:04:30"),
    P3: ("PASSED", "", f"{D} 10:05:30"),
}
KEPT_DUE = {"PLAN.md": [P1, P3], "TEXT.md": [J2, J2B, J3, J7, J8], "figures/S1.e2.png": [J6]}
TEXT_JUDGES_A = [J1, J1B, J3, J7, J8]
TEXT_JUDGES_B = [J2, J2B, J3, J7, J8]


NOTES = (FIXTURE / "sources" / "notes.md").read_text(encoding="utf-8")
KEPT_ENTRIES = [
    ("BRIEF.md", f"{D} 10:00:00", BRIEF_PL, "Write", [], []),
    ("GATES.md", f"{D} 10:00:01", FIXTURE_GATES, "Write", [], []),
    ("TERMS.md", f"{D} 10:00:02", TERMS_A, "Write", [], []),
    ("sources/notes.md", f"{D} 10:00:03", NOTES, "Bash", [], []),
    ("figures/S1.e2.png", f"{D} 10:00:04", PNG, "Bash", [], [J6]),
    ("PLAN.md", f"{D} 10:01:00", PLAN_A, "Write", [], [P1, P2]),
    ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write", [], TEXT_JUDGES_A),
    ("TEXT.md", f"{D} 10:03:00", TEXT_C, "Edit", [SCRIPT_LINE], []),
    ("TEXT.md", f"{D} 10:04:00", TEXT_B, "Edit", [], TEXT_JUDGES_B),
    ("PLAN.md", f"{D} 10:05:00", PLAN_B, "Edit", [], [P1, P3]),
    ("TERMS.md", f"{D} 10:06:00", TERMS_B, "Edit", [], []),
    ("sources/notes.md", f"{D} 10:07:00", None, "Bash", [], []),
]
KEPT_N = {e[1]: n for n, e in enumerate(KEPT_ENTRIES, 1)}  # each kept write has its own second


def kept_doc() -> Doc:
    """A document written with versions kept, every file of it in its history:
     n  file               time      what
     1  BRIEF.md           10:00:00
     2  GATES.md           10:00:01
     3  TERMS.md           10:00:02
     4  sources/notes.md   10:00:03  (Bash)
     5  figures/S1.e2.png  10:00:04  (Bash; its judge J6 complains at 10:00:30)
     6  PLAN.md            10:01:00  P1 complains at the same second; P2 passes
     7  TEXT.md            10:02:00  version A: J1, J1B, J3, J8 complain, J7 passes
     8  TEXT.md            10:03:00  version C: a sentence too long in S2.1.e1, script gate fails
     9  TEXT.md            10:04:00  version B: one word of S1.e1 changed, S2.1.e1 back; J2, J2B pass
    10  PLAN.md            10:05:00  one word of the elements level changed; P3 passes, P1 stands
    11  TERMS.md           10:06:00  (Edit) one word changed
    12  sources/notes.md   10:07:00  deleted (Bash)"""
    doc = Doc()
    keep_by_hand(doc, KEPT_ENTRIES)
    # the folder as it is now: the last version of each file
    doc.write("BRIEF.md", BRIEF_PL, f"{D} 10:00:00")
    doc.write("GATES.md", FIXTURE_GATES, f"{D} 10:00:01")
    doc.write("figures/S1.e2.png", PNG, f"{D} 10:00:04")
    doc.write("TEXT.md", TEXT_B, f"{D} 10:04:00")
    doc.write("PLAN.md", PLAN_B, f"{D} 10:05:00")
    doc.write("TERMS.md", TERMS_B, f"{D} 10:06:00")
    (doc.path / "sources" / "notes.md").unlink()
    judge_state(doc, KEPT_JUDGES, KEPT_VERDICTS, KEPT_DUE)
    return doc


# ================================================================ 1. every file keeps every version

class KeptVersions(unittest.TestCase):
    """Done when 3: every non-hidden file of a document keeps every version, written by Write/Edit or by Bash."""

    def setUp(self):
        self.doc = Doc()

    def tearDown(self):
        self.doc.close()

    def assert_entry(self, w: dict, rel: str, tool: str, content) -> None:
        self.assertEqual(w["file"], rel)
        self.assertEqual(w["tool"], tool)
        self.assertFalse(w["deleted"])
        self.assertRegex(w["time"], TIME)
        self.assertEqual(w["blob"], sha_name(content, rel))
        raw = content.encode("utf-8") if isinstance(content, str) else content
        self.assertEqual(blob(self.doc, w["blob"]), raw, f"the kept blob of {rel} is not its content")

    def test_writing_brief_in_a_new_folder_makes_a_document_and_keeps_the_brief(self):
        new = Doc(fixture=False)
        try:
            p = new.write("BRIEF.md", BRIEF_PL)
            write_call(p)
            ws = kept_writes(self, new)
            self.assertEqual(len(ws), 1, ws)
            w = ws[0]
            self.assertEqual(w["n"], 1)
            self.assertEqual(w["file"], "BRIEF.md")
            self.assertEqual(w["tool"], "Write")
            self.assertFalse(w["deleted"])
            self.assertEqual(w["time"], stamp(p.stat().st_mtime), "the time of a version is its file's mtime")
            self.assertEqual(w["blob"], sha_name(BRIEF_PL, "BRIEF.md"))
            self.assertEqual((new.gates / "history" / "blobs" / w["blob"]).read_text(encoding="utf-8"), BRIEF_PL)
            listed = {os.path.realpath(k): v for k, v in documents_json().items()}
            self.assertIn(str(new.path), listed, "the new document is not in $UNSLOPABLE_CACHE/documents.json")
            self.assertRegex(listed[str(new.path)], TIME)
        finally:
            new.close()

    def test_the_first_call_keeps_every_file_and_an_edit_keeps_only_what_changed(self):
        terms = self.doc.path / "TERMS.md"
        write_call(terms, "Edit")
        first = kept_writes(self, self.doc)
        self.assertEqual({w["file"] for w in first},
                         {"BRIEF.md", "GATES.md", "PLAN.md", "TERMS.md", "TEXT.md", "sources/notes.md"},
                         "the first call keeps every non-hidden file of the document")
        self.assertEqual([w["n"] for w in first], list(range(1, len(first) + 1)))
        self.assertEqual([w["file"] for w in first if w["file"].startswith("/")], [], "paths are relative")
        old = next(w for w in first if w["file"] == "TERMS.md")
        self.doc.write("TERMS.md", TERMS_B, f"{D} 11:30:00")
        write_call(terms, "Edit")
        ws = kept_writes(self, self.doc)
        self.assertEqual(len(ws), len(first) + 1, "an Edit of one file keeps that file only")
        self.assert_entry(ws[-1], "TERMS.md", "Edit", TERMS_B)
        self.assertEqual(ws[-1]["n"], len(first) + 1)
        self.assertEqual(ws[-1]["time"], f"{D} 11:30:00", "the time of a version is its file's mtime")
        self.assertEqual(blob(self.doc, old["blob"]).decode("utf-8"), TERMS_A, "the earlier version is still kept")

    def test_a_change_made_outside_the_tools_is_kept_on_the_next_call(self):
        write_call(self.doc.path / "BRIEF.md")
        before = len(kept_writes(self, self.doc))
        self.doc.write("GATES.md", FIXTURE_GATES.replace("sentence_max_words: 20", "sentence_max_words: 22"))
        write_call(self.doc.path / "TEXT.md")
        new = kept_writes(self, self.doc)[before:]
        self.assertIn("GATES.md", [w["file"] for w in new],
                      "every file whose content changed since its last kept version is kept on every call")
        self.assertIn("sentence_max_words: 22", blob(self.doc, last_of(self, new, "GATES.md")["blob"]).decode())

    def test_a_script_run_by_bash_that_names_the_file_is_kept(self):
        facts = self.doc.path / "FACTS.md"
        bash_call(f"python3 -c \"open('{facts}','w').write('x')\"", self.doc.scratch)
        ws = kept_writes(self, self.doc)
        w = [w for w in ws if w["file"] == "FACTS.md"]
        self.assertEqual(len(w), 1, [x["file"] for x in ws])
        self.assert_entry(w[0], "FACTS.md", "Bash", "x")

    def test_bash_with_cwd_inside_the_document_and_a_relative_path_is_kept(self):
        bash_call("python3 -c \"open('../FACTS.md','w').write('y')\"", self.doc.path / "sources")
        ws = kept_writes(self, self.doc)
        w = [w for w in ws if w["file"] == "FACTS.md"]
        self.assertEqual(len(w), 1, [x["file"] for x in ws])
        self.assert_entry(w[0], "FACTS.md", "Bash", "y")

    def test_a_script_that_never_names_the_document_is_kept_for_a_listed_document(self):
        write_call(self.doc.path / "BRIEF.md")  # the document is now in documents.json
        script = self.doc.scratch / "write_facts.py"
        script.write_text(f"open({str(self.doc.path / 'FACTS.md')!r}, 'w').write('from a script')\n", encoding="utf-8")
        bash_call(f"python3 {script.name}", self.doc.scratch)
        w = last_of(self, kept_writes(self, self.doc), "FACTS.md")
        self.assert_entry(w, "FACTS.md", "Bash", "from a script")

    def test_files_bash_makes_under_sources_research_and_figures_are_kept(self):
        p = self.doc.path
        bash_call(f"ls {p}", self.doc.scratch)  # every file of the document kept once
        before = len(kept_writes(self, self.doc))
        bash_call(f"mkdir -p {p}/sources/web {p}/research {p}/figures && printf 'page' > {p}/sources/web/Page.HTML"
                  f" && printf '{{}}' > {p}/research/notes.json && printf 'draft' > {p}/figures/readme.txt",
                  self.doc.scratch)
        new = kept_writes(self, self.doc)[before:]
        self.assertEqual({w["file"] for w in new},
                         {"sources/web/Page.HTML", "research/notes.json", "figures/readme.txt"})
        page = next(w for w in new if w["file"] == "sources/web/Page.HTML")
        self.assert_entry(page, "sources/web/Page.HTML", "Bash", "page")
        self.assertTrue(page["blob"].endswith(".html"), "a blob is named <sha1>.<lowercase suffix>")

    def test_a_deleted_file_is_an_entry_marked_deleted(self):
        bash_call(f"ls {self.doc.path}", self.doc.scratch)  # every file of the document kept once
        self.assertIn("sources/notes.md", [w["file"] for w in kept_writes(self, self.doc)])
        bash_call(f"rm {self.doc.path / 'sources' / 'notes.md'}", self.doc.scratch)
        w = last_of(self, kept_writes(self, self.doc), "sources/notes.md")
        self.assertTrue(w["deleted"])
        self.assertIsNone(w["blob"])
        self.assertEqual(w["tool"], "Bash")

    def test_bash_that_changes_nothing_adds_nothing_and_hidden_files_are_never_kept(self):
        write_call(self.doc.path / "TEXT.md")  # the gates write .gates/ (inputs, due.json …)
        p = self.doc.path
        bash_call(f"ls {p}", self.doc.scratch)  # every file of the document kept once
        before = kept_writes(self, self.doc)
        self.assertIn("BRIEF.md", [w["file"] for w in before], "a Bash command naming the document kept nothing")
        bash_call(f"ls {p} && touch {p}/TERMS.md", self.doc.scratch)  # a new mtime, the same content
        self.assertEqual(kept_writes(self, self.doc), before, "a Bash call that changed no content added an entry")
        bash_call(f"mkdir -p {p}/.gates/custom {p}/.images && printf 'x' > {p}/.gates/custom/own.py"
                  f" && printf 'x' > {p}/.images/a.png && printf 'x' > {p}/.notes.md", self.doc.scratch)
        ws = kept_writes(self, self.doc)
        self.assertEqual(ws, before, "a hidden file was kept")
        self.assertEqual([w["file"] for w in ws if any(part.startswith(".") for part in w["file"].split("/"))], [])

    def test_a_text_write_that_fails_script_gates_keeps_the_failures_and_no_judges(self):
        self.doc.write("TEXT.md", FIXTURE_TEXT.replace(CUTOFF, LONG))
        ctx = write_call(self.doc.path / "TEXT.md")
        self.assertIn("SCRIPT GATES — NOT PASSED", ctx)  # the case is what it claims to be
        w = last_of(self, kept_writes(self, self.doc), "TEXT.md")
        self.assertEqual(blob(self.doc, w["blob"]).decode("utf-8"), FIXTURE_TEXT.replace(CUTOFF, LONG))
        self.assertTrue(any("sentence-max-words" in s for s in w["scripts"]), w["scripts"])
        self.assertEqual(w["judges"], [])
        self.assertTrue(w["noted"])

    def test_a_text_write_that_passes_keeps_every_judge_of_its_gates(self):
        ctx = write_call(self.doc.path / "TEXT.md")
        self.assertIn("Script gates passed", ctx)
        w = last_of(self, kept_writes(self, self.doc), "TEXT.md")
        due = json.loads((self.doc.gates / "due.json").read_text())["TEXT.md"]["all"]
        self.assertTrue(due)
        self.assertEqual(w["scripts"], [])
        self.assertEqual(set(w["judges"]), set(due))
        self.assertTrue(w["noted"])

    def test_plan_and_text_writes_are_entries_even_unchanged_with_one_blob(self):
        write_call(self.doc.path / "TEXT.md")
        ws = kept_writes(self, self.doc)
        n_text, n_plan = (len([w for w in ws if w["file"] == f]) for f in ("TEXT.md", "PLAN.md"))
        write_call(self.doc.path / "TEXT.md")
        write_call(self.doc.path / "PLAN.md")
        write_call(self.doc.path / "PLAN.md")
        ws = kept_writes(self, self.doc)
        text = [w for w in ws if w["file"] == "TEXT.md"]
        plan = [w for w in ws if w["file"] == "PLAN.md"]
        self.assertEqual(len(text), n_text + 1, "a second Write of the same TEXT.md is not an entry")
        self.assertEqual(len(plan), n_plan + 2, "a Write of the same PLAN.md is not an entry")
        self.assertTrue(all(w["noted"] for w in text[-1:] + plan[-2:]))
        self.assertEqual(len({w["blob"] for w in text}), 1)
        kept_blobs = {w["blob"] for w in ws if w["blob"]}
        on_disk = {p.name for p in (self.doc.gates / "history" / "blobs").iterdir()}
        self.assertEqual(on_disk, kept_blobs, "the same content is kept in one blob, and only kept content")

    def test_documents_json_drops_folders_without_a_brief(self):
        gone = self.doc.tmp / "gone"
        gone.mkdir()
        data = documents_json()
        data[str(gone)] = f"{D} 09:00:00"
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "documents.json").write_text(json.dumps(data), encoding="utf-8")
        write_call(self.doc.path / "BRIEF.md")
        listed = {os.path.realpath(k): v for k, v in documents_json().items()}
        self.assertNotIn(str(gone), listed)
        self.assertIn(str(self.doc.path), listed)
        last = max(w["time"] for w in kept_writes(self, self.doc))
        self.assertEqual(listed[str(self.doc.path)], last, "documents.json maps a folder to its last kept write")

    def test_the_hook_still_gates_when_the_history_cannot_be_written(self):
        self.doc.gates.mkdir(exist_ok=True)
        (self.doc.gates / "history").write_text("not a folder", encoding="utf-8")
        ctx = write_call(self.doc.path / "TEXT.md")  # asserts exit 0
        self.assertIn("Judge gates", ctx, "the gates did not run")
        self.assertIn("TEXT.md", json.loads((self.doc.gates / "due.json").read_text()))


class NotADocument(unittest.TestCase):
    """A folder with only BRIEF.md is no document: a Bash call from inside it or naming a path in it creates
    nothing. A BRIEF.md plus MATERIAL.md, GATES.md, PLAN.md or a .gates/ folder makes it one."""

    def setUp(self):
        self.doc = Doc(fixture=False)
        self.doc.write("BRIEF.md", BRIEF_PL)
        (self.doc.path / "sub").mkdir()

    def tearDown(self):
        self.doc.close()

    def listed(self) -> set:
        return {os.path.realpath(k) for k in documents_json()}

    def test_bash_from_a_subfolder_or_naming_a_path_inside_creates_nothing(self):
        p = self.doc.path
        real = self.doc.tmp / "real"  # the control: a document, named by the same commands
        real.mkdir()
        (real / "BRIEF.md").write_text(BRIEF_PL, encoding="utf-8")
        (real / "GATES.md").write_text(FIXTURE_GATES, encoding="utf-8")
        bash_call(f"printf 'x' > {p}/sub/a.md && printf 'x' > {real}/a.md", self.doc.scratch)
        bash_call(f"printf 'y' > b.md && ls .. {real}", p / "sub")
        self.assertTrue((real / ".gates" / "history" / "index.json").exists(), "the control document kept nothing")
        self.assertFalse((p / ".gates").exists(), "a folder with only BRIEF.md got a .gates/")
        self.assertNotIn(str(p), self.listed(), "a folder with only BRIEF.md was put in documents.json")

    def test_brief_with_one_more_file_of_a_document_is_a_document(self):
        for extra in ("MATERIAL.md", "GATES.md", "PLAN.md", ".gates"):
            with self.subTest(extra=extra):
                d = Doc(fixture=False)
                try:
                    d.write("BRIEF.md", BRIEF_PL)
                    if extra == ".gates":
                        d.gates.mkdir()
                    else:
                        d.write(extra, FIXTURE_GATES if extra == "GATES.md" else
                                FIXTURE_PLAN if extra == "PLAN.md" else "There is no material: research it.\n")
                    bash_call(f"printf 'x' > {d.path}/notes.md", d.scratch)
                    ws = kept_writes(self, d)
                    self.assertIn("notes.md", [w["file"] for w in ws])
                    self.assertIn(str(d.path), self.listed())
                finally:
                    d.close()


class Concurrent(unittest.TestCase):
    """Several hook processes at once after one change keep exactly one new version of the file."""

    def test_one_change_seen_by_many_hooks_is_kept_once(self):
        doc = Doc()
        try:
            p = doc.path
            bash_call(f"ls {p}", doc.scratch)  # every file of the document kept once
            before = [w for w in kept_writes(self, doc) if w["file"] == "TERMS.md"]
            doc.write("TERMS.md", TERMS_B)
            payloads = []
            for k in range(8):
                d = json.loads(RECORDED.read_text())
                if k % 2:
                    d.update(tool_name="Bash", cwd=str(doc.scratch),
                             tool_input={"command": f"ls {p}", "description": "list"})
                else:
                    d.update(tool_name="Edit", cwd=str(p), tool_input={
                        "file_path": str(p / "TERMS.md"), "old_string": "known", "new_string": "explain"})
                payloads.append(d)
            procs = [subprocess.Popen([sys.executable, str(HOOK)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in payloads]
            for proc, d in zip(procs, payloads):
                proc.stdin.write(json.dumps(d))
                proc.stdin.close()
            for proc in procs:
                proc.wait(timeout=200)
                proc.stdout.close()
                proc.stderr.close()
                self.assertEqual(proc.returncode, 0)
            ws = kept_writes(self, doc)
            after = [w for w in ws if w["file"] == "TERMS.md"]
            self.assertEqual(len(after), len(before) + 1, f"{len(after) - len(before)} new versions of TERMS.md kept")
            self.assertEqual(blob(doc, after[-1]["blob"]).decode("utf-8"), TERMS_B)
            self.assertEqual([w["n"] for w in ws], list(range(1, len(ws) + 1)), "n is not 1, 2, 3 … without gaps")
        finally:
            doc.close()


class NotKept(unittest.TestCase):
    """A symlink or a file over history.MAX_BYTES is not kept, and the timeline lists it as missing with a reason."""

    def test_a_symlink_and_a_file_too_big_are_not_kept_and_are_listed_missing(self):
        try:
            import history
        except ImportError as e:
            self.fail(f"gates/lib/history.py cannot be imported: {e}")
        limit = getattr(history, "MAX_BYTES", None)
        self.assertIsInstance(limit, int, "history.MAX_BYTES is missing")
        doc = Doc()
        try:
            outside = doc.tmp / "outside.md"
            outside.write_text("outside the document", encoding="utf-8")
            os.symlink(outside, doc.path / "sources" / "link.md")
            with open(doc.path / "sources" / "big.bin", "wb") as f:
                f.truncate(limit + 1)  # sparse: no real bytes written
            bash_call(f"ls {doc.path}", doc.scratch)
            files = [w["file"] for w in kept_writes(self, doc)]
            self.assertIn("BRIEF.md", files, "the other files were not kept")
            self.assertNotIn("sources/link.md", files, "a symlink was kept")
            self.assertNotIn("sources/big.bin", files, "a file over history.MAX_BYTES was kept")
            missing = {m["file"]: m["what"] for m in read_timeline(self, doc.path)["missing"]}
            for rel in ("sources/link.md", "sources/big.bin"):
                self.assertIn(rel, missing, f"{rel} is not listed as missing")
                self.assertTrue(missing[rel].strip(), f"{rel} is missing with no reason")
        finally:
            doc.close()


class BriefOnly(unittest.TestCase):
    """A folder with a BRIEF.md and nothing of the plugin: an Edit or MultiEdit of that BRIEF.md starts no document;
    only a Write of BRIEF.md in a folder with no .gates/history does."""

    def test_an_edit_of_an_existing_brief_starts_no_document(self):
        for tool in ("Edit", "MultiEdit"):
            with self.subTest(tool=tool):
                d = Doc(fixture=False)
                try:
                    p = d.write("BRIEF.md", BRIEF_PL)
                    payload = json.loads(RECORDED.read_text())
                    payload.update(tool_name=tool, cwd=str(d.path), tool_input={
                        "file_path": str(p), "old_string": "Polish.", "new_string": "Polish. ",
                        "edits": [{"old_string": "Polish.", "new_string": "Polish. "}]})
                    code, _, err = run_hook(payload)
                    self.assertEqual(code, 0, err)
                    self.assertFalse((d.path / ".gates").exists(), f"an {tool} of BRIEF.md made a .gates/")
                    self.assertNotIn(str(d.path), {os.path.realpath(k) for k in documents_json()})
                    # the control: a Write of BRIEF.md in a folder with no history starts the document
                    write_call(p)
                    self.assertIn("BRIEF.md", [w["file"] for w in kept_writes(self, d)])
                    self.assertIn(str(d.path), {os.path.realpath(k) for k in documents_json()})
                finally:
                    d.close()


class UngatedVersion(unittest.TestCase):
    """A gated TEXT.md write whose judge said NOT PASSED, then a version no gate ran on: the element stays failing,
    and each kept version says whether it was gated."""

    def scenario(self, change) -> None:
        doc = Doc()
        try:
            text = doc.path / "TEXT.md"
            self.assertIn("Script gates passed", write_call(text))
            reqs = json.loads((doc.gates / "requests.json").read_text())
            el = sorted(j for j, m in reqs.items() if m["unit"].startswith("element S1.e1 "))
            self.assertTrue(el, "no element judge of S1.e1 was asked for")
            (doc.gates / "verdicts.json").write_text(json.dumps({el[0]: {
                "verdict": "NOT PASSED", "answer": "NOT PASSED", "text": "NOT PASSED\n- «at once» is a cliché.",
                "gate": reqs[el[0]]["gate"], "unit": reqs[el[0]]["unit"], "time": time.strftime(FMT)}},
                ensure_ascii=False), encoding="utf-8")
            change(doc)
            ws = [w for w in kept_writes(self, doc) if w["file"] == "TEXT.md"]
            self.assertEqual(len(ws), 2, ws)
            self.assertIs(ws[0]["gated"], True, "the Write of TEXT.md ran its gates")
            self.assertIs(ws[1]["gated"], False, "no gate ran on the second version")
            self.assertIn(E1_B, blob(doc, ws[1]["blob"]).decode("utf-8"))
            u = unit_of(read_timeline(self, doc.path), "text:S1.e1")
            self.assertTrue(u["failing"], "the element's complaint was dropped by a version no gate checked")
        finally:
            doc.close()

    def test_a_version_written_by_a_bash_script(self):
        def change(doc: Doc) -> None:
            t = doc.path / "TEXT.md"
            bash_call(f"python3 -c \"import pathlib; p = pathlib.Path('{t}'); "
                      f"p.write_text(p.read_text().replace('A family opens', 'A household opens'))\"", doc.scratch)
        self.scenario(change)

    def test_a_version_changed_outside_the_tools(self):
        def change(doc: Doc) -> None:
            doc.write("TEXT.md", FIXTURE_TEXT.replace(E1_A, E1_B))
            bash_call(f"ls {doc.path}", doc.scratch)  # the next hook call keeps it
        self.scenario(change)


class SameContent(unittest.TestCase):
    """A Write of TEXT.md or PLAN.md with unchanged content is kept with `same` true, on the entry and the event."""

    def test_an_unchanged_write_is_marked_same(self):
        doc = Doc()
        try:
            bash_call(f"ls {doc.path}", doc.scratch)  # the first version of every file
            write_call(doc.path / "TEXT.md")  # unchanged
            write_call(doc.path / "PLAN.md")  # unchanged
            doc.write("TEXT.md", FIXTURE_TEXT.replace(E1_A, E1_B), "2030-01-01 12:00:00")
            write_call(doc.path / "TEXT.md")  # changed
            ws = kept_writes(self, doc)
            text = [w for w in ws if w["file"] == "TEXT.md"]
            plan = [w for w in ws if w["file"] == "PLAN.md"]
            self.assertEqual([w.get("same") for w in text], [False, True, False])
            self.assertEqual([w.get("same") for w in plan], [False, True])
            tl = read_timeline(self, doc.path)
            for rel, want in (("TEXT.md", [False, True, False]), ("PLAN.md", [False, True])):
                got = [e.get("same") for e in writes(tl, rel)]
                self.assertEqual(sorted(got, key=str), sorted(want, key=str), f"{rel}: same on the write events")
            changed = [e for e in writes(tl, "TEXT.md") if e["time"] == "2030-01-01 12:00:00"]
            self.assertEqual([e.get("same") for e in changed], [False])
        finally:
            doc.close()


class CacheIsolation(unittest.TestCase):
    """Done when 5: with $UNSLOPABLE_CACHE set, the hook writes nothing under ~/.cache (HOME is a temp dir here)."""

    def test_the_hook_writes_its_log_and_list_only_into_the_cache_it_is_given(self):
        doc = Doc()
        try:
            home, cache = doc.tmp / "home", doc.tmp / "cache"
            home.mkdir()
            env = dict(os.environ, HOME=str(home), UNSLOPABLE_CACHE=str(cache))
            write_call(doc.path / "TEXT.md", env=env)
            bash_call(f"python3 -c \"open('{doc.path / 'FACTS.md'}','w').write('x')\"", doc.scratch, env=env)
            self.assertFalse((home / ".cache").exists(), "the hook wrote under ~/.cache")
            self.assertIn(str(doc.path), (cache / "gate_run.log").read_text(encoding="utf-8"))
            self.assertIn(str(doc.path), {os.path.realpath(k) for k in
                                          json.loads((cache / "documents.json").read_text(encoding="utf-8"))})
        finally:
            doc.close()


# ================================================================ 2. the timeline of a document with kept versions

class KeptTimeline(unittest.TestCase):
    """Done when 1: one timeline in time order, each write with its word diff, each verdict red or green."""

    @classmethod
    def setUpClass(cls):
        cls.doc = kept_doc()

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def setUp(self):
        self.tl = read_timeline(self, self.doc.path)

    def test_the_document_and_its_files(self):
        tl = self.tl
        self.assertEqual(tl["folder"], str(self.doc.path))
        self.assertTrue(tl["name"])
        self.assertEqual(tl["history"], "kept")
        self.assertEqual(tl["missing"], [], "a document with every version kept misses nothing")
        versions = {f["file"]: f["versions"] for f in tl["files"]}
        self.assertEqual(versions.get("TEXT.md"), 3)
        self.assertEqual(versions.get("PLAN.md"), 2)
        self.assertEqual(versions.get("TERMS.md"), 2)
        self.assertEqual(versions.get("BRIEF.md"), 1)
        gates = {m[0] for m in KEPT_JUDGES.values()}
        self.assertTrue(gates <= set(tl["gates"]), set(tl["gates"]))
        self.assertEqual(tl["gates"], sorted(tl["gates"]))

    def test_one_write_event_per_kept_write_and_one_verdict_event_per_verdict(self):
        ws = writes(self.tl)
        self.assertEqual(len(ws), 12)
        self.assertEqual(sorted(by_n(self.tl)), list(range(1, 13)))
        self.assertEqual([by_n(self.tl)[n]["file"] for n in range(1, 13)], [e[0] for e in KEPT_ENTRIES])
        for e in ws:
            self.assertIsInstance(e["n"], int)
            self.assertFalse(e["reconstructed"])
        self.assertEqual(by_n(self.tl)[11]["tool"], "Edit")
        self.assertEqual(by_n(self.tl)[4]["tool"], "Bash")
        self.assertEqual(set(verdicts_of(self.tl)), set(KEPT_VERDICTS))
        ids = [e["id"] for e in self.tl["events"]]
        self.assertEqual(len(ids), len(set(ids)), "event ids are not unique")

    def test_events_are_in_time_order_with_a_write_before_verdicts_of_the_same_second(self):
        times = [e["time"] for e in self.tl["events"]]
        self.assertEqual(times, sorted(times))
        ev = self.tl["events"]
        w6 = next(i for i, e in enumerate(ev) if kn(e) == 6)
        p1 = next(i for i, e in enumerate(ev) if e["kind"] == "verdict" and e["judge"] == P1)
        self.assertEqual(ev[p1]["time"], ev[w6]["time"])
        self.assertLess(w6, p1)

    def test_a_first_version_shows_its_text_and_a_later_one_a_diff_of_the_whole_file(self):
        w = by_n(self.tl)
        self.assertIsNone(w[7]["diff"])
        self.assertEqual(w[7]["text"], TEXT_A)
        for n, old, new in ((8, TEXT_A, TEXT_C), (9, TEXT_C, TEXT_B), (10, PLAN_A, PLAN_B), (11, TERMS_A, TERMS_B)):
            d = w[n]["diff"]
            self.assertTrue(d, n)
            self.assertTrue({op for op, _ in d} <= {"=", "-", "+"}, n)
            self.assertEqual(side(d, "=-"), old, f"write {n}: '=' and '-' parts are not the old text")
            self.assertEqual(side(d, "=+"), new, f"write {n}: '=' and '+' parts are not the new text")

    def test_the_diff_is_word_level(self):
        d = by_n(self.tl)[11]["diff"]
        self.assertEqual(words(d, "-"), "known")
        self.assertEqual(words(d, "+"), "explain")

    def test_a_text_write_shows_the_elements_it_changed_with_their_own_diff(self):
        w = by_n(self.tl)
        first = {p["unit"] for p in w[7]["pieces"]}
        self.assertTrue({"text:S1.e1", "text:S1.e3", "text:S2.1.e1", "text:S2.2.e1"} <= first, first)
        p = piece(w[7], "text:S1.e1")
        self.assertIsNone(p["diff"])
        self.assertIn(E1_A, p["text"])
        self.assertEqual([p["unit"] for p in w[8]["pieces"]], ["text:S2.1.e1"])
        self.assertIn("abroad", words(piece(w[8], "text:S2.1.e1")["diff"], "+"))
        self.assertEqual({p["unit"] for p in w[9]["pieces"]}, {"text:S1.e1", "text:S2.1.e1"},
                         "write 9 changed S1.e1 and brought S2.1.e1 back")
        d = piece(w[9], "text:S1.e1")["diff"]  # from S1.e1 of write 7: write 8 did not change it
        self.assertEqual(words(d, "-"), "family")
        self.assertEqual(words(d, "+"), "household")
        self.assertIn(E1_A, side(d, "=-"))
        self.assertIn(E1_B, side(d, "=+"))
        for e in (w[7], w[8], w[9]):
            for p in e["pieces"]:
                self.assertIsInstance(p["n"], int)

    def test_a_plan_write_shows_the_levels_it_changed(self):
        w = by_n(self.tl)
        self.assertEqual({p["unit"] for p in w[6]["pieces"]},
                         {"plan:level:sections", "plan:level:subsections", "plan:level:elements"})
        self.assertEqual([p["unit"] for p in w[10]["pieces"]], ["plan:level:elements"])
        d = piece(w[10], "plan:level:elements")["diff"]
        self.assertEqual(words(d, "-"), "primed")
        self.assertEqual(words(d, "+"), "full")

    def test_script_gate_outcomes_and_files_that_are_not_text(self):
        w = by_n(self.tl)
        self.assertEqual(w[8]["outcome"], "failed")
        self.assertEqual(w[8]["scripts"], [SCRIPT_LINE])
        self.assertEqual(w[8]["script_count"], 1)
        self.assertEqual(w[7]["outcome"], "passed")
        self.assertEqual(w[9]["outcome"], "passed")
        self.assertTrue(w[5]["binary"])
        self.assertIsNone(w[5]["diff"])
        self.assertEqual(w[5]["blob"], sha_name(PNG, "figures/S1.e2.png"))
        self.assertTrue(w[12]["deleted"])
        self.assertIsNone(w[12]["blob"])
        self.assertEqual(w[12]["file"], "sources/notes.md")

    def test_verdict_events_carry_the_complaint_the_gate_and_the_prompt(self):
        v = verdicts_of(self.tl)
        self.assertEqual(v[J1]["verdict"], "NOT PASSED")
        self.assertIn("«at once» is a cliché.", v[J1]["complaint"])
        self.assertEqual(v[J1]["gate"], "cliche")
        self.assertEqual(v[J1]["unit"], EL1)
        self.assertEqual(v[J1]["time"], f"{D} 10:02:30")
        self.assertEqual(v[J1]["file"], "TEXT.md")
        self.assertTrue(v[J1]["prompt"])
        self.assertFalse(v[J7]["prompt"], "a judge with no input file has no prompt to show")
        self.assertEqual(v[J2]["verdict"], "PASSED")
        self.assertEqual(v[P1]["file"], "PLAN.md")
        self.assertEqual(v[J6]["file"], "figures/S1.e2.png")
        for e in v.values():
            self.assertFalse(e["reconstructed"])

    def test_counts_per_unit_are_complaints_ever_and_failing_is_the_latest_gate_run(self):
        tl = self.tl
        u = unit_of(tl, "text:S1.e1")
        self.assertEqual((u["complaints"], u["verdicts"], u["failing"]), (2, 4, False),
                         "two complaints later fixed still count; the latest judges passed")
        self.assertEqual(unit_of(tl, "text:S1.e3")["complaints"], 1)
        self.assertTrue(unit_of(tl, "text:S1.e3")["failing"])
        self.assertTrue(unit_of(tl, "text:S2")["failing"])
        self.assertTrue(unit_of(tl, "text:S1.e2")["failing"], "the figure's judge still complains")
        self.assertEqual(unit_of(tl, "text:S1.e2")["complaints"], 2)
        self.assertEqual((unit_of(tl, "plan:S1")["complaints"], unit_of(tl, "plan:S1")["failing"]), (1, True))
        lv = unit_of(tl, "plan:level:elements")
        self.assertEqual((lv["complaints"], lv["verdicts"], lv["failing"]), (0, 2, False))
        quiet = unit_of(tl, "text:S2.2.e1")
        self.assertEqual((quiet["complaints"], quiet["verdicts"], quiet["failing"]), (0, 0, False))

    def test_units_cover_the_plan_and_the_text(self):
        keys = {u["key"] for u in self.tl["units"]}
        need = {"text:document", "text:S1", "text:S2", "text:S2.1", "text:S1.e1", "text:S1.e2", "text:S1.e3",
                "text:S2.1.e1", "text:S2.2.e1", "plan:document", "plan:level:sections", "plan:level:subsections",
                "plan:level:elements", "plan:S1", "plan:S2.1", "plan:S1.e1"}
        self.assertTrue(need <= keys, need - keys)
        for u in self.tl["units"]:
            self.assertIn(u["side"], ("plan", "text"))
            self.assertTrue(u["key"].startswith(u["side"] + ":"))
            self.assertIsInstance(u["depth"], int)

    def test_no_key_says_run(self):
        self.assertEqual(keys_with_run(self.tl), [])


# ================================================================ 3. filtering gives the history of one piece

class Filtering(unittest.TestCase):
    """Done when 2: by file, by element or plan level, by gate; a complaint later fixed stays red."""

    @classmethod
    def setUpClass(cls):
        cls.doc = kept_doc()

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def setUp(self):
        self.tl = read_timeline(self, self.doc.path)

    def of_unit(self, key: str) -> list[dict]:
        return [e for e in self.tl["events"]
                if (e["kind"] == "verdict" and key in e["units"])
                or (e["kind"] == "write" and any(p["unit"] == key for p in e["pieces"]))]

    def test_the_history_of_one_element(self):
        ev = self.of_unit("text:S1.e1")
        self.assertEqual([e["kind"] for e in ev], ["write", "verdict", "verdict", "write", "verdict", "verdict"],
                         [(e["kind"], kn(e) or e.get("judge")) for e in ev])
        self.assertEqual([kn(ev[0]), kn(ev[3])], [7, 9])
        self.assertEqual({(e["judge"], e["verdict"]) for e in ev[1:3]}, {(J1, "NOT PASSED"), (J1B, "NOT PASSED")},
                         "the complaints fixed later stay NOT PASSED")
        self.assertEqual({(e["judge"], e["verdict"]) for e in ev[4:]}, {(J2, "PASSED"), (J2B, "PASSED")})

    def test_the_history_of_one_plan_level(self):
        ev = self.of_unit("plan:level:elements")
        self.assertEqual([kn(e) for e in ev if e["kind"] == "write"], [6, 10])
        self.assertEqual({e["judge"] for e in ev if e["kind"] == "verdict"}, {P2, P3})

    def test_the_history_of_one_gate(self):
        ev = [e for e in self.tl["events"] if e["kind"] == "verdict" and e["gate"] == "cliche"]
        self.assertEqual([(e["judge"], e["verdict"]) for e in ev], [(J1, "NOT PASSED"), (J2, "PASSED")])

    def test_the_history_of_one_file(self):
        ev = [e for e in self.tl["events"] if e["file"] == "TEXT.md"]
        self.assertEqual([kn(e) for e in ev if e["kind"] == "write"], [7, 8, 9])
        self.assertEqual({e["judge"] for e in ev if e["kind"] == "verdict"}, {J1, J1B, J2, J2B, J3, J7, J8})
        self.assertEqual([kn(e) for e in self.tl["events"] if e["file"] == "sources/notes.md"], [4, 12])


# ================================================================ 4. which unit a verdict belongs to

class RemovedElement(unittest.TestCase):
    """An element of TEXT.md in one kept version and gone in the next is a piece of the later write, removed."""

    def test_an_element_gone_from_the_text_is_a_removed_piece(self):
        block = FIXTURE_TEXT.split("<!-- S1.e3 -->\n", 1)[1].split("\n", 1)[0]
        without = TEXT_A.replace(f"<!-- S1.e3 -->\n{block}\n\n", "")
        assert "S1.e3" not in without and block not in without
        doc = Doc()
        try:
            keep_by_hand(doc, [
                ("TEXT.md", f"{D} 10:00:00", TEXT_A, "Write", [], []),
                ("TEXT.md", f"{D} 10:01:00", without, "Edit", [], []),
            ])
            doc.write("TEXT.md", without, f"{D} 10:01:00")
            later = {e["time"]: e for e in writes(read_timeline(self, doc.path), "TEXT.md")}[f"{D} 10:01:00"]
            p = piece(later, "text:S1.e3")
            self.assertIs(p.get("removed"), True, p)
            self.assertNotIn("text:S1.e1", [x["unit"] for x in later["pieces"]], "an unchanged element is a piece")
        finally:
            doc.close()


class UnitsOfJudges(unittest.TestCase):
    """A judge's free-text unit goes to every element it names, a level it names, the element showing a named figure,
    else the whole plan or text."""

    CASES = {
        "element S1.e1 at TEXT.md line 6": ("TEXT.md", {"text:S1.e1"}),
        "seam S1.e2 → S1.e3 at TEXT.md line 12": ("TEXT.md", {"text:S1.e2", "text:S1.e3"}),
        "paragraph at TEXT.md line 21 (S2.1.e1)": ("TEXT.md", {"text:S2.1.e1"}),
        "section S2": ("TEXT.md", {"text:S2"}),
        "PLAN.md sections": ("PLAN.md", {"plan:level:sections"}),
        "PLAN.md sections, headings": ("PLAN.md", {"plan:level:sections"}),
        "PLAN.md elements, terms used before their explanation": ("PLAN.md", {"plan:level:elements"}),
        "PLAN.md S1": ("PLAN.md", {"plan:S1"}),
        "PLAN.md S2.1": ("PLAN.md", {"plan:S2.1"}),
        "PLAN.md, unsure sentences": ("PLAN.md", {"plan:document"}),
        "figures/S1.e2.png": ("figures/S1.e2.png", {"text:S1.e2"}),
        "term «pressure switch»": ("TEXT.md", {"text:document"}),
        "TEXT.md · somecustom": ("TEXT.md", {"text:document"}),
    }

    def test_each_unit_string_goes_to_its_units(self):
        doc = kept_doc()
        try:
            judges, verdicts = {}, {}
            for k, (unit, (rel, _)) in enumerate(self.CASES.items()):
                jid = f"custom-{k:012d}"
                judges[jid] = ("custom", unit, rel, f"# Judge input · {unit}\n")
                verdicts[jid] = ("NOT PASSED", f"complaint {k}", f"{D} 10:0{k % 10}:45")
            judge_state(doc, judges, verdicts, {})
            v = verdicts_of(read_timeline(self, doc.path))
            got = {judges[j][1]: set(v[j]["units"]) for j in judges if j in v}
            want = {unit: keys for unit, (_, keys) in self.CASES.items()}
            self.assertEqual(got, want)
        finally:
            doc.close()


# ================================================================ 5. a document made before versions were kept

RA, RB = FIXTURE_TEXT, FIXTURE_TEXT.replace(E1_A, E1_B)
JA, JB, PL = "cliche-eeeeeeeeeee1", "cliche-eeeeeeeeeee2", "one-topic-eeeeeeeeeee3"


def reconstructed_doc() -> Doc:
    """A document with no .gates/history: two versions of element S1.e1 judged (NOT PASSED, then PASSED), a TEXT.md
    write between them that failed its script gates, one PLAN.md write, and the hook's log lines of each."""
    doc = Doc()
    folder = str(doc.path)
    doc.write("BRIEF.md", BRIEF_PL, f"{D} 09:40:00")
    doc.write("GATES.md", FIXTURE_GATES, f"{D} 09:41:00")
    doc.write("TERMS.md", FIXTURE_TERMS, f"{D} 09:42:00")
    doc.write("sources/notes.md", (FIXTURE / "sources" / "notes.md").read_text(encoding="utf-8"), f"{D} 09:43:00")
    doc.write("PLAN.md", FIXTURE_PLAN, f"{D} 09:50:00")
    doc.write("TEXT.md", RB, f"{D} 10:20:00")
    sections = docs.level_text(docs.load(doc.path).plans[1])
    assert "When the pump runs" in sections
    level_input = (f"# Judge input · gate one-topic · PLAN.md sections\n\n"
                   f"## The sections of the plan (the level being checked)\n\n{sections}\n")

    def element_input(text: str) -> str:
        return (f"# Judge input · gate cliche · {EL1}\n\n## What this element is for (from the plan)\n\n"
                f"paragraph: the switch starts and stops the pump\n\n## The element's text\n\n{text}\n")

    judge_state(doc, {
        PL: ("one-topic", "PLAN.md sections", "PLAN.md", level_input),
        JA: ("cliche", EL1, "TEXT.md", element_input(E1_A)),
        JB: ("cliche", EL1, "TEXT.md", element_input(E1_B)),
    }, {
        PL: ("PASSED", "", f"{D} 09:50:30"),
        JA: ("NOT PASSED", "«at once» is a cliché.", f"{D} 10:00:30"),
        JB: ("PASSED", "", f"{D} 10:20:30"),
    }, {"PLAN.md": [PL], "TEXT.md": [JB]})
    for jid, when in ((PL, "09:50:00"), (JA, "10:00:00"), (JB, "10:20:00")):  # when each version was first judged
        p = doc.gates / "inputs" / f"{jid}.md"
        os.utime(p, (epoch(f"{D} {when}"), epoch(f"{D} {when}")))
    other = doc.tmp / "another-document"
    CACHE.mkdir(parents=True, exist_ok=True)
    with open(CACHE / "gate_run.log", "a", encoding="utf-8") as f:
        f.write(f"{D} 09:50:01 {folder} PLAN.md: 6 judges due, 0 standing\n"
                f"{D} 09:55:01 {folder} PLAN.md: 0 judges due, 0 standing\n"  # asked no judge: shows nothing
                f"{D} 10:00:01 {folder} TEXT.md: 12 judges due, 0 standing\n"
                f"{D} 10:05:00 {other} TEXT.md: 3 script failures\n"
                f"{D} 10:10:01 {folder} TEXT.md: 2 script failures\n"
                f"{D} 10:20:01 {folder} TEXT.md: 1 judges due, 0 standing\n")
    return doc


class Reconstructed(unittest.TestCase):
    """Done when 4: rebuilt from what is on disk, each rebuilt event marked; what cannot be rebuilt is listed as
    missing, never faked."""

    @classmethod
    def setUpClass(cls):
        cls.doc = reconstructed_doc()

    @classmethod
    def tearDownClass(cls):
        cls.doc.close()

    def setUp(self):
        self.tl = read_timeline(self, self.doc.path)

    def test_the_history_is_marked_reconstructed(self):
        self.assertEqual(self.tl["history"], "reconstructed")
        self.assertFalse((self.doc.gates / "history").exists(), "reading the timeline wrote a history")
        for e in writes(self.tl):
            self.assertTrue(e["reconstructed"], e)

    def test_each_log_line_of_the_folder_is_a_write_with_its_outcome(self):
        text = writes(self.tl, "TEXT.md")
        self.assertEqual([e["time"] for e in text], [f"{D} 10:00:01", f"{D} 10:10:01", f"{D} 10:20:01"],
                         "TEXT.md has log lines: its writes are those lines (not another folder's line, not an "
                         "extra write at its mtime)")
        self.assertEqual([e["outcome"] for e in text], ["passed", "failed", "passed"])
        self.assertEqual(text[1]["script_count"], 2)
        self.assertEqual([e["time"] for e in writes(self.tl, "PLAN.md")], [f"{D} 09:50:01", f"{D} 09:55:01"])

    def test_pieces_come_from_the_judges_inputs_with_their_diff(self):
        at = {e["time"]: e for e in writes(self.tl, "TEXT.md")}
        a, failed, b = (at[f"{D} {t}"] for t in ("10:00:01", "10:10:01", "10:20:01"))
        self.assertEqual([p["unit"] for p in a["pieces"]], ["text:S1.e1"])
        pa = piece(a, "text:S1.e1")
        self.assertIsNone(pa["diff"])
        self.assertEqual(pa["text"].strip(), E1_A)
        self.assertEqual(failed["pieces"], [])
        pb = piece(b, "text:S1.e1")
        self.assertEqual(words(pb["diff"], "-"), "family")
        self.assertEqual(words(pb["diff"], "+"), "household")
        self.assertEqual(pb["text"].strip(), E1_B)
        plan = {e["time"]: e for e in writes(self.tl, "PLAN.md")}[f"{D} 09:50:01"]
        self.assertEqual([p["unit"] for p in plan["pieces"]], ["plan:level:sections"])
        self.assertIn("When the pump runs", piece(plan, "plan:level:sections")["text"])

    def test_what_is_not_on_disk_is_never_faked_and_is_listed_missing(self):
        failed = {e["time"]: e for e in writes(self.tl, "TEXT.md")}[f"{D} 10:10:01"]
        self.assertIsNone(failed["text"], "the text of a write that failed its script gates is not on disk")
        self.assertIsNone(failed["diff"])
        missing = {m["file"] for m in self.tl["missing"]}
        self.assertTrue({"TEXT.md", "BRIEF.md"} <= missing, self.tl["missing"])
        for m in self.tl["missing"]:
            self.assertTrue(m["what"].strip(), m)

    def test_a_write_that_shows_nothing_of_what_it_wrote_says_so(self):
        text = {e["time"]: e for e in writes(self.tl, "TEXT.md")}
        plan = {e["time"]: e for e in writes(self.tl, "PLAN.md")}
        for e, why in ((text[f"{D} 10:10:01"], "its script gates failed"),
                       (plan[f"{D} 09:55:01"], "it asked no judge")):
            self.assertEqual(e["pieces"], [], why)
            note = e.get("note") or ""
            self.assertTrue(note.strip(), f"a write whose change is unknown ({why}) has no note")
            self.assertRegex(note, re.compile(r"not known|unknown", re.I), f"the note does not say so: {note!r}")
        for e in (text[f"{D} 10:00:01"], text[f"{D} 10:20:01"], plan[f"{D} 09:50:01"]):
            self.assertTrue(e["pieces"])
            self.assertFalse(e.get("note"), f"a write that shows its pieces has a note: {e.get('note')!r}")

    def test_every_other_file_is_one_write_at_its_mtime(self):
        for rel, when in (("BRIEF.md", "09:40:00"), ("GATES.md", "09:41:00"), ("TERMS.md", "09:42:00"),
                          ("sources/notes.md", "09:43:00")):
            ws = writes(self.tl, rel)
            self.assertEqual(len(ws), 1, rel)
            self.assertEqual(ws[0]["time"], f"{D} {when}", rel)
            self.assertEqual(ws[0]["text"], (self.doc.path / rel).read_text(encoding="utf-8"), rel)

    def test_verdicts_are_events_and_a_fixed_complaint_stays_red(self):
        v = verdicts_of(self.tl)
        self.assertEqual(v[JA]["verdict"], "NOT PASSED")
        self.assertEqual(v[JA]["time"], f"{D} 10:00:30")
        self.assertEqual(v[JA]["units"], ["text:S1.e1"])
        self.assertFalse(v[JA]["reconstructed"])
        self.assertEqual(v[JB]["verdict"], "PASSED")
        u = unit_of(self.tl, "text:S1.e1")
        self.assertEqual((u["complaints"], u["verdicts"], u["failing"]), (1, 2, False))
        times = [e["time"] for e in self.tl["events"]]
        self.assertEqual(times, sorted(times))


# ================================================================ 6. end to end: the hook, then the timeline

class HookToTimeline(unittest.TestCase):
    """Done when 1 and 3 together: what the hook keeps is what the timeline shows."""

    def setUp(self):
        self.doc = Doc()

    def tearDown(self):
        self.doc.close()

    def test_writes_kept_by_the_hook_show_with_their_verdicts(self):
        text = self.doc.path / "TEXT.md"
        self.assertIn("Script gates passed", write_call(text))
        reqs = json.loads((self.doc.gates / "requests.json").read_text())
        el = sorted(j for j, m in reqs.items() if m["unit"].startswith("element S1.e1 "))
        self.assertTrue(el, "no element judge of S1.e1 was asked for")
        verdicts = {el[0]: {"verdict": "NOT PASSED", "answer": "NOT PASSED", "text": "NOT PASSED\n- «at once» is a "
                            "cliché.", "gate": reqs[el[0]]["gate"], "unit": reqs[el[0]]["unit"],
                            "time": time.strftime(FMT)}}
        (self.doc.gates / "verdicts.json").write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        self.doc.write("TEXT.md", FIXTURE_TEXT.replace(E1_A, E1_B))
        write_call(text, "Edit")
        bash_call(f"python3 -c \"open('{self.doc.path / 'FACTS.md'}','w').write('a fact')\"", self.doc.scratch)

        tl = read_timeline(self, self.doc.path)
        self.assertEqual(tl["history"], "kept")
        files = {f["file"] for f in tl["files"]}
        self.assertTrue({"BRIEF.md", "GATES.md", "PLAN.md", "TERMS.md", "TEXT.md", "sources/notes.md",
                         "FACTS.md"} <= files, files)
        tw = writes(tl, "TEXT.md")
        self.assertEqual(len(tw), 2)
        d = piece(tw[1], "text:S1.e1")["diff"]
        self.assertEqual((words(d, "-"), words(d, "+")), ("family", "household"))
        v = verdicts_of(tl)[el[0]]
        self.assertEqual(v["verdict"], "NOT PASSED")
        self.assertEqual(v["units"], ["text:S1.e1"])
        self.assertIn("at once", v["complaint"])
        facts = writes(tl, "FACTS.md")
        self.assertEqual([(e["tool"], e["text"]) for e in facts], [("Bash", "a fact")])


# ================================================================ 7. the viewer's local server

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server(unittest.TestCase):
    """The page and its API on 127.0.0.1: documents, the timeline (live), judge prompts, kept versions, files."""

    @classmethod
    def setUpClass(cls):
        cls.doc = kept_doc()
        cls.old = reconstructed_doc()  # named only in gate_run.log
        cls.gone = cls.doc.tmp / "gone"  # no BRIEF.md
        cls.gone.mkdir()
        data = documents_json()
        data.update({str(cls.doc.path): f"{D} 10:07:00", str(cls.gone): f"{D} 09:00:00"})
        (CACHE / "documents.json").write_text(json.dumps(data), encoding="utf-8")
        with open(CACHE / "gate_run.log", "a", encoding="utf-8") as f:
            f.write(f"{D} 11:00:00 {cls.doc.tmp / 'never-existed'} TEXT.md: 1 script failures\n")
        (cls.doc.tmp / "outside.md").write_text("outside the document", encoding="utf-8")
        os.symlink(cls.doc.tmp / "outside.md", cls.doc.path / "link.md")
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, str(SERVE), "--port", str(cls.port)],
                                    env=dict(os.environ, BROWSER="true"), stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE)
        deadline = time.time() + 15
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                raise RuntimeError(f"serve.py exited: {cls.proc.stderr.read().decode()}")
            try:
                socket.create_connection(("127.0.0.1", cls.port), timeout=0.5).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("serve.py did not listen")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.proc.stderr.close()
        cls.doc.close()
        cls.old.close()

    def get(self, path: str, host: str | None = None) -> tuple[int, str, bytes]:
        status, headers, body = self.get_full(path, host)
        return status, headers.get("Content-Type", ""), body

    def get_full(self, path: str, host: str | None = None) -> tuple[int, dict, bytes]:
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            c.request("GET", path, headers={"Host": host or f"127.0.0.1:{self.port}"})
            r = c.getresponse()
            return r.status, {k.title(): v for k, v in r.getheaders()}, r.read()
        finally:
            c.close()

    def test_files_and_kept_versions_are_never_run_by_the_browser(self):
        q = urllib.parse.urlencode
        for path in (f"/api/file?{q({'folder': self.doc.path, 'file': 'TEXT.md'})}",
                     f"/api/file?{q({'folder': self.doc.path, 'file': 'figures/S1.e2.png'})}",
                     f"/api/blob?{q({'folder': self.doc.path, 'blob': sha_name(TEXT_C, 'TEXT.md')})}",
                     f"/api/blob?{q({'folder': self.doc.path, 'blob': sha_name(PNG, 'figures/S1.e2.png')})}"):
            with self.subTest(path=path.split("&")[-1]):
                status, headers, _ = self.get_full(path)
                self.assertEqual(status, 200)
                self.assertEqual(headers.get("X-Content-Type-Options", "").lower(), "nosniff")
                self.assertIn("sandbox", headers.get("Content-Security-Policy", ""))

    def api(self, route: str, **params) -> tuple[int, object]:
        status, _, body = self.get(f"/api/{route}?{urllib.parse.urlencode(params)}")
        try:
            return status, json.loads(body.decode("utf-8"))
        except ValueError:
            return status, body

    def test_only_its_own_host_is_answered(self):
        self.assertEqual(self.get("/api/documents")[0], 200)
        self.assertEqual(self.get("/api/documents", host=f"localhost:{self.port}")[0], 200)
        self.assertEqual(self.get("/api/documents", host=f"attacker.example:{self.port}")[0], 403)
        self.assertEqual(self.get("/", host="127.0.0.1:1")[0], 403)

    def test_documents_lists_folders_with_a_brief_from_the_list_and_the_log(self):
        status, docs_ = self.api("documents")
        self.assertEqual(status, 200)
        folders = {os.path.realpath(d["folder"]) for d in docs_}
        self.assertIn(str(self.doc.path), folders)
        self.assertIn(str(self.old.path), folders, "a folder named only in gate_run.log is not listed")
        self.assertNotIn(str(self.gone), folders)
        self.assertNotIn(str(self.doc.tmp / "never-existed"), folders)
        for d in docs_:
            self.assertTrue({"folder", "name", "time"} <= set(d), d)
        self.assertEqual(keys_with_run(docs_), [])

    def test_the_timeline_of_a_document(self):
        status, tl = self.api("timeline", folder=str(self.doc.path))
        self.assertEqual(status, 200)
        self.assertIn("signature", tl)
        self.assertEqual(sorted(KEPT_N.get(e["time"]) for e in tl["events"] if e["kind"] == "write"),
                         list(range(1, 13)))
        self.assertEqual(keys_with_run(tl), [])
        self.assertEqual(self.api("timeline", folder=str(self.gone))[0], 404)

    def test_a_new_verdict_shows_in_the_next_timeline(self):
        status, tl = self.api("timeline", folder=str(self.doc.path))
        self.assertEqual(status, 200)
        self.assertIsInstance(tl, dict)
        sig = tl.get("signature")
        self.assertTrue(sig, "the timeline answer has no signature")
        status, same = self.api("timeline", folder=str(self.doc.path), since=sig)
        self.assertEqual(status, 200)
        self.assertEqual(same, {"unchanged": True, "signature": sig})
        path = self.doc.gates / "verdicts.json"
        verdicts = json.loads(path.read_text(encoding="utf-8"))
        reqs = json.loads((self.doc.gates / "requests.json").read_text(encoding="utf-8"))
        jid = "cliche-fffffffffff9"
        reqs[jid] = {"gate": "cliche", "unit": EL1, "agent": "unslopable:gate-cliche", "file": str(self.doc.path / "TEXT.md")}
        verdicts[jid] = {"verdict": "NOT PASSED", "answer": "NOT PASSED", "text": "NOT PASSED\n- «a tap» is vague.",
                         "gate": "cliche", "unit": EL1, "time": f"{D} 10:08:00"}
        (self.doc.gates / "requests.json").write_text(json.dumps(reqs, ensure_ascii=False), encoding="utf-8")
        path.write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        later = time.time() + 2
        os.utime(path, (later, later))
        status, new = self.api("timeline", folder=str(self.doc.path), since=sig)
        self.assertEqual(status, 200)
        self.assertNotIn("unchanged", new)
        self.assertNotEqual(new["signature"], sig)
        self.assertIn(jid, {e.get("judge") for e in new["events"]})

    def test_a_judges_prompt(self):
        status, _, body = self.get(f"/api/input?{urllib.parse.urlencode({'folder': self.doc.path, 'id': J1})}")
        self.assertEqual(status, 200)
        self.assertIn(E1_A, body.decode("utf-8"))
        for bad in ("../requests", "inputs/x", "a/../b"):
            self.assertEqual(self.api("input", folder=str(self.doc.path), id=bad)[0], 400, bad)

    def test_a_kept_version(self):
        name = sha_name(TEXT_C, "TEXT.md")
        status, _, body = self.get(f"/api/blob?{urllib.parse.urlencode({'folder': self.doc.path, 'blob': name})}")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"), TEXT_C)
        for bad in ("../index.json", "notasha.md", "../../BRIEF.md", name.replace(".md", "/x.md")):
            self.assertEqual(self.api("blob", folder=str(self.doc.path), blob=bad)[0], 400, bad)

    def test_a_file_as_it_is_now(self):
        status, _, body = self.get(f"/api/file?{urllib.parse.urlencode({'folder': self.doc.path, 'file': 'TEXT.md'})}")
        self.assertEqual(status, 200)
        self.assertEqual(body.decode("utf-8"), TEXT_B)
        for bad in ("../outside.md", str(self.doc.tmp / "outside.md"), ".gates/verdicts.json", "link.md"):
            self.assertEqual(self.api("file", folder=str(self.doc.path), file=bad)[0], 400, bad)

    def test_the_page_never_says_run(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        html = body.decode("utf-8")
        self.assertEqual(RUN_WORD.findall(html), [], "the page still says run")
        self.assertIn("/api/documents", html)
        self.assertIn("/api/timeline", html)


if __name__ == "__main__":
    unittest.main()
