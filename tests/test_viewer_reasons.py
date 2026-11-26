"""Tests of why each kept version of a document's file was written: the `why` of every write event of the timeline
(`viewer/timeline.py`, `read_timeline`), read from the Claude Code session transcripts of the document's folder.

  SKIP_SPACY=1 python3 -m unittest tests.test_viewer_reasons -v      (system Python 3.9, as the hooks run)

A write event's `why` is None when nothing is known, else a dict:
  gates       the script gate failure lines the gate hook reported on this file's previous write in the same session
              (the numbered lines under «SCRIPT GATES — NOT PASSED (n):», without their «1. » prefix); [] when that
              hook said «Script gates passed.» or the file had no earlier write in the session
  gates_text  that hook text in full ("" when none)
  said        the assistant's own text blocks (not thinking, not tool calls, not the user's messages) after the
              previous write call of any file inside the document folder (or the session start) and before the write
              call that produced this version
  session     the transcript's session id (its file stem)

Transcripts: `<CLAUDE_CONFIG_DIR>/projects/<slug>/<session>.jsonl`, slug = the absolute folder path with every
character not in [A-Za-z0-9] replaced by "-"; the folder's own slug and the slugs of its ancestors count. Every test
here points CLAUDE_CONFIG_DIR to a temp dir (never the author's real ~/.claude). Transcript timestamps are UTC, the
history's times local: the transcripts below are written in UTC from the local times of the kept versions.

The cases, by the "done when" condition they serve:
  1. GatesAndSaid         version 2 after a version 1 whose hook failed two script gates: gates, said, gates_text
  2. EditedVersion        an Edit-produced version is matched by its content; the earlier passing hook gives []
  3. NoTranscripts        no transcripts: every write's why is None, the rest of the timeline is unchanged
  4. ParentSession        a session started in the document's parent folder counts; a sibling folder's does not
  5. ServerReasons        /api/timeline returns `why`
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import copy
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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from tests.test_viewer import (BRIEF_PL, PLAN_A, TEXT_A, TEXT_B, Doc, epoch, keep_by_hand, kept_doc,
                                   reconstructed_doc)
except ImportError:
    from test_viewer import (BRIEF_PL, PLAN_A, TEXT_A, TEXT_B, Doc, epoch, keep_by_hand, kept_doc,  # noqa: F401
                             reconstructed_doc)

ROOT = Path(__file__).resolve().parent.parent
SERVE = ROOT / "viewer" / "serve.py"
sys.path.insert(0, str(ROOT / "viewer"))
sys.path.insert(0, str(ROOT / "gates" / "lib"))

# no test of this module may read the author's real transcripts: a default for the whole module, each test sets its own
_DEFAULT_CONFIG = tempfile.mkdtemp(prefix="claude-config-")
os.environ["CLAUDE_CONFIG_DIR"] = _DEFAULT_CONFIG

D = "2026-11-25"
SID = "7b1f0c2e-4d5a-4f3e-9a10-0c1d2e3f4a5b"
SID_PARENT = "0a9b8c7d-6e5f-4a3b-8c2d-1e0f9a8b7c6d"
SID_SIBLING = "5e5e5e5e-1111-4222-8333-944444444444"

# the edit that turns TEXT_A into TEXT_B (tests/test_viewer.py: E1_B is E1_A with this one change)
OLD, NEW = "A family opens", "A household opens"
assert TEXT_A.count(OLD) == 1 and TEXT_A.replace(OLD, NEW) == TEXT_B

FAIL_LINES = [
    "[heading-no-colon-dash] TEXT.md line 1 «Pumps: how a pressure switch keeps the water coming» — a heading has a "
    "colon or a dash",
    "[heading-max-words] TEXT.md line 1 «Pumps: how a pressure switch keeps the water coming» — 12 words, at most 10",
]
HEAD = ("unslopable gates on TEXT.md (the writer). Gate results go to you because you wrote this file; fix only this "
        "file (a length miss is the exception: it goes back to the plan).\n")
# the gate hook's text as hooks/gate_run.py joins its parts
HOOK_FAIL = "\n".join([HEAD, f"SCRIPT GATES — NOT PASSED ({len(FAIL_LINES)}):\n"
                       + "".join(f"{k}. {line}\n" for k, line in enumerate(FAIL_LINES, 1))
                       + "\nFix every point in the file, then write it again; this hook runs again. The judge gates "
                         "run once the script gates pass."])
HOOK_PASS = "\n".join([HEAD, "Script gates passed. Judge gates: 5 in all, 0 passed earlier with the same input.\n",
                       "Run the gate-runner subagent on TEXT.md."])
HOOK_PLAN_FAIL = ("unslopable gates on PLAN.md (the planner). Gate results go to you because you wrote this file; "
                  "fix only this file.\n\nSCRIPT GATES — NOT PASSED (1):\n1. [plan-format] PLAN.md line 3 «S1» — an "
                  "element has no size\n\nFix every point in the file, then write it again; this hook runs again.")
OTHER_HOOK = "[agents on this machine · unslopable · 1 other session(s)]"  # another plugin's hook on the same call


# ================================================================ helpers

def slug(folder: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(folder))


def utc(local: str, shift: float = 0.0) -> str:
    """A local "%Y-%m-%d %H:%M:%S" (the history's clock) as a transcript timestamp (UTC, ISO, milliseconds)."""
    t = datetime.fromtimestamp(epoch(local) + shift, timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class Session:
    """One Claude Code session transcript, line by line in the shapes Claude Code writes. Times are local
    "%Y-%m-%d %H:%M:%S" (as the kept versions have them); `shift` moves the whole transcript's clock, in seconds."""

    def __init__(self, sid: str, cwd: Path, shift: float = 0.0):
        self.sid, self.cwd, self.shift = sid, cwd, shift
        self.lines: list[dict] = []
        self.k = 0

    def _base(self, kind: str, t: str) -> dict:
        self.k += 1
        return {"type": kind, "timestamp": utc(t, self.shift), "isSidechain": False, "sessionId": self.sid,
                "cwd": str(self.cwd), "uuid": f"{self.sid[:8]}-{self.k:04d}", "userType": "external"}

    def user(self, t: str, text: str) -> None:
        line = self._base("user", t)
        line["message"] = {"role": "user", "content": text}
        self.lines.append(line)

    def say(self, t: str, text: str) -> None:
        line = self._base("assistant", t)
        line["message"] = {"role": "assistant", "content": [{"type": "text", "text": text}]}
        self.lines.append(line)

    def think(self, t: str, text: str) -> None:
        line = self._base("assistant", t)
        line["message"] = {"role": "assistant", "content": [{"type": "thinking", "thinking": text, "signature": "x"}]}
        self.lines.append(line)

    def tool(self, t: str, name: str, tool_input: dict, done: str, result: str = "ok",
             use_result: dict | None = None, hooks: list[str] | None = None) -> str:
        """A tool call at `t`, its result at `done` and the PostToolUse hook outputs after it; returns its id."""
        self.k += 1
        tid = f"toolu_{self.sid[:6]}{self.k:04d}"
        line = self._base("assistant", t)
        line["message"] = {"role": "assistant",
                           "content": [{"type": "tool_use", "id": tid, "name": name, "input": tool_input}]}
        self.lines.append(line)
        line = self._base("user", done)
        line["message"] = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tid, "content": result}]}
        if use_result is not None:
            line["toolUseResult"] = use_result
        self.lines.append(line)
        for text in hooks or []:
            line = self._base("attachment", done)
            line["attachment"] = {"type": "hook_additional_context", "content": [text], "hookName": f"PostToolUse:{name}",
                                  "toolUseID": tid, "hookEvent": "PostToolUse"}
            self.lines.append(line)
        return tid

    def write(self, t: str, path: Path, content: str, hook: str | None, done: str | None = None,
              result_content: str | None = None) -> str:
        """A Write of `path`; `result_content` is what Claude Code reports as written (default `content`)."""
        return self.tool(t, "Write", {"file_path": str(path), "content": content}, done or t,
                         f"The file {path} has been updated successfully.",
                         {"type": "update", "filePath": str(path),
                          "content": content if result_content is None else result_content,
                          "structuredPatch": [], "originalFile": None},
                         [OTHER_HOOK] + ([hook] if hook is not None else []))

    def edit(self, t: str, path: Path, old: str, new: str, original: str, hook: str | None,
             done: str | None = None) -> str:
        return self.tool(t, "Edit", {"file_path": str(path), "old_string": old, "new_string": new,
                                     "replace_all": False}, done or t,
                         f"The file {path} has been updated successfully.",
                         {"filePath": str(path), "oldString": old, "newString": new, "originalFile": original,
                          "structuredPatch": [], "userModified": False, "replaceAll": False},
                         [OTHER_HOOK] + ([hook] if hook is not None else []))

    def save(self, config: Path, folder: Path, tail: str = "") -> Path:
        """Writes the transcript under the slug of `folder`; `tail` is appended raw (a line still being written)."""
        d = config / "projects" / slug(folder)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{self.sid}.jsonl"
        p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in self.lines) + tail, encoding="utf-8")
        return p


def timeline_of(test: unittest.TestCase, folder: Path) -> dict:
    try:
        import timeline
    except ImportError as e:
        test.fail(f"viewer/timeline.py cannot be imported: {e}")
    return timeline.read_timeline(folder)


def writes(tl: dict, file: str | None = None) -> list[dict]:
    return [e for e in tl["events"] if e["kind"] == "write" and (file is None or e["file"] == file)]


def version(test: unittest.TestCase, tl: dict, file: str, n: int) -> dict:
    found = [e for e in writes(tl, file) if e["n"] == n]
    test.assertEqual(len(found), 1, f"no single write event {file} #{n}: {[(e['file'], e['n']) for e in writes(tl)]}")
    return found[0]


def why(test: unittest.TestCase, e: dict) -> dict:
    """The `why` of a write event, asserted to be a dict with its four keys."""
    test.assertIn("why", e, f"write event {e['file']} #{e['n']} has no key `why`")
    w = e["why"]
    test.assertIsInstance(w, dict, f"write event {e['file']} #{e['n']}: why is {w!r}, a dict was expected")
    test.assertEqual(set(w) & {"gates", "gates_text", "said", "session"}, {"gates", "gates_text", "said", "session"},
                     f"why lacks a key: {sorted(w)}")
    return w


class ConfigCase(unittest.TestCase):
    """A test with its own CLAUDE_CONFIG_DIR and its own document."""

    def setUp(self):
        self.config = Path(tempfile.mkdtemp(prefix="claude-config-")).resolve()
        self._old = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.config)
        self.docs: list[Doc] = []

    def tearDown(self):
        if self._old is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._old
        shutil.rmtree(self.config, ignore_errors=True)
        for d in self.docs:
            d.close()

    def doc(self, entries: list[tuple]) -> Doc:
        """A document whose kept versions are `entries` (file, local time, content, tool); the last version of each
        file is on disk with that time as its mtime."""
        doc = Doc()
        self.docs.append(doc)
        keep_by_hand(doc, [(rel, t, content, tool, [], []) for rel, t, content, tool in entries])
        last = {rel: (t, content) for rel, t, content, _ in entries}
        for rel, (t, content) in last.items():
            doc.write(rel, content, t)
        return doc


# ================================================================ 1. gates and what was said between two writes

SAID_START = "I write the first section of the text now."
SAID_1 = "The H1 is optional, so I drop the colon and keep the heading short."
SAID_2 = "Now the heading has nine words and no colon."
SAID_AFTER = "Both script gates pass now."


class GatesAndSaid(ConfigCase):
    """Done when 1: version 2 of TEXT.md, written after a version 1 whose gate hook reported two script failures, has
    why.gates == those two lines and why.said == the assistant's text written between the two writes."""

    def scenario(self) -> Doc:
        doc = self.doc([("BRIEF.md", f"{D} 09:00:00", BRIEF_PL, "Write"),
                        ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write"),
                        ("TEXT.md", f"{D} 10:04:00", TEXT_B, "Write")])
        text = doc.path / "TEXT.md"
        s = Session(SID, doc.path)
        s.user(f"{D} 10:01:00", "Write the text of the document.")
        s.say(f"{D} 10:01:05", SAID_START)
        s.write(f"{D} 10:02:00", text, TEXT_A, HOOK_FAIL, done=f"{D} 10:02:01")
        s.think(f"{D} 10:02:10", "The heading is too long; this thinking is not said.")
        s.say(f"{D} 10:02:20", SAID_1)
        s.tool(f"{D} 10:02:30", "Read", {"file_path": str(text)}, f"{D} 10:02:31", TEXT_A)
        s.user(f"{D} 10:02:40", "Keep going.")
        s.say(f"{D} 10:02:50", SAID_2)
        s.write(f"{D} 10:04:00", text, TEXT_B, HOOK_PASS, done=f"{D} 10:04:01")
        s.say(f"{D} 10:04:10", SAID_AFTER)
        s.save(self.config, doc.path)
        return doc

    def test_version_2_has_the_two_failures_of_version_1_and_what_was_said_between(self):
        doc = self.scenario()
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["gates"], FAIL_LINES)
        self.assertEqual(w["said"], [SAID_1, SAID_2], "said holds only the assistant's text blocks between the writes")
        self.assertEqual(w["gates_text"], HOOK_FAIL, "gates_text is the gate hook's text in full, no other hook's")
        self.assertEqual(w["session"], SID)

    def test_version_1_has_no_earlier_write_so_no_gates_and_what_was_said_since_the_session_began(self):
        doc = self.scenario()
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 1))
        self.assertEqual(w["gates"], [])
        self.assertEqual(w["gates_text"], "")
        self.assertEqual(w["said"], [SAID_START])
        self.assertEqual(w["session"], SID)

    def test_a_version_no_call_of_the_transcript_wrote_has_why_none(self):
        doc = self.scenario()  # BRIEF.md: kept at 09:00, the session starts at 10:01 and never writes it
        e = version(self, timeline_of(self, doc.path), "BRIEF.md", 1)
        self.assertIn("why", e)
        self.assertIsNone(e["why"])

    def test_said_restarts_at_a_write_of_another_file_of_the_document_but_gates_stay_those_of_the_same_file(self):
        doc = self.doc([("BRIEF.md", f"{D} 09:00:00", BRIEF_PL, "Write"),
                        ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write"),
                        ("PLAN.md", f"{D} 10:03:00", PLAN_A, "Write"),
                        ("TEXT.md", f"{D} 10:05:00", TEXT_B, "Write")])
        outside = doc.scratch / "notes.md"  # beside the document, not in it: its write restarts nothing
        s = Session(SID, doc.path)
        s.write(f"{D} 10:02:00", doc.path / "TEXT.md", TEXT_A, HOOK_FAIL, done=f"{D} 10:02:01")
        s.say(f"{D} 10:02:20", "Before the plan changes.")
        s.write(f"{D} 10:03:00", doc.path / "PLAN.md", PLAN_A, HOOK_PLAN_FAIL, done=f"{D} 10:03:01")
        s.say(f"{D} 10:03:20", SAID_1)
        s.write(f"{D} 10:03:40", outside, "scratch notes", None, done=f"{D} 10:03:41")
        s.say(f"{D} 10:04:00", SAID_2)
        s.write(f"{D} 10:05:00", doc.path / "TEXT.md", TEXT_B, HOOK_PASS, done=f"{D} 10:05:01")
        s.save(self.config, doc.path)
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["said"], [SAID_1, SAID_2])
        self.assertEqual(w["gates"], FAIL_LINES, "the gates are those of TEXT.md's previous write, not PLAN.md's")
        self.assertEqual(w["gates_text"], HOOK_FAIL)

    def test_a_transcript_still_being_written_is_read_up_to_its_last_whole_line(self):
        doc = self.scenario()
        s = Session(SID, doc.path)  # the same session file, rewritten with a last line cut in the middle
        s.say(f"{D} 10:01:05", SAID_START)
        s.write(f"{D} 10:02:00", doc.path / "TEXT.md", TEXT_A, HOOK_FAIL, done=f"{D} 10:02:01")
        s.say(f"{D} 10:02:20", SAID_1)
        s.write(f"{D} 10:04:00", doc.path / "TEXT.md", TEXT_B, HOOK_PASS, done=f"{D} 10:04:01")
        s.save(self.config, doc.path, tail='{"type":"assistant","timestamp":"2026-11-25T')
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["gates"], FAIL_LINES)
        self.assertEqual(w["said"], [SAID_1])


# ================================================================ 2. a version an Edit produced

SAID_EDIT = "«A family» reads as a cliché opening; «A household» is plainer."


class EditedVersion(ConfigCase):
    """Done when 2: an Edit-produced version is matched by its content (originalFile with old_string replaced by
    new_string) and its why.said holds the text between the previous write and the edit; the earlier write's passing
    hook gives why.gates == []."""

    def scenario(self, shift: float = 0.0) -> Doc:
        doc = self.doc([("BRIEF.md", f"{D} 09:00:00", BRIEF_PL, "Write"),
                        ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write"),
                        ("TEXT.md", f"{D} 10:03:00", TEXT_B, "Edit")])
        text = doc.path / "TEXT.md"
        s = Session(SID, doc.path, shift=shift)
        s.write(f"{D} 10:02:00", text, TEXT_A, HOOK_PASS, done=f"{D} 10:02:01")
        s.say(f"{D} 10:02:30", SAID_EDIT)
        s.edit(f"{D} 10:03:00", text, OLD, NEW, TEXT_A, HOOK_PASS, done=f"{D} 10:03:01")
        s.save(self.config, doc.path)
        return doc

    def test_the_edited_version_is_matched_and_the_earlier_passing_hook_gives_no_gates(self):
        doc = self.scenario()
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["gates"], [])
        self.assertEqual(w["gates_text"], HOOK_PASS)
        self.assertEqual(w["said"], [SAID_EDIT])
        self.assertEqual(w["session"], SID)

    def test_the_edit_is_matched_by_content_when_the_clocks_disagree(self):
        # the transcript's clock is 90 s ahead of the files' mtimes: no version falls in a call's time window, so
        # only the content (originalFile with old_string replaced by new_string) can match the edit
        doc = self.scenario(shift=90)
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["said"], [SAID_EDIT])
        self.assertEqual(w["gates_text"], HOOK_PASS)

    def test_a_version_whose_content_matches_no_call_is_matched_by_its_time(self):
        # what is on disk after the second Write differs from what the call wrote (changed right after it): only its
        # mtime, within the call's time window (UTC in the transcript, local in the history), ties it to the call
        changed = TEXT_B + "\n"
        doc = self.doc([("BRIEF.md", f"{D} 09:00:00", BRIEF_PL, "Write"),
                        ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write"),
                        ("TEXT.md", f"{D} 10:04:01", changed, "Write")])
        s = Session(SID, doc.path)
        s.write(f"{D} 10:02:00", doc.path / "TEXT.md", TEXT_A, HOOK_FAIL, done=f"{D} 10:02:01")
        s.say(f"{D} 10:03:00", SAID_1)
        s.write(f"{D} 10:04:00", doc.path / "TEXT.md", TEXT_B, HOOK_PASS, done=f"{D} 10:04:02")
        s.save(self.config, doc.path)
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["gates"], FAIL_LINES)
        self.assertEqual(w["said"], [SAID_1])


# ================================================================ 3. no transcripts

def _without_why(tl: dict) -> dict:
    out = copy.deepcopy({k: tl[k] for k in ("history", "files", "units", "gates", "events", "missing")})
    for e in out["events"]:
        e.pop("why", None)
    return out


# the keys a write event had before `why` (viewer/timeline.py _write_event; `cut` only with a first version's text)
WRITE_KEYS = {"id", "kind", "time", "file", "n", "reconstructed", "tool", "diff", "text", "binary", "blob", "deleted",
              "pieces", "scripts", "script_count", "outcome", "gated", "note", "same"}


class NoTranscripts(ConfigCase):
    """Done when 3: a document with no transcripts at all: every write event has why None, and the rest of the
    timeline is the same as with transcripts (same events, same keys)."""

    def setUp(self):
        super().setUp()
        self.kept = kept_doc()
        self.docs.append(self.kept)

    def test_every_write_of_a_kept_document_has_why_none(self):
        ws = writes(timeline_of(self, self.kept.path))
        self.assertEqual(len(ws), 12)
        for e in ws:
            with self.subTest(file=e["file"], n=e["n"]):
                self.assertIn("why", e)
                self.assertIsNone(e["why"])
                self.assertEqual(set(e) - {"cut", "why"}, WRITE_KEYS)

    def test_every_write_of_a_reconstructed_document_has_why_none(self):
        old = reconstructed_doc()
        self.docs.append(old)
        ws = writes(timeline_of(self, old.path))
        self.assertTrue(ws)
        for e in ws:
            with self.subTest(id=e["id"]):
                self.assertIn("why", e)
                self.assertIsNone(e["why"])

    def test_transcripts_change_nothing_of_the_timeline_but_why(self):
        bare = timeline_of(self, self.kept.path)
        s = Session(SID, self.kept.path)  # kept_doc: TEXT.md versions A (10:02), C (10:03), B (10:04)
        s.write("2026-11-20 10:02:00", self.kept.path / "TEXT.md", TEXT_A, HOOK_PASS, done="2026-11-20 10:02:01")
        s.say("2026-11-20 10:03:30", SAID_EDIT)
        s.write("2026-11-20 10:04:00", self.kept.path / "TEXT.md", TEXT_B, HOOK_PASS, done="2026-11-20 10:04:01")
        s.save(self.config, self.kept.path)
        told = timeline_of(self, self.kept.path)
        self.assertTrue(any(isinstance(e.get("why"), dict) for e in writes(told)),
                        "the transcript gave no write a why: this comparison would prove nothing")
        self.assertEqual(_without_why(told), _without_why(bare))


# ================================================================ 4. a session started in a parent folder

class ParentSession(ConfigCase):
    """Done when 4: a transcript under the slug of the document's parent folder (a session started there) is used
    too; one under a sibling folder's slug is not."""

    def scenario(self, where) -> Doc:
        doc = self.doc([("BRIEF.md", f"{D} 09:00:00", BRIEF_PL, "Write"),
                        ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write"),
                        ("TEXT.md", f"{D} 10:04:00", TEXT_B, "Write")])
        cwd = where(doc)
        s = Session(SID_PARENT if cwd == doc.tmp else SID_SIBLING, cwd)
        s.write(f"{D} 10:02:00", doc.path / "TEXT.md", TEXT_A, HOOK_FAIL, done=f"{D} 10:02:01")
        s.say(f"{D} 10:03:00", SAID_1)
        s.write(f"{D} 10:04:00", doc.path / "TEXT.md", TEXT_B, HOOK_PASS, done=f"{D} 10:04:01")
        s.save(self.config, cwd)
        return doc

    def test_a_session_started_in_the_parent_folder_counts(self):
        doc = self.scenario(lambda d: d.tmp)
        w = why(self, version(self, timeline_of(self, doc.path), "TEXT.md", 2))
        self.assertEqual(w["gates"], FAIL_LINES)
        self.assertEqual(w["said"], [SAID_1])
        self.assertEqual(w["session"], SID_PARENT)

    def test_a_session_of_a_sibling_folder_does_not_count(self):
        doc = self.scenario(lambda d: d.scratch)
        for e in writes(timeline_of(self, doc.path)):
            with self.subTest(file=e["file"], n=e["n"]):
                self.assertIn("why", e)
                self.assertIsNone(e["why"])


# ================================================================ 5. the server

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerReasons(ConfigCase):
    """Done when 5: /api/timeline of viewer/serve.py returns the `why` of each write event."""

    def test_api_timeline_returns_why(self):
        doc = self.doc([("BRIEF.md", f"{D} 09:00:00", BRIEF_PL, "Write"),
                        ("TEXT.md", f"{D} 10:02:00", TEXT_A, "Write"),
                        ("TEXT.md", f"{D} 10:04:00", TEXT_B, "Write")])
        s = Session(SID, doc.path)
        s.write(f"{D} 10:02:00", doc.path / "TEXT.md", TEXT_A, HOOK_FAIL, done=f"{D} 10:02:01")
        s.say(f"{D} 10:03:00", SAID_1)
        s.write(f"{D} 10:04:00", doc.path / "TEXT.md", TEXT_B, HOOK_PASS, done=f"{D} 10:04:01")
        s.save(self.config, doc.path)
        port = free_port()
        proc = subprocess.Popen([sys.executable, str(SERVE), "--port", str(port)],
                                env=dict(os.environ, BROWSER="true", CLAUDE_CONFIG_DIR=str(self.config)),
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                if proc.poll() is not None:
                    self.fail(f"serve.py exited: {proc.stderr.read().decode()}")
                try:
                    socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("serve.py did not listen")
            url = f"http://127.0.0.1:{port}/api/timeline?{urllib.parse.urlencode({'folder': str(doc.path)})}"
            with urllib.request.urlopen(url, timeout=60) as r:
                tl = json.loads(r.read().decode("utf-8"))
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            proc.stderr.close()
        w = why(self, version(self, tl, "TEXT.md", 2))
        self.assertEqual(w["gates"], FAIL_LINES)
        self.assertEqual(w["said"], [SAID_1])
        self.assertIsNone(version(self, tl, "BRIEF.md", 1)["why"])


if __name__ == "__main__":
    unittest.main()
