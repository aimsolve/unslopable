"""Tests of the gate mechanism: the plan list parser, every script gate, the judge requests, the hook fed with
recorded PostToolUse JSON, and the verdict collector fed with fake subagent transcripts.

The plan is one file, PLAN.md: a nested markdown list, one item per line, fields separated by ` · `
(README «Provisional», bullets Files / The plan / Levels / Text / Return to the plan / Plan approval stand-in).

  python3 -m unittest discover -s tests -v          (system Python 3.9, as the hooks run)
  SKIP_SPACY=1 python3 -m unittest …                skips the spaCy tests (they run uv, ~5 s each)
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gates" / "scripts"))
sys.path.insert(0, str(ROOT / "gates" / "lib"))

import docs  # noqa: E402
import judge_gates as jg  # noqa: E402
import cohesion  # noqa: E402
import common  # noqa: E402
import dates  # noqa: E402
import formats  # noqa: E402
import leftover_markers  # noqa: E402
import links  # noqa: E402
import list_lead_in  # noqa: E402
import no_compound  # noqa: E402
import no_document_talk  # noqa: E402
import no_hedging  # noqa: E402
import no_number_reference  # noqa: E402
import no_repetition  # noqa: E402
import no_semicolon  # noqa: E402
import no_truncated  # noqa: E402
import one_sentence_per_item  # noqa: E402
import out_of_scope  # noqa: E402
import plan_elements_written  # noqa: E402
import run_scripts  # noqa: E402
import sentence_max_words  # noqa: E402
import slop_words  # noqa: E402
import table_duplicate_row  # noqa: E402
import table_flat  # noqa: E402
import table_footnote  # noqa: E402
import tense_shift  # noqa: E402
import term_counts  # noqa: E402
import term_first_use  # noqa: E402
import term_marked  # noqa: E402
import term_order  # noqa: E402
import text_length  # noqa: E402
import yes_no_grid  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "doc"
HOOK = ROOT / "hooks" / "gate_run.py"
COLLECT = ROOT / "hooks" / "collect_judges.py"
RECORDED = ROOT / "tests" / "fixtures" / "hook_posttooluse_write.json"
NO_SPACY = os.environ.get("SKIP_SPACY") == "1"

LEVEL_NAMES = {1: "sections", 2: "subsections", 3: "elements"}


def approval_line(level_name: str, date: str = "2026-11-19") -> str:
    """The approval line the fixture PLAN.md carries for one level."""
    return f"Approved {level_name} by plan-approver for Test Author, {date}"


def fixture_plan(*unapproved: str) -> str:
    """The fixture PLAN.md with the approval lines of the named levels taken out."""
    text = (FIXTURE / "PLAN.md").read_text(encoding="utf-8")
    for name in unapproved:
        line = approval_line(name) + "\n\n"
        assert line in text, name
        text = text.replace(line, "")
    return text


def with_approval(plan: str, level_name: str, date: str = "2026-11-19") -> str:
    """`plan` with the approval line of one level added on its own line at the top."""
    return approval_line(level_name, date) + "\n\n" + plan


class Folder:
    """A copy of the fixture document in a temp dir, with files overridden.

    Folder(PLAN="…") writes PLAN.md; Folder(**{"TEXT.md": "…"}) writes any file; a value of None removes the file.
    Bodies are dedented, so they can be indented in the test."""

    def __init__(self, **files: str | None):
        self.tmp = tempfile.mkdtemp()
        self.path = Path(self.tmp) / "doc"
        shutil.copytree(FIXTURE, self.path, ignore=shutil.ignore_patterns(".*"))  # no state a live hook left
        for name, body in files.items():
            fname = "PLAN.md" if name == "PLAN" else name
            if body is None:
                (self.path / fname).unlink()
            else:
                (self.path / fname).write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")

    def doc(self):
        return docs.load(self.path)

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def gates_of(fs):
    return [f.gate for f in fs]


def polish_brief() -> str:
    """The fixture brief in Polish: the spaCy compound gate then does not run, so run_text needs no uv."""
    return (FIXTURE / "BRIEF.md").read_text().replace("English.", "Polish.")


def read_plan(body: str):
    return docs.read_plan(textwrap.dedent(body).lstrip("\n"))


# A small plan that is valid as a list: every case in PlanFormat is this plan with one thing broken.
VALID = """
    # Plan

    - S1 · **When it runs** · when the pump starts and stops · 10 lines
      - S1.e1 · paragraph · the switch starts and stops the pump · facts: F1, F2 · 6 lines
      - S1.e2 · figure · the path of the water · 4 lines
    - S2 · **Settings** · the settings worth changing · 10 lines
      - S2.1 · **Low water cutoff** · when to turn it off · 10 lines
        - S2.1.e1 · paragraph · the cutoff stops the pump on a low well · facts: F3 · 10 lines
    """


class Parsing(unittest.TestCase):
    def test_sentences_keep_abbreviations(self):
        s = docs.split_sentences("The pump fills it, e.g. a tank. Then it stops! Does it? Yes.")
        self.assertEqual(s, ["The pump fills it, e.g. a tank.", "Then it stops!", "Does it?", "Yes."])

    def test_plain_and_words(self):
        self.assertEqual(docs.plain("**Bold** [link text](http://x) `code`"), "Bold link text code")
        self.assertEqual(len(docs.words("Ann's built-in valve, v2.")), 4)

    def test_config_terms(self):
        self.assertEqual(docs.read_config("- a_b: 12\nnot: a key\nc: x y")["a_b"], "12")
        t = docs.read_terms("- check valve — explain — keeps the pump primed\n- tap - known\n* **PSI** — explain (acronym)\nDIN 1988 — link — a plumbing standard")
        self.assertEqual(t, {"check valve": "explain", "tap": "known", "PSI": "explain", "DIN 1988": "link"})

    def test_terms_two_lists_under_headings(self):
        # new form: two bulleted lists under headings; `(link)` marks a known term linked at first mention
        t = docs.read_terms(
            "# Terms\n\nApproved by the author.\n- not a term — the intro is not under a list heading\n\n"
            "## Known\n\n- pump — moves water from the well to the tank\n"
            "- **pressure gauge** (link) — shows the pressure — https://example.org/gauge\n* `PSI`\n\n"
            "## Explain\n\n- dry run — the pump turning with no water; known as a seal killer\n"
            "- check valve - lets water flow one way only\n- relief valve (link) — link means nothing here\n\n"
            "## Notes\n\n- tank — not a term, its heading is neither list\n")
        self.assertEqual(t, {"pump": "known", "pressure gauge": "link", "PSI": "known", "dry run": "explain",
                             "check valve": "explain", "relief valve": "explain"})

    def test_terms_old_line_form_still_read(self):
        # documents written before 23.11 keep the old one-line form
        t = docs.read_terms("# Terms\n\nDecided by the brief.\n\npump — known\nvalve — link — a source link\n"
                            "dry run — explain — the pump turning with no water\n")
        self.assertEqual(t, {"pump": "known", "valve": "link", "dry run": "explain"})

    def test_one_plan_file_three_levels(self):
        # condition 1: one PLAN.md replaces PLAN-1/2/3.md
        self.assertEqual(docs.PLAN_FILE, "PLAN.md")
        self.assertEqual(docs.LEVELS, {1: "sections", 2: "subsections", 3: "elements"})

    def test_fixture_plan_and_text(self):
        d = docs.load(FIXTURE)
        self.assertEqual(d.plan_problems, [])
        self.assertEqual([r.id for r in d.plans[1]], ["S1", "S2"])
        self.assertEqual([r.id for r in d.plans[2]], ["S2.1", "S2.2"])
        self.assertEqual([r.id for r in d.plans[3]], ["S1.e1", "S1.e2", "S1.e3", "S2.1.e1", "S2.2.e1"])
        self.assertEqual(d.plans[3][0].lines, 4)
        self.assertEqual(d.section_of("S2.2.e1"), "S2")
        self.assertEqual(d.plan_row("S2.2.e1").get("parent"), "S2.2")
        self.assertEqual(d.plan_row("S2.1").get("parent"), "S2")
        self.assertEqual(d.plan_row("S1").get("parent"), "")
        kinds = [b.kind for b in d.text.blocks]
        self.assertEqual(kinds, ["paragraph", "figure", "paragraph", "paragraph", "paragraph", "list"])
        self.assertEqual(d.text.unmarked, [])

    def test_item_fields(self):
        rows, probs = read_plan(VALID)
        self.assertEqual(probs, [])
        self.assertEqual(sorted(rows), [1, 2, 3])
        s1 = rows[1][0]
        self.assertEqual((s1.level, s1.id), (1, "S1"))
        self.assertEqual(docs.plain(s1.get("heading")), "When it runs")  # the bold marks a heading item
        self.assertEqual(s1.get("covers"), "when the pump starts and stops")
        self.assertEqual(s1.lines, 10)
        sub = rows[2][0]
        self.assertEqual((sub.level, sub.id, sub.get("parent")), (2, "S2.1", "S2"))
        self.assertEqual(docs.plain(sub.get("heading")), "Low water cutoff")
        e1, e2, e3 = rows[3]
        self.assertEqual((e1.level, e1.id, e1.get("parent")), (3, "S1.e1", "S1"))
        self.assertEqual(e1.get("kind"), "paragraph")
        self.assertEqual(e1.get("says"), "the switch starts and stops the pump")
        self.assertEqual([x.strip() for x in e1.get("facts").split(",")], ["F1", "F2"])  # no `facts:` prefix
        self.assertEqual(e1.lines, 6)
        self.assertEqual((e2.get("kind"), e2.get("facts"), e2.lines), ("figure", "", 4))  # facts: left out
        self.assertEqual(e3.get("parent"), "S2.1")

    def test_lines_outside_the_list_are_not_plan(self):
        rows, probs = read_plan("""
            Approved sections by x, 2026-11-19 03:00

            # Plan

            A note on the plan, not an item.

            - S1 · **Who sees data** · who can see · 10 lines
            """)
        self.assertEqual(probs, [])
        self.assertEqual([r.id for r in rows[1]], ["S1"])
        self.assertEqual((rows[2], rows[3]), ([], []))

    def test_empty_plan_has_every_level(self):
        rows, _ = docs.read_plan("")
        self.assertEqual(rows, {1: [], 2: [], 3: []})

    def test_folder_without_plan(self):
        f = Folder(PLAN=None)
        try:
            d = f.doc()
            self.assertEqual(d.plans, {1: [], 2: [], 3: []})
            self.assertEqual(d.plan_problems, [])
        finally:
            f.close()

    def test_doc_folder(self):
        self.assertEqual(docs.doc_folder(str(FIXTURE / "PLAN.md")), (FIXTURE, "plan"))
        self.assertEqual(docs.doc_folder(str(FIXTURE / "TEXT.md")), (FIXTURE, "text"))
        self.assertIsNone(docs.doc_folder(str(FIXTURE / "GATES.md")))
        self.assertIsNone(docs.doc_folder(str(FIXTURE / "PLAN-1.md")))  # the old names are no plan any more
        self.assertIsNone(docs.doc_folder(str(FIXTURE / "PLAN-3.md")))
        self.assertIsNone(docs.doc_folder("/tmp/nowhere/PLAN.md"))


class PlanFormat(unittest.TestCase):
    """Condition 2: the parser reads the list without guessing and names every format problem.

    Each case is VALID with one thing broken; VALID itself has no problems, so any problem comes from the break.
    A problem names the item id or `line N` (1-based line of the dedented text)."""

    def assertProblem(self, probs, ids=(), lines=()):
        self.assertTrue(probs, "no format problem reported")
        pats = [rf"(?<![\w.]){re.escape(i)}(?![\w]|\.\w)" for i in ids] + [rf"\bline {n}\b" for n in lines]
        self.assertTrue(any(re.search(p, x) for p in pats for x in probs), f"{probs} names none of {ids} {lines}")

    def test_valid_has_no_problems(self):
        self.assertEqual(read_plan(VALID)[1], [])

    def test_item_without_size(self):
        _, probs = read_plan("""
            - S1 · **When it runs** · when the pump starts and stops
            """)
        self.assertProblem(probs, ["S1"], [1])

    def test_item_size_not_a_number(self):
        _, probs = read_plan("""
            - S1 · **When it runs** · when the pump starts and stops · ten lines
            """)
        self.assertProblem(probs, ["S1"], [1])

    def test_element_without_size(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump · facts: F1
            """)
        self.assertProblem(probs, ["S1.e1"], [2])

    def test_heading_item_under_subsection(self):
        _, probs = read_plan("""
            - S2 · **Settings** · the settings worth changing · 10 lines
              - S2.1 · **Low water cutoff** · when to turn it off · 10 lines
                - S2.1.1 · **Deeper heading** · a third heading level · 10 lines
            """)
        self.assertProblem(probs, ["S2.1.1"], [3])

    def test_heading_item_under_element(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump · 10 lines
                - S1.e1.h · **A heading** · under an element · 10 lines
            """)
        self.assertProblem(probs, ["S1.e1.h"], [3])

    def test_element_at_top_level(self):
        _, probs = read_plan("""
            - S0 · paragraph · an introduction · 2 lines
            - S1 · **Who sees data** · who can see · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump · 10 lines
            """)
        self.assertProblem(probs, ["S0"], [1])

    def test_item_under_element(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump · 10 lines
                - S1.e1.e1 · paragraph · a nested element · 10 lines
            """)
        self.assertProblem(probs, ["S1.e1.e1", "S1.e1"], [3])

    def test_section_with_subsections_and_own_elements(self):
        _, probs = read_plan("""
            - S2 · **Settings** · the settings worth changing · 10 lines
              - S2.1 · **Low water cutoff** · when to turn it off · 5 lines
                - S2.1.e1 · paragraph · the cutoff stops the pump on a low well · 5 lines
              - S2.e1 · paragraph · text outside any subsection · 5 lines
            """)
        self.assertProblem(probs, ["S2", "S2.e1"], [1, 4])

    def test_duplicate_id(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump · 10 lines
            - S1 · **Settings** · the settings worth changing · 10 lines
              - S1.e2 · paragraph · the cutoff stops the pump on a low well · 10 lines
            """)
        self.assertProblem(probs, ["S1"], [3])

    def test_duplicate_id_across_levels(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              - S1 · paragraph · the switch starts and stops the pump · 10 lines
            """)
        self.assertProblem(probs, ["S1"], [2])

    def test_item_continued_on_next_line(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              and what the pump does in winter
              - S1.e1 · paragraph · the switch starts and stops the pump · 10 lines
            """)
        self.assertProblem(probs, ["S1"], [2])

    def test_element_fourth_field_not_facts(self):
        _, probs = read_plan("""
            - S1 · **Who sees data** · who can see · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump · F1, F2 · 10 lines
            """)
        self.assertProblem(probs, ["S1.e1"], [2])

    def test_problems_reach_run_plan_as_format(self):
        f = Folder(PLAN="""
            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
            - S1 · **Settings that protect the pump** · the settings worth changing · 10 lines
            """)
        try:
            self.assertTrue(f.doc().plan_problems)
            fs = run_scripts.run_plan(f.doc(), 1)
            self.assertIn(("format", "PLAN.md"), {(x.gate, x.where) for x in fs})
        finally:
            f.close()


class FixturePasses(unittest.TestCase):
    def test_plan_levels_pass(self):
        d = docs.load(FIXTURE)
        for lvl in (1, 2, 3):
            self.assertTrue(d.plans[lvl], lvl)  # the level is read, so passing means something
            self.assertEqual([x.line() for x in run_scripts.run_plan(d, lvl)], [], lvl)

    def test_text_passes_without_spacy(self):
        # the fixture TEXT.md passes every text gate against PLAN.md (the spaCy gate is off for a Polish brief)
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            notes = []
            fails, _ = run_scripts.run_text(f.doc(), notes)
            self.assertEqual([x.line() for x in fails], [])
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "spaCy")
    def test_text_passes(self):
        notes = []
        fails, cands = run_scripts.run_text(docs.load(FIXTURE), notes)
        self.assertEqual([f.line() for f in fails], [])
        self.assertEqual(notes, [])


@unittest.skipIf(NO_SPACY, "spaCy")
class PlanCompound(unittest.TestCase):
    def test_plan_compound(self):
        f = Folder(PLAN="""
            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
              - S1.e1 · paragraph · the valve holds the water, and the owner never sees it; explains: check valve, pressure switch · facts: F1 · 5 lines
              - S1.e2 · paragraph · the pump fills the tank and stops at the limit · facts: F2 · 5 lines
            """)
        try:
            notes = []
            errs, cands = no_compound.gate_plan_compound(f.doc(), [1, 3], notes)
            self.assertEqual(notes, [])
            flagged = [e.where for e in errs] + [w for w, _, _ in cands]
            self.assertIn("PLAN.md S1.e1", flagged)
            self.assertNotIn("PLAN.md S1.e2", flagged)
            self.assertFalse(any("explains" in e.quote for e in errs))
        finally:
            f.close()


class CustomGates(unittest.TestCase):
    def test_check_lines_go_to_a_judge(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("gate_run_mod", HOOK)
        gr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gr)
        f = Folder()
        try:
            c = f.path / ".gates" / "custom"
            c.mkdir(parents=True)
            (c / "docs_reliance.py").write_text(
                "# TEXT.md: conclusions do not rest on the documentation alone\n"
                "print('CHECK: S1.e1 — the docs say so')\nprint('S2.e1 — a hard failure')\n")
            (c / "no_rule.py").write_text("# TEXT.md: x\nprint('CHECK: S1.e2 — y')\n")
            fails, reqs = gr.custom_gates(f.path, "TEXT.md", common.Failure, jg.JudgeRequest)
            self.assertEqual(reqs, [])  # no rule file yet: CHECK lines cannot reach a judge
            self.assertTrue(any("missing or empty" in x.why for x in fails))
            (c / "docs_reliance.md").write_text("A conclusion may not rest on «the documentation says» alone.")
            (c / "no_rule.py").unlink()
            fails, reqs = gr.custom_gates(f.path, "TEXT.md", common.Failure, jg.JudgeRequest)
            self.assertEqual([x.why for x in fails], ["S2.e1 — a hard failure"])
            self.assertEqual([r.agent for r in reqs], ["unslopable:gate-custom"])
            self.assertIn("the docs say so", reqs[0].input)
            self.assertIn("may not rest on", reqs[0].input)
            self.assertEqual(gr.custom_gates(f.path, "PLAN.md", common.Failure, jg.JudgeRequest), ([], []))
        finally:
            f.close()


class HeadingGates(unittest.TestCase):
    def test_colon_dash_and_words_sections(self):
        f = Folder(PLAN="""
            - S1 · **Pressure: who sets it** · x · 10 lines
            - S2 · **Settings — the defaults** · y · 5 lines
            - S3 · **A built-in valve** · z · 3 lines
            - S4 · **One two three four five six seven** · w · 2 lines
            """)
        try:
            fs = run_scripts.run_plan(f.doc(), 1)
            by = {(x.gate, x.where) for x in fs}
            self.assertIn(("heading-no-colon-dash", "PLAN.md S1"), by)
            self.assertIn(("heading-no-colon-dash", "PLAN.md S2"), by)
            self.assertNotIn(("heading-no-colon-dash", "PLAN.md S3"), by)  # a hyphen in a word is no dash
            self.assertIn(("heading-max-words", "PLAN.md S4"), by)
        finally:
            f.close()

    def test_colon_dash_and_words_subsections(self):
        f = Folder(PLAN=fixture_plan().replace("**Low water cutoff**", "**Low water: cutoff**")
                   .replace("**Pressure limits**", "**Who may change the pump limits today**"))
        try:
            by = {(x.gate, x.where) for x in run_scripts.run_plan(f.doc(), 2)}
            self.assertIn(("heading-no-colon-dash", "PLAN.md S2.1"), by)
            self.assertIn(("heading-max-words", "PLAN.md S2.2"), by)
        finally:
            f.close()

    def test_text_headings_need_not_match_the_plan(self):
        # condition: plan headings are working titles; no gate compares the text's headings with the plan's
        text = (FIXTURE / "TEXT.md").read_text()
        text = text.replace("## When the pump runs", "## When the pump stops")
        text = text.replace("### Low water cutoff", "### Cutoffs that guard the pump")
        f = Folder(**{"TEXT.md": text, "BRIEF.md": polish_brief()})
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertEqual([x.line() for x in fails], [])
        finally:
            f.close()
        # the section judges see the text's own headings, not the plan's working titles
        f = Folder(**{"TEXT.md": text})
        try:
            reqs = jg.text_requests(f.doc(), [])
            shown = [r for r in reqs if r.gate in ("flow-sections", "out-of-scope")]
            self.assertTrue([r for r in shown if r.gate == "flow-sections"])
            self.assertTrue(any("When the pump stops" in r.input for r in shown if r.gate == "flow-sections"))
            for r in shown:
                self.assertNotIn("When the pump runs", r.input, r.unit)
                self.assertNotIn("Low water cutoff", r.input, r.unit)
        finally:
            f.close()


class TextGates(unittest.TestCase):
    def text(self, body: str, **more):
        return Folder(**{"TEXT.md": body}, **more)

    def run_text_no_spacy(self, f):
        d = f.doc()
        out = []
        out += formats.text_format(d)
        out += sentence_max_words.gate_sentence_words(d)
        out += no_semicolon.gate_semicolons(d)
        out += one_sentence_per_item.gate_one_sentence_per_item(d)
        out += term_first_use.gate_term_first_sentence(d)
        out += term_counts.gate_term_counts(d)
        out += text_length.gate_text_length(d)
        return out

    def test_sentence_max_words(self):
        f = self.text("""
            <!-- S1.e1 -->
            One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone.
            """)
        try:
            fs = [x for x in self.run_text_no_spacy(f) if x.gate == "sentence-max-words"]
            self.assertEqual(len(fs), 1)
            self.assertIn("21 words", fs[0].why)
        finally:
            f.close()

    def test_semicolon_and_items(self):
        f = self.text("""
            <!-- S1.e1 -->
            Owners add rooms; builders remove them.

            <!-- S2.2.e1 -->
            - Owners change settings. Guests do not.
            - Guests change nothing &amp; read.

            <!-- S1.e3 -->
            | Role | Can |
            |---|---|
            | Owner | Everything. Really everything. |
            """)
        try:
            fs = self.run_text_no_spacy(f)
            g = gates_of(fs)
            self.assertEqual(g.count("no-semicolon"), 1)  # the entity &amp; is no semicolon
            items = [x for x in fs if x.gate == "one-sentence-per-item"]
            self.assertEqual(len(items), 2)
            self.assertTrue(any("list item" in x.why for x in items) and any("table cell" in x.why for x in items))
        finally:
            f.close()

    def test_term_first_sentence(self):
        f = self.text("""
            <!-- S1.e1 -->
            A pressure switch is one sensor per tank. It stays there.
            """)
        try:
            fs = [x for x in self.run_text_no_spacy(f) if x.gate == "term-first-use"]
            self.assertEqual(len(fs), 1)
            self.assertIn("pressure switch", fs[0].why)
            reqs = jg.text_requests(f.doc(), [])
            self.assertFalse([r for r in reqs if r.gate == "term-explained"])  # the script already failed it
        finally:
            f.close()

    def test_term_counts(self):
        f = self.text("""
            <!-- S1.e1 -->
            Families want water to stay put. The pump keeps a pressure switch there, and the check valve holds water.

            <!-- S1.e2 -->
            ![fig](f.png)
            """)
        try:
            fs = [x for x in self.run_text_no_spacy(f) if x.gate == "term-counts"]
            whys = " ".join(x.why for x in fs)
            self.assertIn("at most 1 allowed", whys)  # before the first figure
            self.assertIn("in one element", whys)     # per unit
        finally:
            f.close()

    def test_term_counts_skip_items_explained_in_their_own_row(self):
        # Items of an outside list explained in their own row, item or tile are not counted
        terms = ("# Terms\n\n## Known\n\n- tap — a water outlet\n\n## Explain\n\n- A1 — a grade\n- B2 — a grade\n"
                 "- C3 — a grade\n- pressure switch — one sensor per tank\n")
        f = self.text("""
            <!-- S1.e1 -->
            A farm sells three grades of apples.

            | Grade | What it is |
            | --- | --- |
            | A1 | large apples sold whole |
            | B2 | small apples for juice |
            | C3 | bruised apples for cider |
            """, **{"TERMS.md": terms, "GATES.md": "terms_before_first_figure: 1\nsentence_max_words: 30\n"})
        try:
            self.assertEqual([x for x in term_counts.gate_term_counts(f.doc()) if x.gate == "term-counts"], [])
            prose = f.path / "TEXT.md"
            prose.write_text(prose.read_text().replace("three grades of apples.", "A1, B2 and C3 apples."))
            self.assertTrue([x for x in term_counts.gate_term_counts(f.doc()) if x.gate == "term-counts"])
        finally:
            f.close()

    def test_term_counts_default_per_unit(self):
        f = Folder(**{"GATES.md": "terms_before_first_figure: 5\nsentence_max_words: 30\n"})
        try:
            d = f.doc()
            self.assertEqual([x for x in term_counts.gate_term_counts(d) if x.gate == "config"], [])
        finally:
            f.close()

    def test_text_format(self):
        f = self.text("""
            A block before any marker.

            <!-- S9.e9 -->
            A block with an unknown id.
            """)
        try:
            fs = [x for x in self.run_text_no_spacy(f) if x.gate == "format"]
            self.assertEqual(len(fs), 2)
        finally:
            f.close()

    def test_marker_must_name_an_element(self):
        # S1 is an item of PLAN.md but a section, not an element: the text marks elements only
        body = "<!-- {} -->\nA family opens a tap in its kitchen.\n"
        f, g = self.text(body.format("S1")), self.text(body.format("S1.e1"))
        try:
            fs = [x for x in formats.text_format(f.doc()) if x.gate == "format"]
            self.assertEqual(len(fs), 1, [x.line() for x in fs])
            self.assertEqual([x.line() for x in formats.text_format(g.doc())], [])  # an element id is a good marker
        finally:
            f.close()
            g.close()

    def test_markers_read_from_plan_md(self):
        # every fixture element is a valid marker: no format failure on the fixture text
        self.assertEqual([x.line() for x in formats.text_format(docs.load(FIXTURE))], [])

    def test_text_without_plan_elements_fails(self):
        f = Folder(PLAN="""
            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
            - S2 · **Settings that protect the pump** · the settings worth changing · 10 lines
            """, **{"BRIEF.md": polish_brief()})
        try:
            self.assertEqual(([r.id for r in f.doc().plans[1]], f.doc().plans[3]), (["S1", "S2"], []))
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertIn(("format", "TEXT.md"), {(x.gate, x.where) for x in fails})
        finally:
            f.close()

    def test_text_without_plan_file_fails(self):
        f = Folder(PLAN=None, **{"BRIEF.md": polish_brief()})
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertIn(("format", "TEXT.md"), {(x.gate, x.where) for x in fails})
        finally:
            f.close()

    def test_text_length_goes_back_to_plan(self):
        long = " ".join(["word"] * 80) + "."
        f = self.text(f"<!-- S1.e1 -->\n{long}\n")
        try:
            fs = [x for x in text_length.gate_text_length(f.doc()) if x.gate == "length"]
            self.assertEqual(len(fs), 1)
            self.assertIn("goes back to the plan", fs[0].why)
            self.assertIn("never to cutting", fs[0].why)
        finally:
            f.close()

    def test_text_length_uses_plan_md_sizes(self):
        # the same 80-word paragraph fits once PLAN.md gives S1.e1 eight lines (and S1 the sum)
        long = " ".join(["word"] * 80) + "."
        f = self.text(f"<!-- S1.e1 -->\n{long}\n")
        try:
            self.assertTrue([x for x in text_length.gate_text_length(f.doc()) if x.gate == "length"])  # 4 lines: too long
            (f.path / "PLAN.md").write_text(fixture_plan().replace("facts: F1 · 4 lines", "facts: F1 · 8 lines"))
            self.assertEqual([x for x in text_length.gate_text_length(f.doc()) if x.gate == "length"], [])
        finally:
            f.close()

    def test_missing_config_is_a_failure(self):
        f = Folder(**{"GATES.md": "# nothing\n"})
        try:
            fs = sentence_max_words.gate_sentence_words(f.doc()) + text_length.gate_text_length(f.doc())
            self.assertTrue(fs and all(x.gate == "config" for x in fs))
            self.assertIn("sentence_max_words", fs[0].why)
        finally:
            f.close()

    def test_out_of_scope_search(self):
        f = self.text("""
            <!-- S1.e1 -->
            The Bluebird project used the pump.
            """)
        try:
            d = f.doc()
            pieces = [(common.where(u, d.text.blocks), u.text) for u in common.body_units(d.text.blocks)]
            fs = out_of_scope.gate_oos_search(d, pieces)
            self.assertEqual(len(fs), 1)
            self.assertIn("Bluebird", fs[0].why)
        finally:
            f.close()


class PlanGates(unittest.TestCase):
    def test_fact_one_place_and_summary(self):
        f = Folder(PLAN="""
            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
              - S1.e1 · paragraph · a · facts: F1, F2 · 5 lines
              - S1.e2 · paragraph · b · facts: F2 · 5 lines
            - S2 · **Settings that protect the pump** · the settings worth changing · 8 lines
              - S2.1 · **Low water cutoff** · when to turn it off · 3 lines
                - S2.1.e1 · summary · c · facts: F1 · 3 lines
              - S2.2 · **Pressure limits** · who may change the limits · 5 lines
                - S2.2.e1 · list · d · 5 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "fact-one-place"]
            self.assertEqual([x.quote for x in fs], ["F2"])  # F1 repeats only in a summary
        finally:
            f.close()

    def test_terms_placed(self):
        f = Folder(PLAN="""
            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
              - S1.e1 · paragraph · a; explains: Pressure Switch · facts: F1 · 5 lines
              - S1.e2 · paragraph · b; explains: pressure switch, `tap` · facts: F2 · 5 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "terms-placed"]
            self.assertEqual(sorted(x.quote for x in fs), ["check valve", "pressure switch"])
            self.assertIn("S1.e1, S1.e2", [x.where for x in fs if x.quote == "pressure switch"][0])
        finally:
            f.close()

    def test_term_order(self):
        f = Folder(PLAN="""
            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
              - S1.e1 · paragraph · water passes the check valve first; explains: pressure switch · facts: F1 · 5 lines
            - S2 · **Settings** · where the check valve sits · 15 lines
              - S2.e2 · paragraph · what the valve does; explains: check valve · facts: F2 · 5 lines
              - S2.e3 · paragraph · the check valve again · facts: F3 · 5 lines
            """)
        try:
            c = term_order.term_order_candidates(f.doc())
            self.assertEqual([(t, el, prev) for t, el, prev, _ in c], [("check valve", "S2.e2", "S1.e1"), ("check valve", "S2.e2", "S2")])
            reqs = jg.term_order_requests(f.doc())
            self.assertEqual([r.agent for r in reqs], ["unslopable:gate-term-order"])
            self.assertIn("check valve — explain", reqs[0].input)
            self.assertIn("term-order", [r.gate for r in jg.plan_requests(f.doc(), 3)])
        finally:
            f.close()

    def test_level_gates_run_only_up_to_upto(self):
        f = Folder(PLAN=fixture_plan().replace("facts: F2 · 2 lines", "facts: F1 · 2 lines"))
        try:
            self.assertIn("fact-one-place", gates_of(run_scripts.run_plan(f.doc(), 3)))
            self.assertNotIn("fact-one-place", gates_of(run_scripts.run_plan(f.doc(), 1)))
            self.assertNotIn("fact-one-place", gates_of(run_scripts.run_plan(f.doc(), 2)))
        finally:
            f.close()

    def test_length_level1(self):
        f = Folder(PLAN="""
            - S1 · **Who sees data** · x · 30 lines
            - S2 · **Settings** · y · 10 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 1) if x.gate == "length"]
            self.assertEqual(len(fs), 1)
            self.assertEqual(fs[0].where, "PLAN.md, all sections")
            self.assertIn("40 lines", fs[0].why)
        finally:
            f.close()

    def test_length_level2(self):
        f = Folder(PLAN="""
            - S1 · **Who sees data** · x · 10 lines
            - S2 · **Settings** · y · 10 lines
              - S2.1 · **Low water cutoff** · x · 9 lines
              - S2.2 · **Pressure limits** · y · 9 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 2) if x.gate == "length"]
            self.assertEqual([x.where for x in fs], ["PLAN.md, subsections of S2"])
        finally:
            f.close()

    def test_length_level3_subsection_and_section(self):
        f = Folder(PLAN="""
            - S1 · **Who sees data** · x · 10 lines
              - S1.e1 · paragraph · a · 30 lines
            - S2 · **Settings** · y · 10 lines
              - S2.1 · **Low water cutoff** · x · 5 lines
                - S2.1.e1 · paragraph · b · 9 lines
              - S2.2 · **Pressure limits** · y · 5 lines
                - S2.2.e1 · list · c · 5 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "length"]
            self.assertEqual(sorted(x.where for x in fs), ["PLAN.md, elements of S1", "PLAN.md, elements of S2.1"])
        finally:
            f.close()

    def test_part_without_elements_fails(self):
        f = Folder(PLAN="""
            - S1 · **Who sees data** · x · 10 lines
              - S1.e1 · paragraph · a · 10 lines
            - S2 · **Settings** · y · 10 lines
              - S2.1 · **Low water cutoff** · x · 5 lines
                - S2.1.e1 · paragraph · b · 5 lines
              - S2.2 · **Pressure limits** · y · 5 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "length"]
            self.assertEqual(len(fs), 1, [x.line() for x in fs])
            self.assertIn("S2.2 has no elements", fs[0].why)
        finally:
            f.close()

    def test_section_without_subsections_or_elements_fails(self):
        f = Folder(PLAN="""
            - S1 · **Who sees data** · x · 10 lines
            - S2 · **Settings** · y · 10 lines
              - S2.e1 · paragraph · b · 10 lines
            """)
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "length"]
            self.assertTrue(any("S1 has no elements" in x.why for x in fs), [x.line() for x in fs])
        finally:
            f.close()

    def test_oos_in_plan_sections(self):
        f = Folder(PLAN=fixture_plan().replace("when the pump starts and stops", "who can see it and pricing"))
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 1) if x.gate == "out-of-scope"]
            self.assertEqual([x.where for x in fs], ["PLAN.md S1"])
        finally:
            f.close()

    def test_oos_in_plan_elements(self):
        f = Folder(PLAN=fixture_plan().replace("the valve keeps the pump primed", "the Bluebird valve holds water"))
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "out-of-scope"]
            self.assertEqual([x.where for x in fs], ["PLAN.md S1.e3"])
        finally:
            f.close()


class Flags(unittest.TestCase):
    def test_hedges(self):
        yes = ["This is not an exhaustive review of the pump.", "To the best of our knowledge, it holds.",
               "The findings should not be relied upon alone."]
        no = ["The pump keeps one switch per tank.", "Owners read the pressure gauge."]
        for s in yes:
            self.assertTrue(no_hedging.HEDGES.search(s), s)
        for s in no:
            self.assertFalse(no_hedging.HEDGES.search(s), s)

    def test_number_refs(self):
        yes = ["See § 3.2 for the details.", "Table 4 lists them.", "As said above, it acts as you.",
               "The previous section showed it.", "Section 2 covers settings."]
        no = ["The pump keeps one switch per tank.", "The manual lists ten faults."]
        for s in yes:
            self.assertTrue(no_number_reference.NUMBER_REFS.search(s), s)
        for s in no:
            self.assertFalse(no_number_reference.NUMBER_REFS.search(s), s)


@unittest.skipIf(NO_SPACY, "spaCy")
class LeadInAndMarking(unittest.TestCase):
    """A list or table is led in; an `explain` term is marked at its first use."""

    def test_list_after_heading_fails_and_led_in_list_goes_to_a_judge(self):
        f = Folder()
        try:
            doc = f.doc()
            self.assertNotIn("list-lead-in", gates_of(list_lead_in.gate_list_lead_in(doc)))
            reqs = jg.text_requests(doc, [])
            self.assertEqual(len([r for r in reqs if r.gate == "list-lead-in"]), 1)
            t = f.path / "TEXT.md"
            t.write_text(t.read_text().replace("Four people decide who may change the limits.\n\n", ""))
            self.assertIn("list-lead-in", gates_of(list_lead_in.gate_list_lead_in(f.doc())))
        finally:
            f.close()

    def test_announced_count_goes_to_a_judge(self):
        f = Folder()
        try:
            t = f.path / "TEXT.md"
            t.write_text(t.read_text().replace("Four people decide who may change the limits.",
                                               "Four people decide who may change the limits in 2026."))
            doc = f.doc()
            reqs = [r for r in jg.text_requests(doc, []) if r.gate == "announced-count"]
            self.assertEqual(len(reqs), 1)
            self.assertIn("Four people", reqs[0].input)
            self.assertIn("Owners change", reqs[0].input)
        finally:
            f.close()

    def test_term_marked_at_first_use(self):
        f = Folder()
        try:
            self.assertEqual(term_marked.gate_term_marked(f.doc()), [])
            t = f.path / "TEXT.md"
            t.write_text(t.read_text().replace("*check valve*", "check valve"))
            fails = term_marked.gate_term_marked(f.doc())
            self.assertEqual([x.gate for x in fails], ["term-marked"])
            self.assertIn("check valve", fails[0].why)
        finally:
            f.close()


@unittest.skipIf(NO_SPACY, "SKIP_SPACY=1")
class Cohesion(unittest.TestCase):
    """Heap of facts and enumerations in running text: the parse marks, one judge per paragraph."""

    def test_parse(self):
        res = cohesion.parse_cohesion([
            ["The vase stood on the table.", "It was painted red.", "Inside, the vase was empty."],
            ["The house has problems.", "The roof leaks.", "The neighbours are loud.", "Taxes went up."],
            ["Apples, pears and plums grow in the garden."],
        ])
        self.assertTrue(all(x["linked"] for x in res[0]["subjects"]))
        self.assertGreaterEqual(sum(1 for x in res[1]["subjects"] if not x["linked"]), 2)
        self.assertEqual(len(res[2]["lists"]), 1)
        self.assertEqual(len(res[2]["lists"][0]["items"]), 3)

    def test_judges_per_paragraph(self):
        f = Folder(**{"TEXT.md": "<!-- S1.e1 -->\nThe house has problems. The roof leaks. The neighbours are loud. "
                                 "Apples, pears and plums grow in the garden.\n"})
        try:
            notes = []
            doc = f.doc()
            coh = cohesion.gate_cohesion(doc, notes)
            self.assertEqual(notes, [])
            reqs = jg.text_requests(doc, [], coh)
            self.assertEqual(len([r for r in reqs if r.gate == "fact-soup"]), 1)
            self.assertEqual(len([r for r in reqs if r.gate == "inline-list"]), 1)
            soup = next(r for r in reqs if r.gate == "fact-soup")
            self.assertIn("NEW", soup.input)
        finally:
            f.close()


class Compound(unittest.TestCase):
    def test_parse(self):
        res = no_compound.parse_compound([
            "The pump fills the tank, and the owner sets the limit.",
            "The pump fills the tank and stops at the limit.",
            "Owners add rooms; builders remove them.",
            "If the owner blocks changes, plumbers cannot fit parts.",
            "The risk is low: the valve blocks the flow.",
            "The maker says the water stays in the tank.",
        ])
        self.assertEqual(res[0]["verdict"], "error")
        self.assertIsNone(res[1])
        self.assertEqual(res[2]["verdict"], "error")
        self.assertIsNone(res[3])
        self.assertEqual(res[4]["verdict"], "candidate")
        self.assertIsNone(res[5])

    def test_gate_and_judge(self):
        f = Folder(**{"TEXT.md": "<!-- S1.e1 -->\nThe pump fills the tank, and the owner sets the limit. "
                                 "The risk is low: the valve blocks the flow.\n"})
        try:
            notes = []
            fails, cands = run_scripts.run_text(f.doc(), notes)
            self.assertIn("no-compound", gates_of(fails))
            self.assertEqual(len(cands), 1)
            reqs = jg.text_requests(f.doc(), cands)
            self.assertEqual(len([r for r in reqs if r.gate == "no-compound"]), 1)
        finally:
            f.close()

    def test_other_language_is_reported(self):
        f = Folder(**{"BRIEF.md": "# Brief\n\n## Language, brand, author\nPolish.\n"})
        try:
            notes = []
            no_compound.gate_compound(f.doc(), notes)
            self.assertTrue(notes and "English" in notes[0])
        finally:
            f.close()




class JudgeRequests(unittest.TestCase):
    def test_plan_requests_per_heading_level(self):
        d = docs.load(FIXTURE)
        for lvl, name, heads in ((1, "sections", ["S1", "S2"]), (2, "subsections", ["S2.1", "S2.2"])):
            reqs = jg.plan_requests(d, lvl)
            g = [r.gate for r in reqs]
            self.assertEqual(g.count("heading-names-topic"), 2, lvl)
            for one in ("goals-covered", "out-of-scope", "section-has-material", "one-topic", "heading-no-listicle"):
                self.assertEqual(g.count(one), 1, (lvl, one))
            self.assertEqual(sorted(r.unit for r in reqs if r.gate == "heading-names-topic"),
                             [f"PLAN.md {h}" for h in heads])
            for r in reqs:
                if r.gate != "heading-names-topic":
                    self.assertTrue(r.unit.startswith(f"PLAN.md {name}"), (r.gate, r.unit))

    def test_plan_requests_elements(self):
        reqs = jg.plan_requests(docs.load(FIXTURE), 3)
        self.assertEqual(sorted(r.gate for r in reqs), ["goals-covered", "out-of-scope"])
        self.assertEqual({r.unit for r in reqs}, {"PLAN.md elements"})

    def test_plan_inputs_show_the_level(self):
        d = docs.load(FIXTURE)
        one_topic = {lvl: [r for r in jg.plan_requests(d, lvl) if r.gate == "one-topic"][0] for lvl in (1, 2)}
        self.assertIn("When the pump runs", one_topic[1].input)
        self.assertIn("Low water cutoff", one_topic[2].input)
        s1 = [r for r in jg.plan_requests(d, 1) if r.unit == "PLAN.md S1"][0]
        self.assertIn("When the pump runs", s1.input)
        self.assertIn("the cutoff stops the pump on a low well",
                      [r for r in jg.plan_requests(d, 3) if r.gate == "goals-covered"][0].input)

    def test_approval_lines_change_no_judge(self):
        f = Folder()  # one folder for both, so the material paths in the inputs are the same
        try:
            approved = {lvl: sorted(r.id for r in jg.plan_requests(f.doc(), lvl)) for lvl in (1, 2, 3)}
            for lvl, item in ((1, "when the pump starts and stops"), (2, "when to turn it off"),
                              (3, "the valve keeps the pump primed")):  # the inputs carry the level's items
                self.assertTrue(any(item in r.input for r in jg.plan_requests(f.doc(), lvl)), lvl)
            for lvl in (1, 2, 3):
                for r in jg.plan_requests(f.doc(), lvl):
                    self.assertNotIn("Approved sections by", r.input)
                    self.assertNotIn("Approved elements by", r.input)
            (f.path / "PLAN.md").write_text(fixture_plan("sections", "subsections", "elements"))
            for lvl in (1, 2, 3):
                self.assertEqual(approved[lvl], sorted(r.id for r in jg.plan_requests(f.doc(), lvl)), lvl)
        finally:
            f.close()

    def test_text_requests_per_unit(self):
        reqs = jg.text_requests(docs.load(FIXTURE), [])
        g = [r.gate for r in reqs]
        self.assertEqual(g.count("term-explained"), 2)      # one per explain term used
        self.assertEqual(g.count("flow-sentences"), 3)      # paragraphs with 2+ sentences
        self.assertEqual(g.count("flow-paragraphs"), 1)     # S1.e3 after the figure, same part
        self.assertEqual(g.count("flow-sections"), 2)       # both sections complete
        self.assertEqual(g.count("out-of-scope"), 2)

    def test_incomplete_section_waits(self):
        f = Folder(**{"TEXT.md": "<!-- S1.e1 -->\nFamilies open a tap. It fills the glass.\n"})
        try:
            g = [r.gate for r in jg.text_requests(f.doc(), [])]
            self.assertNotIn("flow-sections", g)
            self.assertIn("flow-sentences", g)
        finally:
            f.close()

    def test_material_change_changes_the_judge(self):
        f = Folder(**{"FACTS.md": "F1 one fact\n"})
        try:
            one = [r.id for r in jg.plan_requests(f.doc(), 1) if r.gate == "section-has-material"]
            (f.path / "FACTS.md").write_text("F1 one fact\nF2 another\n")
            two = [r.id for r in jg.plan_requests(f.doc(), 1) if r.gate == "section-has-material"]
            self.assertNotEqual(one, two)
        finally:
            f.close()

    def test_flagged_input_has_no_line_numbers(self):
        body = "<!-- S1.e1 -->\nFamilies open a tap. As said above, it fills.\n"
        f = Folder(**{"TEXT.md": body})
        g = Folder(**{"TEXT.md": "\n\n\n" + body})
        try:
            a = [r for r in jg.text_requests(f.doc(), []) if r.gate == "no-number-reference"]
            b = [r for r in jg.text_requests(g.doc(), []) if r.gate == "no-number-reference"]
            self.assertEqual(len(a), 1)
            self.assertEqual(a[0].id, b[0].id)
        finally:
            f.close()
            g.close()

    def test_id_depends_on_input(self):
        a = jg.JudgeRequest("one-topic", "u", "x")
        self.assertEqual(a.id, jg.JudgeRequest("one-topic", "other unit", "x").id)
        self.assertNotEqual(a.id, jg.JudgeRequest("one-topic", "u", "y").id)
        self.assertEqual(a.agent, "unslopable:gate-one-topic")

    def test_every_judge_has_an_agent_file(self):
        gates = {r.gate for lvl in (1, 2, 3) for r in jg.plan_requests(docs.load(FIXTURE), lvl)}
        gates |= {r.gate for r in jg.text_requests(docs.load(FIXTURE), [])}
        gates |= {"no-compound", "no-hedging", "no-number-reference", "term-explained"}
        for g in gates:
            self.assertTrue((ROOT / "gates" / "judges" / f"gate-{g}.md").exists(), g)
        self.assertTrue((ROOT / "agents" / "plan-approver.md").exists())


def run_hook(payload: dict) -> dict | None:
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                       timeout=200)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout) if r.stdout.strip() else None


def recorded(path: Path, tool="Write", new_string: str | None = None) -> dict:
    d = json.loads(RECORDED.read_text())
    d["tool_name"] = tool
    d["tool_input"]["file_path"] = str(path)
    if new_string is not None:
        d["tool_input"]["new_string"] = new_string
    return d


def hook_ctx(path: Path, tool="Write", new_string: str | None = None) -> str:
    out = run_hook(recorded(path, tool, new_string))
    assert out is not None, "the hook said nothing"
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    return out["hookSpecificOutput"]["additionalContext"]


def approved_keys(folder: Path) -> set[str]:
    p = folder / ".gates" / "approved.json"
    return set(json.loads(p.read_text())) if p.exists() else set()


def runner(cmd: str, *args, env: dict | None = None) -> str:
    """The gate runner's script, as the runner calls it; its output stripped."""
    r = subprocess.run([sys.executable, str(COLLECT), cmd] + [str(a) for a in args], capture_output=True, text=True,
                       timeout=120, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def due_agents(folder: Path, name: str | None = None) -> list[str]:
    """The subagent_types of the judges due in the last run on `name` (every gated file when None)."""
    due = json.loads((folder / ".gates" / "due.json").read_text())
    index = json.loads((folder / ".gates" / "requests.json").read_text())
    runs = [due[name]] if name else list(due.values())
    return sorted(index[j]["agent"] for run in runs for j in run["due"])


def pass_every_judge(folder: Path) -> None:
    index = json.loads((folder / ".gates" / "requests.json").read_text())
    (folder / ".gates" / "verdicts.json").write_text(
        json.dumps({j: {"verdict": "PASSED", "text": "PASSED"} for j in index}))


class Hook(unittest.TestCase):
    def test_silent_outside_a_document(self):
        f = Folder()
        try:
            self.assertIsNone(run_hook(recorded(f.path / "GATES.md")))
            self.assertIsNone(run_hook(recorded(f.path / "PLAN.md", tool="Read")))
            (f.path / "PLAN-1.md").write_text((FIXTURE / "PLAN.md").read_text())  # an old name is no plan
            self.assertIsNone(run_hook(recorded(f.path / "PLAN-1.md")))
            (f.path / "BRIEF.md").unlink()
            self.assertIsNone(run_hook(recorded(f.path / "PLAN.md")))
        finally:
            f.close()

    def test_script_failures_stop_before_judges(self):
        f = Folder(PLAN=fixture_plan("sections").replace("**When the pump runs**", "**Pressure: who sets it**"))
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertIn("unslopable gates on PLAN.md", ctx)
            self.assertIn("SCRIPT GATES — NOT PASSED (1)", ctx)
            self.assertIn("heading-no-colon-dash", ctx)
            self.assertNotIn("START ONE AGENT", ctx)
        finally:
            f.close()

    def test_every_written_level_is_gated(self):
        # an element-level failure is caught by a write of PLAN.md (gates run down to the deepest level)
        f = Folder(PLAN=fixture_plan().replace("facts: F2 · 2 lines", "facts: F1 · 2 lines"))
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertIn("SCRIPT GATES — NOT PASSED (1)", ctx)
            self.assertIn("fact-one-place", ctx)
            self.assertNotIn("START ONE AGENT", ctx)
        finally:
            f.close()

    def test_format_problem_is_a_script_failure(self):
        f = Folder(PLAN=fixture_plan().replace("- S1.e2 · figure · the path of the water · 4 lines",
                                               "- S1.e2 · figure · the path of the water"))
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertIn("SCRIPT GATES — NOT PASSED", ctx)
            self.assertIn("[format]", ctx)
            self.assertIn("S1.e2", ctx)
            self.assertNotIn("START ONE AGENT", ctx)
        finally:
            f.close()

    def test_levels_not_written_yet_are_not_gated(self):
        # only sections written: no "part without elements" failure, only the section judges
        f = Folder(PLAN="""
            # Plan

            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
            - S2 · **Settings that protect the pump** · the settings worth changing · 10 lines
            """)
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertNotIn("SCRIPT GATES", ctx)
            self.assertIn("Judges due now: 7.", ctx)
        finally:
            f.close()

    def test_judges_only_for_unapproved_levels(self):
        for unapproved, n in ((["subsections"], 7), (["elements"], 2), (["sections", "elements"], 9)):
            f = Folder(PLAN=fixture_plan(*unapproved))
            try:
                ctx = hook_ctx(f.path / "PLAN.md")
                self.assertIn(f"Judges due now: {n}.", ctx, unapproved)
                units = {v["unit"] for v in json.loads((f.path / ".gates" / "requests.json").read_text()).values()}
                for name in LEVEL_NAMES.values():
                    if name not in unapproved:
                        self.assertNotIn(f"PLAN.md {name}", units, (unapproved, name))
            finally:
                f.close()

    def test_unapproved_level_is_noted(self):
        f = Folder(PLAN=fixture_plan("sections"))
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertIn("the sections are not approved yet", ctx)
            self.assertNotIn("the subsections are not approved yet", ctx)
            self.assertNotIn("the elements are not approved yet", ctx)
        finally:
            f.close()

    def test_judges_then_cache_then_approval_level_by_level(self):
        f = Folder(PLAN=fixture_plan("sections", "subsections", "elements"))
        p = f.path / "PLAN.md"
        try:
            ctx = hook_ctx(p, tool="Edit")
            self.assertIn("Judges due now: 16.", ctx)  # 7 on sections, 7 on subsections, 2 on elements
            index = json.loads((f.path / ".gates" / "requests.json").read_text())
            self.assertEqual(len(index), 16)
            for jid in index:
                self.assertTrue((f.path / ".gates" / "inputs" / f"{jid}.md").exists())
            # one judge said NOT PASSED, the rest PASSED
            ids = sorted(index)
            verdicts = {j: {"verdict": "PASSED", "text": "PASSED"} for j in ids}
            verdicts[ids[0]] = {"verdict": "NOT PASSED", "text": "NOT PASSED\n- «x» — S1 — why"}
            (f.path / ".gates" / "verdicts.json").write_text(json.dumps(verdicts))
            ctx = hook_ctx(p)
            self.assertIn("JUDGE GATES — NOT PASSED — 1 place, details in ", ctx)  # the report, written by the hook
            self.assertNotIn("«x»", ctx)  # the judge's answer is in the report, never in the context
            self.assertIn("«x» — S1 — why", (f.path / ".gates" / "report-PLAN.md.md").read_text())
            self.assertNotIn("START ONE AGENT", ctx)
            # every judge passed: the lowest unapproved level, the sections, goes for approval
            pass_every_judge(f.path)
            ctx = hook_ctx(p)
            self.assertIn("Every gate of the plan passed", ctx)
            self.assertNotIn("unslopable:plan-approver", ctx)
            self.assertIn("Approved sections by <the author>", ctx)
            self.assertNotIn("START ONE AGENT", ctx)
            # the sections are approved by an Edit adding their line; next the subsections go
            line = approval_line("sections", "2026-11-19 03:00")
            p.write_text(line + "\n\n" + p.read_text())
            ctx = hook_ctx(p, tool="Edit", new_string=line)
            self.assertIn("PLAN.md sections", approved_keys(f.path))
            self.assertNotIn("the sections are not approved yet", ctx)
            self.assertIn("Approved subsections by <the author>", ctx)
            self.assertNotIn("the plan is approved", ctx)
            # subsections, then elements
            line = approval_line("subsections", "2026-11-19 03:05")
            p.write_text(line + "\n\n" + p.read_text())
            ctx = hook_ctx(p, tool="Edit", new_string=line)
            self.assertIn("PLAN.md subsections", approved_keys(f.path))
            self.assertIn("Approved elements by <the author>", ctx)
            self.assertNotIn("the plan is approved", ctx)
            line = approval_line("elements", "2026-11-19 03:10")
            p.write_text(line + "\n\n" + p.read_text())
            ctx = hook_ctx(p, tool="Edit", new_string=line)
            self.assertIn("PLAN.md elements", approved_keys(f.path))
            self.assertIn("the plan is approved", ctx)
            self.assertNotIn("not approved yet", ctx)
        finally:
            f.close()

    def test_fully_approved_plan(self):
        f = Folder()
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertIn("the plan is approved", ctx)
            self.assertNotIn("START ONE AGENT", ctx)
            self.assertNotIn("not approved yet", ctx)
        finally:
            f.close()

    def test_empty_level_needs_no_approval(self):
        # no section has subsections: sections and elements approved means the plan is approved
        f = Folder(PLAN="""
            Approved sections by plan-approver for Test Author, 2026-11-19

            Approved elements by plan-approver for Test Author, 2026-11-19

            # Plan

            - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
              - S1.e1 · paragraph · the switch starts and stops the pump; explains: pressure switch · facts: F1 · 4 lines
              - S1.e2 · figure · the path of the water · 4 lines
              - S1.e3 · paragraph · the valve keeps the pump primed; explains: check valve · facts: F2 · 2 lines
            - S2 · **Settings that protect the pump** · the settings worth changing · 10 lines
              - S2.e1 · paragraph · the cutoff stops the pump on a low well · facts: F3 · 5 lines
              - S2.e2 · list · who can edit · facts: F4 · 5 lines
            """)
        try:
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertNotIn("SCRIPT GATES", ctx)
            self.assertIn("the plan is approved", ctx)
            self.assertNotIn("Approved subsections by", ctx)
            self.assertNotIn("the subsections are not approved yet", ctx)
        finally:
            f.close()

    def test_edit_of_one_level_stales_only_that_level(self):
        for old, new, name, n in (
                ("when the pump starts and stops", "who can see it", "sections", 7),
                ("when to turn it off", "when to switch them off", "subsections", 7),
                ("the valve keeps the pump primed", "the valve keeps the water", "elements", 2)):
            f = Folder()
            p = f.path / "PLAN.md"
            try:
                hook_ctx(p)  # the approvals are recorded
                p.write_text(p.read_text().replace(old, new))
                ctx = hook_ctx(p, tool="MultiEdit")
                self.assertIn(f"the {name} changed since their approval", ctx)
                for other in LEVEL_NAMES.values():
                    if other != name:
                        self.assertNotIn(f"the {other} changed since their approval", ctx)
                        self.assertNotIn(f"the {other} are not approved yet", ctx)
                self.assertIn(f"Judges due now: {n}.", ctx, name)
                self.assertNotIn("the plan is approved", ctx)
            finally:
                f.close()

    def test_write_keeping_the_line_is_no_new_approval(self):
        f = Folder()
        p = f.path / "PLAN.md"
        try:
            hook_ctx(p)
            p.write_text(p.read_text().replace("when the pump starts and stops", "who can see it"))
            ctx = hook_ctx(p, tool="Write")
            self.assertIn("the sections changed since their approval", ctx)
            ctx = hook_ctx(p, tool="Write")  # a second write does not turn it into an approval either
            self.assertIn("the sections changed since their approval", ctx)
        finally:
            f.close()

    def test_new_approval_line_approves_the_edited_level(self):
        f = Folder()
        p = f.path / "PLAN.md"
        try:
            hook_ctx(p)
            p.write_text(p.read_text().replace("when the pump starts and stops", "who can see it"))
            self.assertIn("the sections changed since their approval", hook_ctx(p, tool="Edit"))
            new = approval_line("sections", "2026-11-20 10:00")
            p.write_text(p.read_text().replace(approval_line("sections"), new))
            ctx = hook_ctx(p, tool="Edit", new_string=new)
            self.assertNotIn("changed since their approval", ctx)
            self.assertIn("the plan is approved", ctx)
        finally:
            f.close()

    def test_edit_mentioning_approval_is_no_approval(self):
        f = Folder()
        p = f.path / "PLAN.md"
        try:
            hook_ctx(p)  # recorded as approved
            p.write_text(p.read_text().replace("when the pump starts and stops", "Approved sections by the owner"))
            ctx = hook_ctx(p, tool="Edit", new_string="Approved sections by the owner")
            self.assertIn("the sections changed since their approval", ctx)
        finally:
            f.close()

    def test_text_notes_unapproved_elements(self):
        f = Folder(PLAN=fixture_plan("elements"))
        try:
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertIn("the elements are not approved yet", ctx)
        finally:
            f.close()

    def test_judges_are_capped_per_round(self):
        paras = "\n\n".join(f"<!-- S1.e1 -->\nFamily {k} opens a tap. It fills their glasses."
                             for k in range(30))
        gates = (FIXTURE / "GATES.md").read_text().replace("length_tolerance_pct: 20", "length_tolerance_pct: 5000")
        f = Folder(**{"TEXT.md": paras + "\n", "GATES.md": gates})
        try:
            ids = [r.id for r in jg.text_requests(f.doc(), [])]
            self.assertGreater(len(ids), 20)
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertIn(f"Judges due now: {len(set(ids))}.", ctx)  # every due judge goes to the one runner
            self.assertEqual(ctx.count("START ONE AGENT NOW"), 1)
            out = runner("next", f.path, "TEXT.md")
            self.assertIn("ROUND: 20 judges", out)  # the runner takes them 20 at a time
        finally:
            f.close()

    def test_skipped_gate_is_not_called_passed(self):
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            ids = [r.id for r in jg.text_requests(f.doc(), [])]
            (f.path / ".gates").mkdir()
            (f.path / ".gates" / "verdicts.json").write_text(json.dumps({i: {"verdict": "PASSED"} for i in ids}))
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertIn("did not run", ctx)
            self.assertIn("Every gate that ran passed", ctx)
            self.assertNotIn("Every gate passed", ctx)
        finally:
            f.close()

    def test_broken_gate_module_is_reported(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(ROOT / "hooks", tmp / "hooks")
            shutil.copytree(ROOT / "gates", tmp / "gates")
            (tmp / "gates" / "lib" / "run_scripts.py").write_text("this is not python(\n")
            f = Folder()
            r = subprocess.run([sys.executable, str(tmp / "hooks" / "gate_run.py")],
                               input=json.dumps(recorded(f.path / "PLAN.md")), capture_output=True, text=True)
            f.close()
            self.assertEqual(r.returncode, 0)
            self.assertIn("did not run", r.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_broken_input_never_blocks(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("did not run", r.stdout)


def fake_transcript(path: Path, prompt: str, answer: str | None) -> None:
    lines = [{"type": "user", "message": {"role": "user", "content": prompt}}]
    if answer is not None:
        lines.append({"type": "assistant", "message": {"role": "assistant", "stop_reason": "end_turn",
                                                       "content": [{"type": "text", "text": answer}]}})
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")


class Collect(unittest.TestCase):
    def test_verdict_shapes(self):
        sys.path.insert(0, str(ROOT / "hooks"))
        import collect_judges as cj
        self.assertEqual(cj.verdict("```\nPASSED\n```"), "PASSED")
        self.assertEqual(cj.verdict("```\nNOT PASSED\n- «x» — y — z\n```"), "NOT PASSED")
        self.assertEqual(cj.verdict("**NOT PASSED**\n- x"), "NOT PASSED")
        self.assertEqual(cj.verdict("Verdict: PASSED"), "PASSED")
        self.assertEqual(cj.verdict("APPROVED"), "APPROVED")
        self.assertEqual(cj.verdict("I think it is fine"), "UNCLEAR")

    def test_no_arguments(self):
        for args in ([], ["next"], ["next", "/tmp"], ["record", "/tmp"], ["record", "/tmp", "x", "--timeout"],
                     ["report", "/tmp"], ["collect", "/tmp", "x"]):
            r = subprocess.run([sys.executable, str(COLLECT)] + args, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, args)
            self.assertIn("usage", r.stdout)

    def test_records_verdicts(self):
        f = Folder()
        try:
            state = f.path / ".gates"
            state.mkdir()
            (state / "requests.json").write_text(json.dumps({
                "one-topic-aaa": {"gate": "one-topic", "unit": "PLAN.md sections"},
                "flow-sections-bbb": {"gate": "flow-sections", "unit": "section S1"},
                "plan-approver-ccc": {"gate": "plan-approver", "unit": "PLAN.md sections"},
                "out-of-scope-ddd": {"gate": "out-of-scope", "unit": "PLAN.md sections"}}))
            t = Path(f.tmp)
            fake_transcript(t / "a.jsonl", "judge_id: one-topic-aaa\ninput: /x", "PASSED")
            fake_transcript(t / "b.jsonl", "judge_id: flow-sections-bbb\ninput: /x",
                            "NOT PASSED\n- «Settings» — S2 — jumps")
            fake_transcript(t / "c.jsonl", "judge_id: plan-approver-ccc\ninput: /x", "APPROVED")
            fake_transcript(t / "d.jsonl", "judge_id: out-of-scope-ddd\ninput: /x", None)  # never finishes
            out = runner("record", f.path, t / "a.jsonl", t / "b.jsonl", t / "c.jsonl", t / "d.jsonl",
                         "--timeout", "3")
            self.assertEqual(out, "recorded 3 of 4: APPROVED 1, NOT PASSED 1, PASSED 1, not finished 1")
            self.assertNotIn("jumps", out)  # counts only: the runner never sees an answer through the script
            v = json.loads((state / "verdicts.json").read_text())
            self.assertEqual(v["one-topic-aaa"]["verdict"], "PASSED")
            self.assertEqual(v["flow-sections-bbb"]["verdict"], "NOT PASSED")
            self.assertEqual(v["plan-approver-ccc"]["verdict"], "PASSED")
            self.assertNotIn("out-of-scope-ddd", v)
        finally:
            f.close()


class Runner(unittest.TestCase):
    """The gate runner between the writing stage and its judges: the hook asks for one runner and
    nothing of the judges; the runner's script hands out rounds, records verdicts and writes the report."""

    def test_hook_asks_for_exactly_one_runner(self):
        f = Folder(PLAN=fixture_plan("sections"))
        try:
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertNotIn("SCRIPT GATES", ctx)
            self.assertEqual(ctx.count("START ONE AGENT NOW"), 1)
            self.assertEqual(ctx.count("subagent_type"), 1)
            self.assertIn('subagent_type "unslopable:gate-runner"', ctx)
            self.assertIn(f"   folder: {os.path.realpath(f.path)}\n   file: TEXT.md\n   script: {COLLECT}\n", ctx)
            # no judge is named, and no judge input or id reaches the writer
            self.assertNotIn("unslopable:gate-", ctx.replace("unslopable:gate-runner", ""))
            self.assertNotIn("judge_id", ctx)
            self.assertNotIn(".gates/inputs", ctx)
            due = json.loads((f.path / ".gates" / "due.json").read_text())["TEXT.md"]
            index = json.loads((f.path / ".gates" / "requests.json").read_text())
            self.assertIn(f"Judges due now: {len(due['due'])}.", ctx)
            for j in due["due"]:
                self.assertIn(j, index)
                self.assertTrue((f.path / ".gates" / "inputs" / f"{j}.md").exists())
            self.assertTrue((ROOT / "agents" / "gate-runner.md").exists())
        finally:
            f.close()

    def test_rounds_record_and_report(self):
        f = Folder(PLAN=fixture_plan("sections"))  # sections unapproved: 7 judges on PLAN.md
        try:
            hook_ctx(f.path / "PLAN.md")
            out = runner("next", f.path, "PLAN.md", "--max", "5")
            self.assertTrue(out.startswith("ROUND: 5 judges (2 more after these)"), out)
            ids = re.findall(r"judge_id: (\S+)", out)
            self.assertEqual(len(ids), 5)
            self.assertEqual(out.count("subagent_type \"unslopable:gate-"), 5)
            # the judges answer; the runner passes their agent ids, the script finds the transcripts
            conf = Path(f.tmp) / "conf"
            sub = conf / "projects" / "-some-project" / "session-1" / "subagents"
            sub.mkdir(parents=True)
            env = dict(os.environ, CLAUDE_CONFIG_DIR=str(conf))
            answers = ["PASSED"] * 4 + ["```\nNOT PASSED\n- «Settings that reduce risk» — S2 — a list noun\n"
                                        "- «Who sees» — S1 — answers the topic\n```"]
            for k, (j, a) in enumerate(zip(ids, answers)):
                fake_transcript(sub / f"agent-a{k}.jsonl", f"judge_id: {j}\ninput: /x", a)
            out = runner("record", f.path, *[f"a{k}" for k in range(5)], env=env)
            self.assertEqual(out, "recorded 5 of 5: NOT PASSED 1, PASSED 4")
            # the next round holds only the two left; a judge with no verdict is served again, twice at most
            out = runner("next", f.path, "PLAN.md")
            rest = re.findall(r"judge_id: (\S+)", out)
            self.assertEqual(len(rest), 2)
            self.assertFalse(set(rest) & set(ids))
            fake_transcript(sub / "agent-b0.jsonl", f"judge_id: {rest[0]}\ninput: /x", "PASSED")
            fake_transcript(sub / "agent-b1.jsonl", f"judge_id: {rest[1]}\ninput: /x", "It looks fine to me")
            self.assertEqual(runner("record", f.path, "b0", "b1", env=env), "recorded 1 of 2: PASSED 1, no verdict 1")
            self.assertEqual(re.findall(r"judge_id: (\S+)", runner("next", f.path, "PLAN.md")), [rest[1]])
            self.assertEqual(runner("next", f.path, "PLAN.md"), "NONE")
            # the report: one line, every failed place with its quotes in the file
            line = runner("report", f.path, "PLAN.md")
            path = f.path / ".gates" / "report-PLAN.md.md"
            real = Path(os.path.realpath(f.path)) / ".gates" / "report-PLAN.md.md"  # the hook names the real path
            self.assertEqual(line, f"NOT PASSED — 3 places, details in {path}")
            rep = path.read_text()
            self.assertIn("NOT PASSED — 3 places (7 judges: 5 passed, 1 not passed, 1 with no verdict)", rep)
            self.assertIn("- «Settings that reduce risk» — S2 — a list noun", rep)
            self.assertIn("- «Who sees» — S1 — answers the topic", rep)
            self.assertNotIn("```", rep)
            self.assertIn("## No verdict (1)", rep)
            self.assertIn("PLAN.md sections", rep)
            # a later write with the same plan: no judge is due, the hook writes the report and says the same line
            fake_transcript(sub / "agent-c0.jsonl", f"judge_id: {rest[1]}\ninput: /x", "PASSED")
            runner("record", f.path, "c0", env=env)
            ctx = hook_ctx(f.path / "PLAN.md")
            self.assertNotIn("START ONE AGENT", ctx)
            self.assertIn(f"JUDGE GATES — NOT PASSED — 2 places, details in {real}", ctx)
            self.assertNotIn("a list noun", ctx)
            # every judge passed
            pass_every_judge(f.path)
            self.assertEqual(runner("report", f.path, "PLAN.md"), "PASSED")
            self.assertIn("Every gate of the plan passed", hook_ctx(f.path / "PLAN.md"))
        finally:
            f.close()

    def test_new_write_gives_a_judge_its_tries_again(self):
        f = Folder(PLAN=fixture_plan("sections"))
        try:
            hook_ctx(f.path / "PLAN.md")
            runner("next", f.path, "PLAN.md")
            runner("next", f.path, "PLAN.md")
            self.assertEqual(runner("next", f.path, "PLAN.md"), "NONE")  # two tries, no verdict
            hook_ctx(f.path / "PLAN.md")
            self.assertIn("ROUND: 7 judges", runner("next", f.path, "PLAN.md"))
        finally:
            f.close()

    def test_unknown_agent_id_records_nothing(self):
        f = Folder(PLAN=fixture_plan("sections"))
        try:
            hook_ctx(f.path / "PLAN.md")
            env = dict(os.environ, CLAUDE_CONFIG_DIR=str(Path(f.tmp) / "none"), HOME=str(Path(f.tmp)))
            self.assertEqual(runner("record", f.path, "zzz", "../x", env=env),
                             "recorded 0 of 2: no transcript 2")
        finally:
            f.close()


# ================================================================ seven text gates of the library (lines 68, 69, 72,
# 74, 81, 83, 85): no document talk, no announcing, no repetition, example on its own line, date tense and weekday,
# no truncated sentence, summary faithful. The documents here are a small bakery text, independent of the fixture.

BAKERY_PLAN = """
    # Plan

    - S1 · **Morning baking** · how the bakery bakes before it opens · 6 lines
      - S1.e1 · paragraph · the ovens start early · facts: F1 · 3 lines
      - S1.e2 · paragraph · the dough rests overnight · facts: F2 · 3 lines
    - S2 · **Selling bread** · how the shop sells its bread · 6 lines
      - S2.e1 · paragraph · the shop opens at seven · facts: F3 · 3 lines
      - S2.e2 · paragraph · regulars ask ahead · facts: F4 · 3 lines
    - S3 · **Closing time** · what happens with leftovers · 3 lines
      - S3.e1 · paragraph · leftovers go to a shelter · facts: F5 · 3 lines
    """

BAKERY_PARAS = {
    "S1.e1": "The ovens start before dawn. The first loaves come out at six.",
    "S1.e2": "The dough rests overnight in a cool room. Slow rising gives the crust its colour.",
    "S2.e1": "The shop opens at seven. The baker serves the first customers himself.",
    "S2.e2": "Regulars ask for their loaves a day ahead.",
    "S3.e1": "Unsold bread goes to a shelter nearby. Nothing is thrown away.",
}

BAKERY_HEADINGS = {"S0": "In short", "S1": "Morning baking", "S2": "Selling bread", "S3": "Closing time",
                   "S4": "In short"}


def bakery_text(paras: dict) -> str:
    """TEXT.md of the bakery: one `## heading` per section, then each element's marker and paragraph, in the order of
    `paras` (an element left out has no text yet)."""
    out, sec = ["# The corner bakery", ""], None
    for el, body in paras.items():
        s = el.split(".")[0]
        if s != sec:
            out += [f"## {BAKERY_HEADINGS.get(s, s)}", ""]
            sec = s
        out += [f"<!-- {el} -->", body, ""]
    return "\n".join(out)


def bakery(changes: dict | None = None, drop: tuple = (), plan: str = BAKERY_PLAN, **files):
    """A Folder with the bakery plan and text; `changes` replaces or adds element paragraphs, `drop` leaves elements
    without text."""
    paras = dict(BAKERY_PARAS)
    paras.update(changes or {})
    for el in drop:
        paras.pop(el, None)
    return Folder(PLAN=plan, **{"TEXT.md": bakery_text(paras)}, **files)


def block_of(doc, element: str) -> int:
    """Index in doc.text.blocks of the first block of an element."""
    return next(i for i, b in enumerate(doc.text.blocks) if b.element == element)


def reqs_of(reqs, gate: str):
    return [r for r in reqs if r.gate == gate]


def with_gates_on(value: str) -> str:
    """The fixture GATES.md with a `gates_on:` line added."""
    return (FIXTURE / "GATES.md").read_text(encoding="utf-8").rstrip("\n") + f"\ngates_on: {value}\n"


def text_requests_truncated(test: unittest.TestCase, doc, truncated):
    """jg.text_requests with the `truncated` argument; a clean test failure while the parameter does not exist."""
    import inspect
    if "truncated" not in inspect.signature(jg.text_requests).parameters:
        test.fail("jg.text_requests has no `truncated` parameter")
    return jg.text_requests(doc, [], None, truncated=truncated)


def gate_truncated_fn(test: unittest.TestCase):
    return no_truncated.gate_truncated


NEW_TEXT_JUDGES = ("no-document-talk", "no-announcing", "no-repetition", "example-own-line", "date-tense",
                   "date-weekday", "no-truncated", "summary-faithful")


class DocumentTalkAndAnnouncing(unittest.TestCase):
    """Library line 69: no talk about the document itself, no announcing later contents — both off by default and
    switched on by `gates_on:` in GATES.md; one judge per paragraph with a flagged sentence."""

    TALK = {"S1.e1": "This report covers the bakery's morning. The ovens start before dawn. "
                     "This document also describes the shop.",
            "S1.e2": "The dough rests overnight in a cool room. In the next section we look at prices."}

    def test_off_by_default(self):
        f = bakery(self.TALK)
        try:
            g = gates_of(jg.text_requests(f.doc(), []))
            self.assertNotIn("no-document-talk", g)
            self.assertNotIn("no-announcing", g)
        finally:
            f.close()

    def test_on_gives_one_judge_per_flagged_paragraph(self):
        f = bakery(self.TALK, **{"GATES.md": with_gates_on("no-document-talk; no-announcing")})
        try:
            reqs = jg.text_requests(f.doc(), [])
            talk = reqs_of(reqs, "no-document-talk")
            ann = reqs_of(reqs, "no-announcing")
            # two talk sentences in one paragraph: still one judge for that paragraph
            self.assertEqual(len([r for r in talk if "This report covers" in r.input]), 1)
            self.assertTrue(any("This document also describes the shop" in r.input for r in talk))
            self.assertEqual(len([r for r in ann if "In the next section we look at prices" in r.input]), 1)
            # ordinary paragraphs give no judge
            for r in talk + ann:
                for plain_text in ("The shop opens at seven", "Regulars ask", "Unsold bread"):
                    self.assertNotIn(plain_text, r.input, (r.gate, r.unit))
        finally:
            f.close()

    def test_ordinary_text_gives_no_judge_when_on(self):
        f = bakery(**{"GATES.md": with_gates_on("no-document-talk; no-announcing")})
        try:
            g = gates_of(jg.text_requests(f.doc(), []))
            self.assertNotIn("no-document-talk", g)
            self.assertNotIn("no-announcing", g)
        finally:
            f.close()

    def test_one_name_switches_only_that_gate(self):
        for value, on, off in (("no-announcing", "no-announcing", "no-document-talk"),
                               ("no-document-talk", "no-document-talk", "no-announcing")):
            f = bakery(self.TALK, **{"GATES.md": with_gates_on(value)})
            try:
                g = gates_of(jg.text_requests(f.doc(), []))
                self.assertIn(on, g, value)
                self.assertNotIn(off, g, value)
            finally:
                f.close()

    def test_names_separated_by_semicolon_comma_or_space(self):
        for value in ("no-document-talk; no-announcing", "no-document-talk, no-announcing",
                      "no-document-talk no-announcing"):
            f = bakery(self.TALK, **{"GATES.md": with_gates_on(value)})
            try:
                g = gates_of(jg.text_requests(f.doc(), []))
                self.assertIn("no-document-talk", g, value)
                self.assertIn("no-announcing", g, value)
            finally:
                f.close()

    def test_unknown_gates_on_name_is_a_config_failure(self):
        # a gate that is on by default, or no gate at all, cannot be switched on: run_text names it under `config`
        for bad in ("no-hedging", "no-such-gate"):
            f = Folder(**{"BRIEF.md": polish_brief(), "GATES.md": with_gates_on(f"no-document-talk; {bad}")})
            try:
                fails, _ = run_scripts.run_text(f.doc(), [])
                cfg = [x for x in fails if x.gate == "config"]
                self.assertTrue(any(bad in x.line() for x in cfg), (bad, [x.line() for x in fails]))
            finally:
                f.close()

    def test_valid_gates_on_keeps_the_fixture_passing(self):
        f = Folder(**{"BRIEF.md": polish_brief(), "GATES.md": with_gates_on("no-document-talk; no-announcing")})
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertEqual([x.line() for x in fails], [])
        finally:
            f.close()


class Repetition(unittest.TestCase):
    """Library line 72: identical runs of 6 words in two sections; one judge per complete section after the first
    (it also looks for the same point in other words)."""

    RUN = "dough rests overnight in a cool"

    def test_one_judge_per_complete_section_after_the_first(self):
        f = bakery()
        try:
            self.assertEqual(len(reqs_of(jg.text_requests(f.doc(), []), "no-repetition")), 2)  # S2, S3; not S1
        finally:
            f.close()

    def test_six_word_run_in_a_later_section_is_quoted(self):
        # case and markup differ between the two places; the run still counts
        f = bakery({"S2.e2": "Our croissant **Dough Rests overnight** in a cool room too."})
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "no-repetition")
            self.assertEqual(len(reqs), 2)  # the hit is the later section's; the first section gets none
            self.assertTrue(any(self.RUN in docs.plain(r.input).lower() for r in reqs))
        finally:
            f.close()

    def test_incomplete_section_gets_no_judge(self):
        # S2 has no text for S2.e2 yet: no judge for S2 even with a repeated run; S3 is complete and gets one
        f = bakery({"S2.e1": "Our croissant dough rests overnight in a cool room too."}, drop=("S2.e2",))
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "no-repetition")
            self.assertEqual(len(reqs), 1)
            self.assertTrue(any("Unsold bread" in r.input for r in reqs))
        finally:
            f.close()

    def test_fixture_has_one_judge(self):
        reqs = reqs_of(jg.text_requests(docs.load(FIXTURE), []), "no-repetition")
        self.assertEqual(len(reqs), 1)  # two complete sections: only the second

    def test_run_is_found_and_quoted_as_a_hit(self):
        f = bakery({"S2.e2": "Our croissant **Dough Rests overnight** in a cool room too."})
        try:
            self.assertEqual(no_repetition.repeat_hits(f.doc()), [("S2.e2", "S1.e2", "dough rests overnight in a cool room")])
            req = [r for r in reqs_of(jg.text_requests(f.doc(), []), "no-repetition") if r.unit == "section S2"][0]
            found = req.input.split("## The text before this section")[0]
            self.assertIn("«dough rests overnight in a cool room» — here in S2.e2, earlier in S1.e2", found)
        finally:
            f.close()

    def test_same_section_repeats_only_with_a_faq_or_callout(self):
        para = "Every day the first loaves come out at six."  # 7 words shared with S1.e1
        f = bakery({"S1.e2": para})
        try:
            self.assertEqual(no_repetition.repeat_hits(f.doc()), [])  # two paragraphs of one section build on each other
        finally:
            f.close()
        f = bakery({"S1.e2": para}, plan=BAKERY_PLAN.replace("S1.e2 · paragraph", "S1.e2 · callout"))
        try:
            self.assertEqual([h[:2] for h in no_repetition.repeat_hits(f.doc())], [("S1.e2", "S1.e1")])
        finally:
            f.close()

    def test_leading_summary_is_not_text_before(self):
        # a summary at the top restates every section by design: no repetition judge sees it as the text before
        lead = "In short, the ovens start early and nothing is thrown away."
        plan = BAKERY_PLAN.replace("    - S1 · **Morning baking**", "    - S0 · **In short** · the main points · 2 lines\n"
                                   "      - S0.e1 · summary · what the reader takes away · 2 lines\n"
                                   "    - S1 · **Morning baking**")
        f = Folder(PLAN=plan, **{"TEXT.md": bakery_text({"S0.e1": lead, **BAKERY_PARAS})})
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "no-repetition")
            self.assertEqual(sorted(r.unit for r in reqs), ["section S2", "section S3"])  # S1 is the first one
            for r in reqs:
                self.assertNotIn(lead, r.input)
        finally:
            f.close()

    def test_summary_is_left_out_of_the_search(self):
        f = bakery({"S4.e1": "In short, the dough rests overnight in a cool room."}, plan=SUMMARY_PLAN)
        try:
            self.assertEqual(no_repetition.repeat_hits(f.doc()), [])
            self.assertNotIn("section S4", [r.unit for r in reqs_of(jg.text_requests(f.doc(), []), "no-repetition")])
        finally:
            f.close()


class ExampleOwnLine(unittest.TestCase):
    """Library line 74: an example that is a full sentence sits on its own line, never inside a paragraph."""

    def test_example_sentence_inside_a_paragraph(self):
        f = bakery({"S2.e1": "The shop opens at seven. For example, a regular buys rye bread before work."})
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "example-own-line")
            self.assertEqual(len(reqs), 1)
            self.assertIn("For example, a regular buys rye bread", reqs[0].input)
        finally:
            f.close()

    def test_for_instance_and_eg_inside_a_sentence(self):
        f = bakery({"S2.e1": "The shop opens at seven. Regulars buy small loaves, for instance rye rolls, "
                             "on their way to work.",
                    "S3.e1": "Unsold bread goes to a shelter nearby. Some loaves become something new, "
                             "e.g. crumbs for a soup kitchen."})
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "example-own-line")
            self.assertEqual(len(reqs), 2)  # one per paragraph
            self.assertTrue(any("for instance rye rolls" in r.input for r in reqs))
            self.assertTrue(any("crumbs for a soup kitchen" in r.input for r in reqs))
        finally:
            f.close()

    def test_example_on_its_own_line_and_plain_text_give_no_judge(self):
        f = bakery({"S2.e2": "For example, a baker opens at six."})
        try:
            self.assertEqual(reqs_of(jg.text_requests(f.doc(), []), "example-own-line"), [])
        finally:
            f.close()
        self.assertEqual(reqs_of(jg.text_requests(docs.load(FIXTURE), []), "example-own-line"), [])


class DateGates(unittest.TestCase):
    """Library line 81: tense against today's date (one judge per block with a date); date and weekday against the
    calendar (ONE judge for all date sentences, with a weekday tool)."""

    DATED = {
        "S1.e1": "The new oven arrived on 2026-03-02. It bakes many loaves at once.",
        "S1.e2": "The shop was repainted on 2 March 2026.",
        "S2.e1": "The first market stall opened on March 2, 2026.",
        "S2.e2": "The flour price rose on 02.03.2026.",
        "S3.e1": "The bakery opened in 2025. It has grown since.",
    }
    SENTENCES = ("The new oven arrived on 2026-03-02", "The shop was repainted on 2 March 2026",
                 "The first market stall opened on March 2, 2026", "The flour price rose on 02.03.2026",
                 "The bakery opened in 2025")

    def test_more_date_forms(self):
        for t in ("It moved on 2026/03/02.", "It moved on 2026.03.02.", "It moved in spring 2026.",
                  "It moved in March 2026.", "Q3 2026 is the target.", "On Monday 2.3 it moved."):
            self.assertTrue(dates.DATE.search(t), t)
        for t in ("Version 3.2 is out.", "It costs 2048 tokens.", "At 10:30 it opens.", "It may 5 times fail."):
            self.assertFalse(dates.DATE.search(t), t)

    def test_tense_one_judge_per_block_with_today(self):
        import datetime
        f = bakery(self.DATED)
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "date-tense")
            self.assertEqual(len(reqs), 5)  # every date form is found, one judge per block
            today = datetime.date.today().isoformat()
            for r in reqs:
                self.assertIn(today, r.input, r.unit)
            for s in self.SENTENCES:
                self.assertTrue(any(s in r.input for r in reqs), s)
        finally:
            f.close()

    def test_weekday_one_judge_for_all_dates_with_the_tool(self):
        f = bakery(self.DATED)
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "date-weekday")
            self.assertEqual(len(reqs), 1)
            for s in self.SENTENCES:
                self.assertIn(s, reqs[0].input)
            m = re.search(r"[^\s`'\"«»()]*weekday\.py", reqs[0].input)
            self.assertIsNotNone(m, "the input names no weekday.py tool")
            tool = Path(m.group(0))
            self.assertTrue(tool.exists() or (ROOT / tool).exists(), str(tool))
        finally:
            f.close()

    def test_no_date_no_judge(self):
        for doc_maker in (lambda: bakery(), lambda: Folder()):
            f = doc_maker()
            try:
                g = gates_of(jg.text_requests(f.doc(), []))
                self.assertNotIn("date-tense", g)
                self.assertNotIn("date-weekday", g)
            finally:
                f.close()

    def test_weekday_tool(self):
        for day, name in (("2026-11-23", "Monday"), ("2026-11-25", "Wednesday")):
            r = subprocess.run([sys.executable, str(ROOT / "gates" / "lib" / "weekday.py"), day],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(name, r.stdout, day)


class Truncated(unittest.TestCase):
    """Library line 83: a script finds sentences with no end mark or no verb, one judge per flagged paragraph."""

    def test_no_end_mark_without_spacy(self):
        f = bakery({"S1.e1": "The ovens start before dawn. The first loaves come out at six",
                    "S1.e2": "Is the dough ready? Yes! It rests overnight…",
                    "S2.e1": "The shop sells three breads:\n\n- rye bread\n- white bread\n- spelt bread"},
                   **{"BRIEF.md": polish_brief()})
        try:
            doc = f.doc()
            notes = []
            res = gate_truncated_fn(self)(doc, notes)
            i = block_of(doc, "S1.e1")
            self.assertEqual(set(res), {i})  # . ! ? : … end a sentence; list items are no sentences to end
            self.assertTrue(any("come out at six" in s for s in res[i]), res[i])
            self.assertTrue(notes, "a Polish brief: the verb part did not run, and a notice says so")
        finally:
            f.close()

    def test_paragraphs_only_not_lists_or_table_cells(self):
        # List items and table cells are never checked, only paragraphs
        f = bakery({"S2.e1": "The shop sells these breads:\n\n- rye bread\n- white bread\n- spelt bread",
                    "S2.e2": "Prices per loaf:\n\n| Bread | Price |\n|---|---|\n| Rye | 4 EUR |\n| Spelt | 5 EUR |"},
                   **{"BRIEF.md": polish_brief()})
        try:
            doc = f.doc()
            self.assertIn("table", {b.kind for b in doc.text.blocks})
            self.assertEqual(gate_truncated_fn(self)(doc, []), {})
        finally:
            f.close()

    def test_skipped_verb_part_is_called_not_run(self):
        # the hook calls a run «passed» only when no notice says a gate «did not run»
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            notes = []
            gate_truncated_fn(self)(f.doc(), notes)
            self.assertTrue(any("no-truncated" in n and "did not run" in n for n in notes), notes)
        finally:
            f.close()

    def test_hook_asks_for_the_judge(self):
        text = (FIXTURE / "TEXT.md").read_text(encoding="utf-8")
        f = Folder(**{"BRIEF.md": polish_brief(), "TEXT.md": text.replace("keeps it primed.", "keeps it primed")})
        try:
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertNotIn("SCRIPT GATES", ctx)
            self.assertIn("unslopable:gate-no-truncated", due_agents(f.path, "TEXT.md"))
        finally:
            f.close()

    def test_fixture_has_nothing_truncated_without_spacy(self):
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            self.assertEqual(gate_truncated_fn(self)(f.doc(), []), {})
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "spaCy")
    def test_verbless_sentence_with_spacy(self):
        f = bakery({"S1.e1": "The menu changes every day. A quick look at the menu. Bread always comes first."})
        try:
            doc = f.doc()
            notes = []
            res = gate_truncated_fn(self)(doc, notes)
            self.assertEqual(notes, [])
            i = block_of(doc, "S1.e1")
            self.assertEqual(set(res), {i})
            self.assertTrue(any("A quick look at the menu" in s for s in res[i]), res[i])
            self.assertFalse(any("The menu changes" in s or "Bread always" in s for s in res[i]), res[i])
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "spaCy")
    def test_fixture_has_nothing_truncated_with_spacy(self):
        notes = []
        self.assertEqual(gate_truncated_fn(self)(docs.load(FIXTURE), notes), {})
        self.assertEqual(notes, [])

    def test_one_judge_per_flagged_paragraph(self):
        f = bakery()
        try:
            doc = f.doc()
            a, b = block_of(doc, "S1.e1"), block_of(doc, "S2.e1")
            flagged = {a: ["The first loaves come out at six."], b: ["The baker serves the first customers himself."]}
            reqs = reqs_of(text_requests_truncated(self, doc, flagged), "no-truncated")
            self.assertEqual(len(reqs), 2)
            self.assertTrue(any("The first loaves come out at six" in r.input for r in reqs))
            self.assertTrue(any("The baker serves the first customers himself" in r.input for r in reqs))
            for empty in (None, {}):
                self.assertEqual(reqs_of(text_requests_truncated(self, doc, empty), "no-truncated"), [])
        finally:
            f.close()


SUMMARY_PLAN = BAKERY_PLAN.replace(
    "  - S3.e1 · paragraph · leftovers go to a shelter · facts: F5 · 3 lines\n",
    "  - S3.e1 · paragraph · leftovers go to a shelter · facts: F5 · 3 lines\n"
    "    - S4 · **In short** · the main points · 3 lines\n"
    "      - S4.e1 · summary · what the reader takes away · 3 lines\n")
SUMMARY = "In short, the bakery bakes before dawn and gives away what it cannot sell."


class SummaryFaithful(unittest.TestCase):
    """Library line 85: each summary element (by its plan kind) goes to a judge with the rest of the text, once every
    other element is written."""

    def test_plan_reads_the_summary(self):
        rows, probs = read_plan(SUMMARY_PLAN)
        self.assertEqual(probs, [])
        self.assertEqual(rows[3][-1].get("kind"), "summary")

    def test_one_judge_with_summary_and_rest(self):
        f = bakery({"S4.e1": SUMMARY}, plan=SUMMARY_PLAN)
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "summary-faithful")
            self.assertEqual(len(reqs), 1)
            self.assertEqual(reqs[0].input.count(SUMMARY), 1)  # the summary once, not again inside the rest
            for rest in ("The dough rests overnight in a cool room", "Regulars ask for their loaves",
                         "Unsold bread goes to a shelter"):
                self.assertIn(rest, reqs[0].input)
        finally:
            f.close()

    def test_waits_for_every_other_element(self):
        f = bakery({"S4.e1": SUMMARY}, drop=("S2.e2",), plan=SUMMARY_PLAN)
        try:
            self.assertEqual(reqs_of(jg.text_requests(f.doc(), []), "summary-faithful"), [])
        finally:
            f.close()

    def test_summary_without_text_gives_no_judge(self):
        f = bakery(plan=SUMMARY_PLAN)
        try:
            self.assertEqual(reqs_of(jg.text_requests(f.doc(), []), "summary-faithful"), [])
        finally:
            f.close()

    def test_every_kind_containing_summary(self):
        plan = SUMMARY_PLAN.replace("S4.e1 · summary ·", "S4.e1 · closing summary ·").replace(
            "    - S1 · **Morning baking**",
            "    - S0 · **In short** · the main points first · 2 lines\n"
            "      - S0.e1 · summary · the main points first · 2 lines\n"
            "    - S1 · **Morning baking**")
        first = "First, the bakery bakes early and wastes nothing."
        paras = {"S0.e1": first}
        paras.update(BAKERY_PARAS)
        paras["S4.e1"] = SUMMARY
        f = Folder(PLAN=plan, **{"TEXT.md": bakery_text(paras)})
        try:
            reqs = reqs_of(jg.text_requests(f.doc(), []), "summary-faithful")
            self.assertEqual(len(reqs), 2)  # `summary` and `closing summary`, one judge each
            self.assertEqual(len({r.id for r in reqs}), 2)
            for r in reqs:
                self.assertEqual(r.input.count(first), 1)
                self.assertEqual(r.input.count(SUMMARY), 1)
        finally:
            f.close()


class SlopWords(unittest.TestCase):
    """No slop words: both lists whole, the script flags, one judge per paragraph decides."""

    def test_lists_merged_whole(self):
        src, _ = slop_words.slop_list()
        self.assertIn("Kobak", src["delve"])
        self.assertIn("Antislop hand list", src["tapestry"])
        self.assertIn("Kobak", src["this"])                  # function words are not cut
        self.assertIn("Antislop words", src["nodded"])       # nor words from fiction
        self.assertIn("rasped", src)                         # «" ,rasped"» of the hand list, cleaned
        self.assertGreater(len(src), 5000)

    def test_one_judge_per_block_with_hits(self):
        f = Folder(**{"TEXT.md": "<!-- S1.e1 -->\nWe delve into a rich tapestry of options. We delve again.\n\n"
                                 "<!-- S2.1.e1 -->\nThe pump fills the tank.\n"})
        try:
            doc = f.doc()
            hits = slop_words.slop_hits(doc)
            self.assertEqual(len(hits), 1)
            words = [w.lower() for w, _ in hits[0][1]]
            self.assertIn("delve", words)
            self.assertIn("tapestry", words)
            self.assertEqual(words.count("delve"), 1)
            reqs = [r for r in jg.text_requests(doc, []) if r.gate == "slop-words"]
            self.assertEqual(len(reqs), 1)
            self.assertIn("«tapestry»", reqs[0].input)
            self.assertTrue((ROOT / "gates" / "judges" / "gate-slop-words.md").exists())
        finally:
            f.close()


class Idiosyncrasies(unittest.TestCase):
    """The seven idiosyncrasies of Chakrabarty et al. (CHI 2025), one judge per kind."""

    def test_six_judges_per_element_with_an_agent_each(self):
        f = Folder(**{"TEXT.md": "<!-- S1.e1 -->\nThe tool reads the file.\n\n- one item\n- another item\n\n"
                                 "<!-- S2.1.e1 -->\nIt writes the log.\n"})
        try:
            reqs = jg.idiosyncrasy_requests(f.doc())
            self.assertEqual(len(reqs), 12)
            self.assertEqual({r.gate for r in reqs}, set(jg.IDIOSYNCRASIES))
            first = [r for r in reqs if "S1.e1" in r.unit]
            self.assertEqual(len(first), 6)
            self.assertIn("one item", first[0].input)          # the list is part of its element's text
            self.assertNotIn("writes the log", first[0].input)
            self.assertTrue({r.id for r in reqs} <= {r.id for r in jg.text_requests(f.doc(), [])})
            for g in list(jg.IDIOSYNCRASIES) + ["tense-shift"]:
                self.assertTrue((ROOT / "gates" / "judges" / f"gate-{g}.md").exists(), g)
        finally:
            f.close()

    def test_no_tense_judge_without_marks(self):
        f = Folder()
        try:
            self.assertEqual([r for r in jg.idiosyncrasy_requests(f.doc()) if r.gate == "tense-shift"], [])
        finally:
            f.close()

    def test_tense_not_english_is_a_notice(self):
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            notes = []
            self.assertEqual(tense_shift.gate_tense(f.doc(), notes), {})
            self.assertTrue(any("tense-shift" in n and "did not run" in n for n in notes))
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "SKIP_SPACY=1")
    def test_tense_shift_goes_to_a_judge(self):
        f = Folder(**{"TEXT.md": "<!-- S1.e1 -->\nThe tool reads the file. It then checked the header.\n\n"
                                 "<!-- S2.1.e1 -->\nThe tool reads the file. It then checks the header.\n"})
        try:
            notes = []
            doc = f.doc()
            marks = tense_shift.gate_tense(doc, notes)
            self.assertEqual(notes, [])
            self.assertEqual([doc.text.blocks[i].element for i in marks], ["S1.e1"])
            reqs = [r for r in jg.text_requests(doc, [], None, marks) if r.gate == "tense-shift"]
            self.assertEqual(len(reqs), 1)
            self.assertIn("«checked» past", reqs[0].input)
            self.assertIn("«reads» present", reqs[0].input)
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "SKIP_SPACY=1")
    def test_tense_rules(self):
        res = tense_shift.parse_tense([["It will stop.", "It won't log.", "It can stop.", "It does not retry.",
                               "It was released.", "It has changed."]])[0]
        self.assertEqual([[(c["verb"], c["tense"]) for c in s] for s in res],
                         [[("will stop", "future")], [("won't log", "future")], [],
                          [("does not retry", "present")], [("was released", "past")],
                          [("has changed", "present")]])

    def test_purpose_from_the_plan_for_two_judges(self):
        f = Folder()
        try:
            reqs = [r for r in jg.idiosyncrasy_requests(f.doc()) if "S1.e1" in r.unit]
            with_plan = {r.gate for r in reqs if "from the plan" in r.input}
            self.assertEqual(with_plan, set(jg.PURPOSE_GATES))
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "SKIP_SPACY=1")
    def test_hook_asks_the_tense_judge(self):
        f = Folder()
        try:
            t = f.path / "TEXT.md"
            t.write_text(t.read_text().replace("Only that switch decides when the pump starts",
                                               "Only that switch decided when the pump started"))
            doc, notes = f.doc(), []
            fails, cands = run_scripts.run_text(doc, notes)
            self.assertEqual(fails, [])
            reqs = jg.text_requests(doc, cands, cohesion.gate_cohesion(doc, notes), tense_shift.gate_tense(doc, notes))
            self.assertIn("tense-shift", {r.gate for r in reqs})
            (f.path / ".gates").mkdir()
            (f.path / ".gates" / "verdicts.json").write_text(json.dumps(
                {r.id: {"verdict": "PASSED"} for r in reqs if r.gate != "tense-shift"}))
            ctx = hook_ctx(t)
            self.assertIn("Judges due now: 1.", ctx)
            self.assertEqual(due_agents(f.path, "TEXT.md"), ["unslopable:gate-tense-shift"])
        finally:
            f.close()


class NewTextGatesOnFixture(unittest.TestCase):
    """The fixture document stays clean for the new gates, and every new judge has its agent file."""

    def test_fixture_gives_no_new_judge(self):
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            doc = f.doc()
            notes = []
            fails, _ = run_scripts.run_text(doc, notes)
            self.assertEqual([x.line() for x in fails], [])
            truncated = gate_truncated_fn(self)(doc, [])
            g = gates_of(text_requests_truncated(self, doc, truncated))
            for gate in ("no-document-talk", "no-announcing", "example-own-line", "date-tense", "date-weekday",
                         "no-truncated", "summary-faithful"):
                self.assertNotIn(gate, g)
        finally:
            f.close()

    def test_every_new_judge_has_an_agent_file(self):
        for g in NEW_TEXT_JUDGES:
            self.assertTrue((ROOT / "gates" / "judges" / f"gate-{g}.md").exists(), g)


# ---------------------------------------------------------------- tables and tiles (library «Tables and blocks»)

TILES_PLAN_KIND = ("S2.2.e1 · list · who can change them", "S2.2.e1 · tiles · the plans a team can pick")
TILES_TEXT = """
# Doc

## Settings that protect the pump

### Low water cutoff

<!-- S2.1.e1 -->
A team picks one of two plans before it starts.

| Plan | Price | Seats |
| --- | --- | --- |
| Basic | 5 EUR | 3 |
| Pro | 20 EUR | 10 |

Prices exclude VAT.

### Pressure limits

<!-- S2.2.e1 -->
A team chooses how it pays for the service.

- **Monthly:** the team pays each month and can stop at any time.
- **Yearly:** the team pays once a year at a lower price.
"""


class TablesAndTiles(unittest.TestCase):
    """Tables and tiles (library «Tables and blocks»): tiles are a list under a `tiles` plan element."""

    def folder(self, text: str = TILES_TEXT, kind: bool = True) -> Folder:
        plan = (FIXTURE / "PLAN.md").read_text()
        if kind:
            plan = plan.replace(*TILES_PLAN_KIND)
        return Folder(PLAN=plan, **{"TEXT.md": text, "BRIEF.md": polish_brief()})

    def blocks(self, f: Folder, kind: str):
        return [b for b in f.doc().text.blocks if b.kind == kind]

    def test_tiles_get_the_slop_idiosyncrasy_and_document_talk_gates(self):
        # tiles were a list before the tables gates; the gates that read lists must read tiles too
        text = TILES_TEXT.replace("at a lower price.", "at a lower price, a testament to this document's tapestry.")
        f = Folder(PLAN=(FIXTURE / "PLAN.md").read_text().replace(*TILES_PLAN_KIND),
                   **{"GATES.md": with_gates_on("no-document-talk"), "TEXT.md": text, "BRIEF.md": polish_brief()})
        try:
            doc = f.doc()
            i = next(k for k, b in enumerate(doc.text.blocks) if b.kind == "tiles")
            self.assertIn(i, [k for k, _ in slop_words.slop_hits(doc)])
            reqs = jg.text_requests(doc, [])
            self.assertEqual(len([r for r in reqs if r.gate == "slop-words" and "tapestry" in r.input]), 1)
            idio = [r for r in reqs if r.gate in jg.IDIOSYNCRASIES and "tapestry" in r.input]
            self.assertEqual(len(idio), 6)
            self.assertIn(i, [k for k, _ in common.flagged_paragraphs(doc, "no-document-talk", no_document_talk.DOCUMENT_TALK)])
        finally:
            f.close()

    def test_a_list_under_a_tiles_element_is_tiles(self):
        f = self.folder()
        try:
            (t,) = self.blocks(f, "tiles")
            self.assertEqual(t.titles, ["Monthly", "Yearly"])
            self.assertEqual(docs.tile_parts(t.items[1]), ("Yearly", "the team pays once a year at a lower price."))
        finally:
            f.close()
        f = self.folder(kind=False)
        try:
            self.assertEqual(self.blocks(f, "tiles"), [])
            self.assertEqual(len(self.blocks(f, "list")), 1)
        finally:
            f.close()

    def test_tiles_format(self):
        f = self.folder()
        try:
            self.assertEqual(formats.tiles_format(f.doc()), [])
        finally:
            f.close()
        for broken, why in (("- the", "no title"), ("- **Yearly: the team pays once a year.**", "no body")):
            f = self.folder(TILES_TEXT.replace("- **Yearly:** the team pays once a year at a lower price.", broken))
            try:
                fails = formats.tiles_format(f.doc())
                self.assertEqual(gates_of(fails), ["format"], broken)
                self.assertIn("tile 2", fails[0].where)
                self.assertIn(why, fails[0].why)
            finally:
                f.close()
        written_as_paragraph = TILES_TEXT.split("<!-- S2.2.e1 -->")[0] + "<!-- S2.2.e1 -->\nMonthly or yearly.\n"
        f = self.folder(written_as_paragraph)
        try:
            self.assertEqual(gates_of(formats.tiles_format(f.doc())), ["format"])
        finally:
            f.close()

    def test_tiles_are_units_and_are_led_in(self):
        f = self.folder()
        try:
            doc = f.doc()
            self.assertIn("tile", {u.kind for u in common.body_units(doc.text.blocks)})
            self.assertEqual(list_lead_in.gate_list_lead_in(doc), [])
            reqs = [r for r in jg.text_requests(doc, []) if r.gate == "list-lead-in"]
            self.assertEqual(len(reqs), 2)
            self.assertTrue(any("## The tiles" in r.input for r in reqs))
        finally:
            f.close()

    def test_a_tile_is_one_sentence(self):
        f = self.folder(TILES_TEXT.replace("at a lower price.", "at a lower price. It saves money."))
        try:
            fails = one_sentence_per_item.gate_one_sentence_per_item(f.doc())
            self.assertEqual(gates_of(fails), ["one-sentence-per-item"])
            self.assertIn("a tile with 2 sentences", fails[0].why)
        finally:
            f.close()

    def test_footnote_look_alikes_pass(self):
        f = self.folder(TILES_TEXT.replace("| Basic | 5 EUR | 3 |", "| ***Basic*** | 2 * 3 EUR | 3 ft² |")
                        .replace("| Pro | 20 EUR | 10 |", "| Pro | 20 \\*EUR | 10 s⁻¹ |"))
        try:
            self.assertEqual(table_footnote.gate_table_footnotes(f.doc()), [])
        finally:
            f.close()

    def test_no_footnote_marks(self):
        f = self.folder(TILES_TEXT.replace("| Pro | 20 EUR |", "| Pro* | 20 EUR† |")
                        .replace("| Basic | 5 EUR |", "| **Basic** | 5 m² `a*b` |"))
        try:
            fails = table_footnote.gate_table_footnotes(f.doc())
            self.assertEqual([x.quote for x in fails], ["Pro*", "20 EUR†"])
            self.assertEqual(set(gates_of(fails)), {"table-footnote"})
        finally:
            f.close()

    def test_no_duplicate_row_labels(self):
        f = self.folder(TILES_TEXT.replace("| Pro | 20 EUR | 10 |", "| Pro | 20 EUR | 10 |\n| **Extras** | | |\n"
                                           "| basic | 7 EUR | 3 |"))
        try:
            fails = table_duplicate_row.gate_table_duplicate_rows(f.doc())
            self.assertEqual(gates_of(fails), ["table-duplicate-row"])
            self.assertIn("row 2", fails[0].why)
        finally:
            f.close()
        f = self.folder(TILES_TEXT.replace("| Pro | 20 EUR | 10 |", "| Pro | 20 EUR | 10 |\n| **Extras** | | |\n"
                                           "| **Extras** | | |"))
        try:
            self.assertEqual(table_duplicate_row.gate_table_duplicate_rows(f.doc()), [])  # mini header rows are not data rows
        finally:
            f.close()

    def test_only_two_dimensional_data(self):
        f = self.folder(TILES_TEXT.replace("| Basic | 5 EUR | 3 |", "| Basic | 5 EUR<br>7 EUR | 3 |")
                        .replace("| Pro | 20 EUR | 10 |", "| Pro | 20 EUR | email, phone, chat |"))
        try:
            doc = f.doc()
            self.assertEqual(gates_of(table_flat.gate_table_flat(doc)), ["table-flat"])
            (req,) = [r for r in jg.text_requests(doc, []) if r.gate == "table-flat"]
            self.assertIn("«email, phone, chat»", req.input)
            self.assertNotIn("«5 EUR", req.input)  # failed by the script, not sent to the judge
        finally:
            f.close()
        f = self.folder(TILES_TEXT.replace("| Basic | 5 EUR | 3 |", "| Basic | 09:00 - 17:00, Mon - Fri | 3 |")
                        .replace("| Pro | 20 EUR | 10 |", "| Pro | 20 EUR | `a-*`, `*-b`, `c` |"))
        try:
            doc = f.doc()
            self.assertEqual(table_flat.gate_table_flat(doc), [])  # spaced hyphens are not bullets
            (req,) = [r for r in jg.text_requests(doc, []) if r.gate == "table-flat"]
            self.assertIn("«`a-*`, `*-b`, `c`»", req.input)  # the judge quotes the raw cell
        finally:
            f.close()

    def test_yes_no_column_goes_to_a_judge(self):
        f = self.folder()
        try:
            self.assertEqual(yes_no_grid.yes_no_columns(f.doc()), [])
        finally:
            f.close()
        f = self.folder(TILES_TEXT.replace("| Seats |", "| Can export? |").replace("| 3 |", "| ✗ |")
                        .replace("| 10 |", "| Yes, after review |"))
        try:
            doc = f.doc()
            self.assertEqual([c for _, c in yes_no_grid.yes_no_columns(doc)], [["Can export?"]])
            (req,) = [r for r in jg.text_requests(doc, []) if r.gate == "yes-no-grid"]
            self.assertIn("- Can export?", req.input)
        finally:
            f.close()
        f = self.folder(TILES_TEXT.replace("| Seats |", "| Export |").replace("| 3 |", "| ✗ |")
                        .replace("| 10 |", "| ✓ |"))
        try:
            self.assertEqual(yes_no_grid.yes_no_columns(f.doc()), [])  # already a tick grid
        finally:
            f.close()

    def test_judges_per_block(self):
        f = self.folder()
        try:
            reqs = jg.text_requests(f.doc(), [])
            by = {}
            for r in reqs:
                by.setdefault(r.gate, []).append(r)
            self.assertEqual([r.unit.split(" at ")[0] for r in by["cell-answers-header"]], ["table"])
            self.assertEqual(sorted(r.unit.split(" at ")[0] for r in by["same-kind"]), ["table", "tiles"])
            self.assertEqual([r.unit.split(" at ")[0] for r in by["tiles-choice"]], ["tiles"])
            self.assertIn("A team chooses how it pays", by["tiles-choice"][0].input)
            hidden = {r.unit.split(" at ")[0]: r.input for r in by["no-hidden-fact"]}
            self.assertEqual(sorted(hidden), ["table", "tiles"])
            self.assertIn("Prices exclude VAT.", hidden["table"])
            self.assertIn("(none: nothing follows it", hidden["tiles"])
            ext = {r.unit.split(" at ")[0]: r.input for r in by["external-items"]}
            self.assertEqual(sorted(ext), ["table", "tiles"])
            self.assertIn("| Basic | 5 EUR | 3 |", ext["table"])
            self.assertIn("pressure switch — explain", ext["table"])          # the whole TERMS.md
            self.assertIn("A team picks one of two plans", ext["table"])       # the text before the block
            self.assertIn("| Pro | 20 EUR | 10 |", ext["tiles"])
            for g in ("cell-answers-header", "yes-no-grid", "table-flat", "same-kind", "tiles-choice",
                      "no-hidden-fact", "external-items"):
                self.assertTrue((ROOT / "gates" / "judges" / f"gate-{g}.md").exists(), g)
        finally:
            f.close()

    def test_run_text_runs_the_table_scripts(self):
        f = self.folder(TILES_TEXT.replace("| Pro | 20 EUR |", "| Pro* | 20 EUR |").replace("- **Yearly:** the", "- the"))
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertTrue({"table-footnote", "format"} <= set(gates_of(fails)))
        finally:
            f.close()


# ---------------------------------------------------------------- figures (library «Figures, images, screenshots»)

import figure_files  # noqa: E402
import figure_gates  # noqa: E402
import figure_steps  # noqa: E402
import screenshot_margin  # noqa: E402

CAN_RENDER = bool(figure_files._which("rsvg-convert") or figure_files._which("qlmanage"))


def png_bytes(w: int = 8, h: int = 8, seed: int = 0) -> bytes:
    """A small valid RGB PNG; a different seed gives a different picture."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(((x * 37 + y * 91 + seed * 53) % 256) for x in range(w * 3)) for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def svg(*labels: str, title: str = "One request's path", dashed: bool = False) -> str:
    texts = "".join(f'<text x="10" y="{20 + 20 * k}">{lb}</text>' for k, lb in enumerate(labels))
    dash = '<line x1="0" y1="0" x2="50" y2="0" stroke="#E07A00" stroke-dasharray="4 2"/>' if dashed else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="200" height="200">'
            f'<title>{title}</title><rect x="0" y="0" width="80" height="40" fill="#12A98D"/>{dash}{texts}</svg>')


def bash_payload(folder: Path, command: str) -> dict:
    d = recorded(folder / "x")
    d.update(tool_name="Bash", tool_input={"command": command}, cwd=str(folder))
    return d


def judge_input(folder: Path, gate: str) -> str:
    ins = sorted((folder / ".gates" / "inputs").glob(f"{gate}-*.md"))
    assert ins, f"no input for {gate}"
    return ins[-1].read_text()


class FigureFiles(unittest.TestCase):
    """Gates on the figure file itself (decision D7): they run when the file is written."""

    def test_which_file_is_a_figure(self):
        f = Folder()
        try:
            (f.path / "figures" / "sub").mkdir(parents=True)
            real = Path(os.path.realpath(f.path))
            self.assertEqual(figure_files.figure_file(str(real / "figures" / "a.svg")), (real, "figures/a.svg"))
            self.assertEqual(figure_files.figure_file(str(real / "figures" / "sub" / "b.PNG")), (real, "figures/sub/b.PNG"))
            self.assertIsNone(figure_files.figure_file(str(real / "figures" / "notes.md")))
            self.assertIsNone(figure_files.figure_file(str(real / "fig1.png")))  # not under figures/
            (f.path / "BRIEF.md").unlink()
            self.assertIsNone(figure_files.figure_file(str(real / "figures" / "a.svg")))
        finally:
            f.close()

    def test_a_written_svg_gets_the_marks_judge_with_its_image(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            p = f.path / "figures" / "S1.e2.svg"
            p.write_text(svg("pressure switch", "check valve", dashed=True))
            ctx = hook_ctx(p)
            self.assertIn("unslopable gates on the figure figures/S1.e2.svg", ctx)
            self.assertIn("cannot start a subagent", ctx)  # then the illustrator passes the runner block on
            self.assertIn("START ONE AGENT NOW", ctx)
            self.assertIn("file: figures/S1.e2.svg", ctx)
            self.assertIn("unslopable:gate-figure-marks", due_agents(f.path, "figures/S1.e2.svg"))
            self.assertNotIn("unslopable:gate-screenshot-cropped", due_agents(f.path, "figures/S1.e2.svg"))
            inp = judge_input(f.path, "figure-marks")
            self.assertIn("S1.e2 (figure): the path of the water", inp)  # the plan element, by the file's id
            self.assertIn("One request's path", inp)  # the caption: the SVG's title before the text has it
            self.assertIn("dashed lines: yes", inp)
            self.assertIn("#E07A00", inp)
            self.assertIn("Only that switch decides", inp)  # the text so far
            if CAN_RENDER:
                self.assertIn("(read this image)", inp)
                self.assertTrue(list((f.path / ".gates" / "renders").glob("figures__S1.e2.svg.*.png")))
            req = json.loads((f.path / ".gates" / "requests.json").read_text())
            self.assertTrue(any(v["file"].endswith("figures/S1.e2.svg") for v in req.values()))
            # the same file again: the judge's verdict stands
            pass_every_judge(f.path)
            self.assertIn("Every gate passed on the figure figures/S1.e2.svg", hook_ctx(p, tool="Edit"))
        finally:
            f.close()

    def test_an_svg_that_does_not_parse_fails(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            p = f.path / "figures" / "S1.e2.svg"
            p.write_text("<svg><text>open")
            ctx = hook_ctx(p)
            self.assertIn("SCRIPT GATES — NOT PASSED (1)", ctx)
            self.assertIn("the SVG does not parse", ctx)
            self.assertNotIn("Judges due now", ctx)
        finally:
            f.close()

    def test_a_screenshot_copied_by_bash_is_gated_once(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            self.assertIsNone(run_hook(bash_payload(f.path, "ls -la")))  # no `figures` in the command
            (f.path / "figures" / "panel.png").write_bytes(png_bytes())
            ctx = hook_ctx_of(bash_payload(f.path, "cp ~/Desktop/shot.png figures/panel.png"))
            self.assertIn("figures/panel.png", ctx)
            self.assertIn("`manual: yes|no`", ctx)  # the gates stage has not said whether this is a manual
            gates = (f.path / "GATES.md").read_text()
            (f.path / "GATES.md").write_text(gates + "manual: yes\n")
            self.assertIsNone(run_hook(recorded(f.path / "GATES.md")))  # GATES.md is not gated
            # the same bytes copied again still count: the figure failed, so it is gated again
            ctx = hook_ctx_of(bash_payload(f.path, "ls figures"))
            self.assertIn("unslopable:gate-screenshot-cropped", due_agents(f.path, "figures/panel.png"))
            self.assertIn("unslopable:gate-figure-marks", due_agents(f.path, "figures/panel.png"))
            self.assertIn(str(f.path / "figures" / "panel.png"), judge_input(f.path, "screenshot-cropped"))
            # nothing changed since: a later command that names figures is silent
            self.assertIsNone(run_hook(bash_payload(f.path, "ls figures")))
            (f.path / "figures" / "panel.png").write_bytes(png_bytes(seed=3))  # a new crop
            (f.path / "GATES.md").write_text(gates + "manual: no\n")
            ctx = hook_ctx_of(bash_payload(f.path, f"cp /tmp/x.png {f.path}/figures/panel.png"))
            self.assertNotIn("unslopable:gate-screenshot-cropped", due_agents(f.path, "figures/panel.png"))
            self.assertIn("unslopable:gate-figure-marks", due_agents(f.path, "figures/panel.png"))
        finally:
            f.close()

    def test_a_long_bash_command_with_no_gated_file_is_silent(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            (f.path / "figures" / "panel.png").write_bytes(png_bytes())  # a new figure, not gated yet
            long_word = "figures" + "x" * 5000  # longer than a file name may be
            commands = [
                f"cat <<'EOF' > notes.md\n{long_word}\nthe figures of the report\nEOF",
                f"echo {'a' * 300}/figures/b.png",
                "python3 make_figures.py --title 'the figures of the report'",
            ]
            for command in commands:
                self.assertIsNone(run_hook(bash_payload(f.path, command)), command[:60])
            # a command that does name the figures still gates the new figure
            self.assertIn("figures/panel.png", hook_ctx_of(bash_payload(f.path, "ls figures/")))
        finally:
            f.close()

    def test_a_bash_command_that_names_a_figure_path_finds_its_folder(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            cwd, doc = str(f.path), [Path(os.path.realpath(f.path))]
            named = [
                "uv run --with pillow python - <<'EOF'\nfrom PIL import Image\n"
                "Image.open('figures/shot.png').crop((0, 0, 9, 9)).save('figures/shot.png')\nEOF",
                "cat <<'EOF' > figures/a.svg\n<svg/>\nEOF",
                "ls figures; echo done",
                "echo $(ls figures)",
                "cat <<< hello\nls figures/",
                "echo $((1<<2))\nls figures/",
                'echo "a <<EOF"\ncp x.png figures/x.png',
                "cp x.png $PWD/figures/x.png",
                "cp x.png ${PWD}/figures/x.png",
                "make 2>figures/log.txt",
                "cd figures && magick a.svg a.png",
            ]
            for command in named:
                self.assertEqual(figure_files.bash_folders(command, cwd), doc, command)
            # a bare word in a here-document's body is data, not a path, whatever the end word looks like
            for start, end in (("<<'EOF'", "EOF"), ("<<\\EOF", "EOF"), ("<<'END-X'", "END-X"), ('<<"a.txt"', "a.txt")):
                command = f"cat {start} > notes.md\nthe figures\nfigures\n{end}"
                self.assertEqual(figure_files.bash_folders(command, cwd), [], command)
            # run inside `figures/`, a prose word or a word too long for a file name is still no path
            inside = str(f.path / "figures")
            for command in ("echo 'the figures of the report'", "echo figures" + "x" * 5000):
                self.assertEqual(figure_files.bash_folders(command, inside), [], command[:40])
            self.assertEqual(figure_files.bash_folders("ls ../figures", inside), doc)
        finally:
            f.close()

    def test_a_generated_image_needs_its_prompt_and_references(self):
        f = Folder(PLAN=fixture_plan().replace("figure · the path of the water",
                                               "figure · a generated image hero.png of one request"))
        try:
            (f.path / "figures").mkdir()
            img = f.path / "figures" / "hero.png"
            img.write_bytes(png_bytes(seed=1))
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: no\n")
            ctx = hook_ctx_of(bash_payload(f.path, "imagegen --out figures/hero.png 'one request'"))
            self.assertIn("[generated-image]", ctx)
            self.assertIn("hero.prompt.md is missing", ctx)
            prompt = f.path / "figures" / "hero.prompt.md"
            prompt.write_text(
                "## Prompt\nA flat drawing of one request crossing a garden.\n\n## Style\nFlat, two colours.\n\n"
                "## References\n- `figures/ref/style.png`\n")
            ctx = hook_ctx(prompt)  # writing the prompt file gates its image
            self.assertIn("names a reference image that does not exist", ctx)
            (f.path / "figures" / "ref").mkdir()
            (f.path / "figures" / "ref" / "style.png").write_bytes(png_bytes(seed=2))
            ctx = hook_ctx_of(bash_payload(f.path, "cp ~/style.png figures/ref/style.png"))
            self.assertIn("unslopable:gate-generated-image", due_agents(f.path))
            self.assertNotIn("unslopable:gate-screenshot-cropped", due_agents(f.path))
            inp = judge_input(f.path, "generated-image")
            self.assertIn("crossing a garden", inp)
            self.assertIn("Flat, two colours", inp)
            self.assertIn("figures/ref/style.png", inp)
            self.assertIn("similarity to the generated image", inp)
            self.assertIn("figures/ref/style.png", ctx)  # the new reference is a figure file too, gated on its own
        finally:
            f.close()

    def test_the_runner_reports_on_a_figure(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            p = f.path / "figures" / "S1.e2.svg"
            p.write_text(svg("pressure switch"))
            hook_ctx(p)
            pass_every_judge(f.path)
            self.assertEqual(runner("next", f.path, "figures/S1.e2.svg"), "NONE")
            self.assertEqual(runner("report", f.path, "figures/S1.e2.svg"), "PASSED")
            self.assertTrue((f.path / ".gates" / "report-figures_S1.e2.svg.md").exists())
        finally:
            f.close()

    def test_the_marks_judge_sees_what_the_text_around_will_say(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            p = f.path / "figures" / "S1.e2.svg"
            p.write_text(svg("pressure switch"))
            hook_ctx(p)
            inp = judge_input(f.path, "figure-marks")
            self.assertIn("S1.e3 (paragraph): the valve keeps the pump primed", inp)
        finally:
            f.close()

    def test_a_documents_own_gate_can_target_figure_files(self):
        f = Folder()
        try:
            c = f.path / ".gates" / "custom"
            c.mkdir(parents=True)
            (c / "text_size.py").write_text(
                "# figures/*.svg: text in a drawn figure is at least 9 px\n"
                "import sys\nprint(sys.argv[2].split('/')[-1] + ' — a label at 6 px')\n"
                "print('CHECK: the legend — may be too small')\n")
            (c / "text_size.md").write_text("Text in a figure is readable as printed.")
            (c / "on_text.py").write_text("# TEXT.md: about figures/ in the text\nprint('should not run')\n")
            fails, reqs = figure_gates.custom_figure_gates(f.path, "figures/a.svg")
            self.assertEqual([x.why for x in fails], ["a.svg — a label at 6 px"])
            self.assertEqual([r.agent for r in reqs], ["unslopable:gate-custom"])
            self.assertIn("may be too small", reqs[0].input)
            self.assertIn("figures/a.svg", reqs[0].input)
            self.assertEqual(figure_gates.custom_figure_gates(f.path, "figures/shot.png"), ([], []))  # *.svg only
            self.assertFalse(figure_gates._targets("# configures the export", "figures/a.svg"))
            import importlib.util
            spec = importlib.util.spec_from_file_location("gate_run_mod2", HOOK)
            gr = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(gr)
            fails, _ = gr.custom_gates(f.path, "TEXT.md", common.Failure, jg.JudgeRequest)
            self.assertEqual([x.why for x in fails], ["should not run"])  # the figure gate is not a TEXT.md gate
            # and the hook runs it on a figure write
            (f.path / "figures").mkdir()
            (f.path / "figures" / "a.svg").write_text(svg("pressure switch"))
            ctx = hook_ctx(f.path / "figures" / "a.svg")
            self.assertIn("[custom:text_size]", ctx)
        finally:
            f.close()

    def test_every_figure_gate_has_its_judge(self):
        for g in ("figure-marks", "figure-steps", "figure-labels", "screenshot-cropped", "screenshot-margin",
                  "generated-image"):
            self.assertTrue((ROOT / "gates" / "judges" / f"gate-{g}.md").exists(), g)


def shot_png(w: int, h: int, box: tuple[int, int, int, int], bg=(255, 255, 255, 255), ink=(30, 30, 30, 255),
             frame=None, more=()) -> bytes:
    """An RGBA PNG of `bg` with a filled rectangle `box` = (left, top, right, bottom), right and bottom excluded: a
    screenshot whose content is that rectangle. `frame`: a colour for the outermost ring of pixels (a card cropped
    exactly along its 1-px border). `more`: other rectangles filled with `ink`."""
    import struct
    import zlib
    boxes = [box, *more]

    def colour(x: int, y: int) -> tuple:
        if frame and (x in (0, w - 1) or y in (0, h - 1)):
            return frame
        return ink if any(l <= x < r and t <= y < b for l, t, r, b in boxes) else bg
    raw = b"".join(b"\x00" + b"".join(bytes(colour(x, y)) for x in range(w)) for y in range(h))

    def chunk(k: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


NEEDS_UV = unittest.skipUnless(figure_files._which("uv"), "the margin is measured under uv with Pillow")


class ScreenshotMargin(unittest.TestCase):
    """screenshot-margin: every screenshot keeps a band of background on every side; a script measures
    it, a judge looks where a side is too thin."""

    def gate(self, f: Folder, name: str, data: bytes) -> list[str]:
        (f.path / "figures").mkdir(exist_ok=True)
        (f.path / "figures" / name).write_bytes(data)
        hook_ctx_of(bash_payload(f.path, f"cp ~/shot.png figures/{name}"))
        return due_agents(f.path, f"figures/{name}")

    def test_the_least_band(self):
        self.assertEqual(screenshot_margin.margin_min(100, 80), 8)        # small image: 8 px
        self.assertEqual(screenshot_margin.margin_min(1600, 1000), 20)    # 2% of the shorter side
        self.assertEqual(screenshot_margin.margin_min(3000, 200), 8)

    @NEEDS_UV
    def test_a_screenshot_with_a_margin_passes_on_the_script(self):
        f = Folder()
        try:
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: no\n")
            agents = self.gate(f, "card.png", shot_png(100, 80, (20, 15, 80, 65)))
            self.assertNotIn("unslopable:gate-screenshot-margin", agents)
            self.assertIn("unslopable:gate-figure-marks", agents)  # the other gates still run
            m = screenshot_margin.measure_margin(f.path, "figures/card.png", [])
            self.assertEqual(m["bands"], {"top": 15, "right": 20, "bottom": 15, "left": 20})
            # a transparent margin counts as background
            agents = self.gate(f, "clear.png", shot_png(100, 80, (20, 15, 80, 65), bg=(0, 0, 0, 0)))
            self.assertNotIn("unslopable:gate-screenshot-margin", agents)
        finally:
            f.close()

    @NEEDS_UV
    def test_content_at_an_edge_goes_to_the_judge_in_every_document(self):
        f = Folder()
        try:
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: no\n")  # not a manual
            agents = self.gate(f, "flush.png", shot_png(100, 80, (20, 0, 80, 65)))  # the card runs into the top
            self.assertIn("unslopable:gate-screenshot-margin", agents)
            inp = judge_input(f.path, "screenshot-margin")
            self.assertIn(str(f.path / "figures" / "flush.png"), inp)
            self.assertIn("top 0 px, right 20 px, bottom 15 px, left 20 px", inp)
            self.assertIn("least band this gate asks for is 8 px", inp)
            # a band thinner than the least, though not zero, goes to the judge too
            self.assertIn("unslopable:gate-screenshot-margin",
                          self.gate(f, "thin.png", shot_png(100, 80, (3, 15, 80, 65))))
        finally:
            f.close()

    @NEEDS_UV
    def test_a_crop_along_a_light_frame_goes_to_the_judge(self):
        f = Folder()
        try:
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: no\n")
            # a white card with a 1-px light grey border exactly at the image's edge, content inside
            card = shot_png(100, 80, (30, 25, 70, 55), frame=(238, 238, 238, 255))
            self.assertIn("unslopable:gate-screenshot-margin", self.gate(f, "framed.png", card))
            self.assertIn("top 1 px, right 1 px, bottom 1 px, left 1 px", judge_input(f.path, "screenshot-margin"))
        finally:
            f.close()

    @NEEDS_UV
    def test_a_hairline_running_into_an_edge_goes_to_the_judge(self):
        f = Folder()
        try:
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: no\n")
            # a wide card 20 px below the top, and a 1-px rule from it up to the top edge
            data = shot_png(1200, 120, (100, 20, 1100, 100), more=[(600, 0, 601, 20)])
            self.assertIn("unslopable:gate-screenshot-margin", self.gate(f, "rule.png", data))
            self.assertIn("top 0 px", judge_input(f.path, "screenshot-margin"))
        finally:
            f.close()

    @NEEDS_UV
    def test_a_bad_cache_entry_is_measured_again(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            (f.path / "figures" / "card.png").write_bytes(shot_png(100, 80, (20, 15, 80, 65)))
            (f.path / ".gates").mkdir(exist_ok=True)
            key = f"{screenshot_margin.MARGIN_VERSION}:{figure_files._sha(f.path / 'figures' / 'card.png')}"
            (f.path / ".gates" / "margins.json").write_text(json.dumps({key: {"bands": {}}}))
            notices: list = []
            self.assertEqual(screenshot_margin.gate_screenshot_margin(f.doc(), "figures/card.png", notices), [])
            self.assertEqual(notices, [])
        finally:
            f.close()

    @NEEDS_UV
    def test_in_a_manual_both_screenshot_gates_run(self):
        f = Folder()
        try:
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: yes\n")
            agents = self.gate(f, "flush.png", shot_png(100, 80, (0, 15, 80, 65)))
            self.assertIn("unslopable:gate-screenshot-margin", agents)
            self.assertIn("unslopable:gate-screenshot-cropped", agents)
        finally:
            f.close()

    def test_drawn_diagrams_and_generated_images_are_not_screenshots(self):
        f = Folder()
        try:
            (f.path / "GATES.md").write_text((f.path / "GATES.md").read_text() + "manual: no\n")
            (f.path / "figures").mkdir()
            p = f.path / "figures" / "S1.e2.svg"
            p.write_text(svg("pressure switch"))  # its box runs into the top-left corner
            hook_ctx(p)
            self.assertNotIn("unslopable:gate-screenshot-margin", due_agents(f.path, "figures/S1.e2.svg"))
            (f.path / "figures" / "hero.prompt.md").write_text("## Prompt\nOne request.\n\n## Style\nFlat.\n")
            agents = self.gate(f, "hero.png", shot_png(100, 80, (0, 0, 100, 80)))
            self.assertNotIn("unslopable:gate-screenshot-margin", agents)
        finally:
            f.close()

    def test_an_image_nothing_could_measure_goes_to_the_judge(self):
        f = Folder()
        try:
            (f.path / "figures").mkdir()
            (f.path / "figures" / "broken.png").write_bytes(b"not an image")
            notices: list = []
            reqs = screenshot_margin.gate_screenshot_margin(f.doc(), "figures/broken.png", notices)
            self.assertEqual([r.agent for r in reqs], ["unslopable:gate-screenshot-margin"])
            self.assertIn("No script could measure the edges", reqs[0].input)
            self.assertTrue(any("could not be measured" in n for n in notices))
        finally:
            f.close()


def hook_ctx_of(payload: dict) -> str:
    out = run_hook(payload)
    assert out is not None, "the hook said nothing"
    return out["hookSpecificOutput"]["additionalContext"]


FIG_TEXT = (FIXTURE / "TEXT.md").read_text().replace("(fig1.png)", "(figures/S1.e2.svg)")


class FiguresInText(unittest.TestCase):
    """Gates on a figure in the text: they run on TEXT.md."""

    def test_labels_not_in_the_text_before_go_to_a_judge(self):
        f = Folder(**{"TEXT.md": FIG_TEXT})
        try:
            (f.path / "figures").mkdir()
            (f.path / "figures" / "S1.e2.svg").write_text(svg("Taps", "Tank inlet", "1", "2"))
            reqs = figure_gates.text_requests(f.doc())
            labels = [r for r in reqs if r.gate == "figure-labels"]
            self.assertEqual(len(labels), 1)
            self.assertIn("«Tank inlet»", labels[0].input)
            self.assertNotIn("«Taps»", labels[0].input)  # «tap» is in the text before
            self.assertIn("A family opens a tap", labels[0].input)
            self.assertNotIn("check valve", labels[0].input.split("## The text before the figure")[1])
            (f.path / "figures" / "S1.e2.svg").write_text(svg("pressure switch"))
            self.assertEqual([r for r in figure_gates.text_requests(f.doc()) if r.gate == "figure-labels"], [])
            # leading blank lines: a label used only after the figure is still missing before it
            (f.path / "TEXT.md").write_text("\n\n\n" + FIG_TEXT)
            (f.path / "figures" / "S1.e2.svg").write_text(svg("check valve"))
            labels = [r for r in figure_gates.text_requests(f.doc()) if r.gate == "figure-labels"]
            self.assertEqual(len(labels), 1)
            self.assertIn("«check valve»", labels[0].input)
        finally:
            f.close()

    def test_numbered_marks_run_one_to_n_and_meet_a_judge_once_the_section_is_complete(self):
        f = Folder(**{"TEXT.md": FIG_TEXT})
        try:
            (f.path / "figures").mkdir()
            p = f.path / "figures" / "S1.e2.svg"
            p.write_text(svg("pressure switch", "1", "3"))
            fails = figure_steps.gate_figure_steps(f.doc())
            self.assertEqual([x.gate for x in fails], ["figure-steps"])
            self.assertIn("2 missing", fails[0].why)
            p.write_text(svg("port", "80", "pressure switch"))  # a port number is no step
            self.assertEqual(figure_steps.gate_figure_steps(f.doc()), [])
            p.write_text(svg("pressure switch", "1", "②"))  # a circled 2
            self.assertEqual(figure_steps.gate_figure_steps(f.doc()), [])
            steps = [r for r in figure_gates.text_requests(f.doc()) if r.gate == "figure-steps"]
            self.assertEqual(len(steps), 1)
            self.assertIn("1, 2", steps[0].input)
            self.assertIn("keeps it primed", steps[0].input)  # the whole section S1
            # a section not complete yet: no steps judge
            cut = FIG_TEXT.split("<!-- S1.e3 -->")[0]
            (f.path / "TEXT.md").write_text(cut)
            self.assertEqual([r for r in figure_gates.text_requests(f.doc()) if r.gate == "figure-steps"], [])
            # a figure with no numbers has no steps judge
            (f.path / "TEXT.md").write_text(FIG_TEXT)
            p.write_text(svg("pressure switch"))
            self.assertEqual([r for r in figure_gates.text_requests(f.doc()) if r.gate == "figure-steps"], [])
        finally:
            f.close()

    def test_a_raster_figure_goes_to_both_judges(self):
        f = Folder(**{"TEXT.md": FIG_TEXT.replace("figures/S1.e2.svg", "figures/shot.png")})
        try:
            (f.path / "figures").mkdir()
            (f.path / "figures" / "shot.png").write_bytes(png_bytes())
            gates = sorted(r.gate for r in figure_gates.text_requests(f.doc()))
            self.assertEqual(gates, ["figure-labels", "figure-steps"])
        finally:
            f.close()

    @unittest.skipIf(NO_SPACY, "the hook on TEXT.md runs the spaCy gates")
    def test_the_hook_on_text_runs_the_figure_gates(self):
        f = Folder(**{"TEXT.md": FIG_TEXT})
        try:
            (f.path / "figures").mkdir()
            (f.path / "figures" / "S1.e2.svg").write_text(svg("pressure switch", "1", "3"))
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertIn("[figure-steps]", ctx)
        finally:
            f.close()


# ---------------------------------------------------------------- final document: plan elements, leftovers, links

FULL_TEXT = (FIXTURE / "TEXT.md").read_text(encoding="utf-8")


def without_element(text: str, rid: str) -> str:
    """The fixture text with one element's marker and its block taken out."""
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == f"<!-- {rid} -->":
            skip = True
            continue
        if skip and (line.startswith("<!--") or line.startswith("#")):
            skip = False
        if not skip:
            out.append(line)
    return "".join(out)


def up_to(text: str, rid: str) -> str:
    """The fixture text as the writer has it once element `rid` is written (everything after it not yet)."""
    marker = f"<!-- {rid} -->"
    i = text.index(marker)
    nxt = text.find("<!--", i + len(marker))
    head = text if nxt < 0 else text[:nxt]
    return head.rstrip() + "\n"


class PlanElementsWritten(unittest.TestCase):
    def fails(self, body):
        f = Folder(**{"TEXT.md": body})
        try:
            notes = []
            return [x for x in plan_elements_written.gate_plan_elements_written(f.doc(), notes)], notes
        finally:
            f.close()

    def test_skipped_element_fails(self):
        fs, _ = self.fails(without_element(FULL_TEXT, "S1.e2"))
        self.assertEqual([(x.gate, x.where) for x in fs], [("plan-element-missing", "TEXT.md element S1.e2")])
        self.assertIn("S1.e3", fs[0].why)

    def test_mid_writing_is_not_a_failure(self):
        # the writer has written S1.e1..S1.e3 so far: S2.1.e1 and S2.2.e1 are not written yet, not missing
        fs, notes = self.fails(up_to(FULL_TEXT, "S1.e3"))
        self.assertEqual(fs, [])
        self.assertEqual(len(notes), 1)
        self.assertIn("2 elements of PLAN.md not written yet (next: S2.1.e1)", notes[0])

    def test_complete_text_has_no_note(self):
        fs, notes = self.fails(FULL_TEXT)
        self.assertEqual((fs, notes), ([], []))

    def test_runs_in_run_text(self):
        f = Folder(**{"TEXT.md": without_element(FULL_TEXT, "S1.e1"), "BRIEF.md": polish_brief()})
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertIn(("plan-element-missing", "TEXT.md element S1.e1"), {(x.gate, x.where) for x in fails})
        finally:
            f.close()


class LeftoverMarkers(unittest.TestCase):
    def fails(self, body, **more):
        f = Folder(**{"TEXT.md": body}, **more)
        try:
            return leftover_markers.gate_leftover_markers(f.doc())
        finally:
            f.close()

    def test_markers_fail_and_are_named(self):
        body = FULL_TEXT.replace("one sensor per tank.", "one sensor per tank TODO.").replace(
            "Guests change nothing.", "Guests change nothing [уточнить].")
        fs = self.fails(body)
        self.assertEqual(len(fs), 2, [x.line() for x in fs])
        self.assertEqual({x.gate for x in fs}, {"leftover-marker"})
        self.assertTrue(any("«TODO»" in x.why for x in fs))
        self.assertTrue(any("«[уточнить]»" in x.why for x in fs))
        self.assertTrue(all(x.where.startswith("TEXT.md line ") for x in fs))

    def test_element_markers_words_and_code_are_not_leftovers(self):
        body = FULL_TEXT.replace("Guests change nothing.", "Guests change nothing, todo or not, in `TODO.md`.")
        self.assertEqual([x.line() for x in self.fails(body)], [])  # every <!-- id --> line stays out too

    def test_document_extends_the_list(self):
        body = FULL_TEXT.replace("Guests change nothing.", "Guests change nothing [DRAFT].")
        self.assertEqual(self.fails(body), [])
        gates = (FIXTURE / "GATES.md").read_text() + "leftover_markers: [DRAFT]; @@\n"
        fs = self.fails(body, **{"GATES.md": gates})
        self.assertEqual(len(fs), 1)
        self.assertIn("«[DRAFT]»", fs[0].why)
        f = Folder(**{"GATES.md": gates})
        try:
            self.assertIn("TODO", leftover_markers.leftover_markers(f.doc()))  # the document's list extends the default one
        finally:
            f.close()


class Links(unittest.TestCase):
    """No network: `links.open_url` is replaced by a fake that records the URLs it was asked."""

    def setUp(self):
        self.asked = []
        self.answers = {}
        self._orig = links.open_url

        def fake(url, timeout=None):
            self.asked.append(url)
            return self.answers.get(url, ("ok", "HTTP 200"))
        links.open_url = fake

    def tearDown(self):
        links.open_url = self._orig

    def run_links(self, f):
        notes = []
        return links.gate_links(f.doc(), notes), notes

    def text_with(self, extra: str) -> str:
        return FULL_TEXT.replace("Four people decide who may change the limits.", extra)

    def test_internal_links_match_headings(self):
        f = Folder(**{"TEXT.md": self.text_with(
            "Four roles decide it, as [the data part](#when-the-pump-runs) and [this](#pressure-limits) say. "
            "A [wrong one](#no-such-part) does not resolve.")})
        try:
            fs, _ = self.run_links(f)
            self.assertEqual([(x.gate, x.quote) for x in fs], [("links", "#no-such-part")])
            self.assertIn("no heading", fs[0].why)
        finally:
            f.close()

    def test_file_links_and_images(self):
        f = Folder(**{"TEXT.md": self.text_with(
            "Four roles decide it, see [the notes](sources/notes.md) and [gone](sources/gone.md). "
            "Mail [us](mailto:a@example.com).")})
        try:
            fs, _ = self.run_links(f)
            self.assertEqual([x.quote for x in fs], ["sources/gone.md"])  # the fixture's fig1.png image is not checked
            self.assertEqual(self.asked, [])
        finally:
            f.close()

    def test_external_links_opened_named_and_cached(self):
        good, bad, shy = "https://good.example/a", "https://bad.example/b", "https://shy.example/c"
        self.answers = {bad: ("fail", "HTTP 404: the page is not there"),
                        shy: ("unknown", "HTTP 403: the site refuses scripted requests")}
        f = Folder(**{"TEXT.md": self.text_with(
            f"Four roles decide it, see [good]({good}), <{bad}> and {shy}.\n\n[ref]: {good}")})
        try:
            fs, notes = self.run_links(f)
            self.assertEqual([(x.quote, x.gate) for x in fs], [(bad, "links")])
            self.assertIn("does not open (HTTP 404", fs[0].why)
            self.assertEqual(len(notes), 1)
            self.assertIn(shy, notes[0])
            self.assertEqual(sorted(self.asked), sorted([good, bad, shy]))  # each URL opened once
            # the next write uses the cache: nothing is opened again
            self.asked.clear()
            fs2, _ = self.run_links(f)
            self.assertEqual([x.quote for x in fs2], [bad])
            self.assertEqual(self.asked, [])
            # an expired entry is opened again
            cache = json.loads((f.path / ".gates" / "links.json").read_text())
            cache[good]["time"] -= links.LINK_TTL_OK + 1
            (f.path / ".gates" / "links.json").write_text(json.dumps(cache))
            self.run_links(f)
            self.assertEqual(self.asked, [good])
        finally:
            f.close()

    def test_runs_in_run_text(self):
        f = Folder(**{"TEXT.md": self.text_with("Four roles decide it, as [this](#nowhere) says."),
                      "BRIEF.md": polish_brief()})
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertIn(("links", "#nowhere"), {(x.gate, x.quote) for x in fails})
        finally:
            f.close()

    def test_hook_reports_a_leftover_marker(self):
        # the hook runs in a subprocess, where the fake open_url does not apply: this text must hold no external link
        f = Folder(**{"TEXT.md": FULL_TEXT.replace("Guests change nothing.", "Guests change nothing TBD."),
                      "BRIEF.md": polish_brief()})
        try:
            ctx = hook_ctx(f.path / "TEXT.md")
            self.assertIn("SCRIPT GATES — NOT PASSED", ctx)
            self.assertIn("[leftover-marker]", ctx)
        finally:
            f.close()


class LinksMore(Links):
    """Cases the first review found: brackets in URLs, footnotes, code in headings, folders, cache refresh."""

    def test_url_with_brackets_is_kept_whole(self):
        u = "https://wiki.example/Mercury_(planet)"
        f = Folder(**{"TEXT.md": self.text_with(f"Four roles decide it, see [x]({u}) and {u}.")})
        try:
            self.run_links(f)
            self.assertEqual(self.asked, [u])
        finally:
            f.close()

    def test_footnote_is_no_link_and_ref_anchor_resolves(self):
        f = Folder(**{"TEXT.md": self.text_with("Four roles decide it.[^1]\n\n[^1]: Smith, 2020, page 4.\n\n"
                                                "[edits]: #pressure-limits")})
        try:
            self.assertEqual(self.run_links(f)[0], [])
        finally:
            f.close()

    def test_heading_with_code_and_file_outside_folder(self):
        body = self.text_with("Four roles decide it, see [opt](#the-foo-option), [out](../outside.md) and "
                              "[abs](/etc/hosts).") + "\n## The `foo` option\n"
        f = Folder(**{"TEXT.md": body})
        try:
            (f.path.parent / "outside.md").write_text("x")
            self.assertEqual(sorted(x.quote for x in self.run_links(f)[0]), ["../outside.md", "/etc/hosts"])
        finally:
            f.close()

    def test_failed_link_is_opened_again_after_its_ttl(self):
        bad = "https://bad.example/b"
        self.answers = {bad: ("fail", "HTTP 404: the page is not there")}
        f = Folder(**{"TEXT.md": self.text_with(f"Four roles decide it, see {bad}.")})
        try:
            self.run_links(f)
            self.run_links(f)
            self.assertEqual(self.asked, [bad])  # cached within its TTL
            cache = json.loads((f.path / ".gates" / "links.json").read_text())
            cache[bad]["time"] -= links.LINK_TTL_BAD + 1
            cache["https://gone.example/"] = {"status": "ok", "time": cache[bad]["time"]}  # no longer in the text
            (f.path / ".gates" / "links.json").write_text(json.dumps(cache))
            self.run_links(f)
            self.assertEqual(self.asked, [bad, bad])
            self.assertEqual(list(json.loads((f.path / ".gates" / "links.json").read_text())), [bad])
        finally:
            f.close()


class OpenUrl(unittest.TestCase):
    """`open_url` against servers on 127.0.0.1 (no network): every answer maps to ok / fail / unknown, never raises."""

    @classmethod
    def setUpClass(cls):
        import http.server
        import socket
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                code = int(self.path.strip("/") or 200)
                self.send_response(code)
                self.end_headers()

            def log_message(self, *a):
                pass
        cls.http = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()

        def raw(reply):
            srv = socket.socket()
            srv.bind(("127.0.0.1", 0))
            srv.listen(5)

            def loop():
                while True:
                    try:
                        c, _ = srv.accept()
                        c.recv(4096)
                    except OSError:
                        return  # the server was closed
                    cls.conns.append(c)
                    if reply is not None:
                        c.sendall(reply)
                        c.close()
            threading.Thread(target=loop, daemon=True).start()
            return srv
        cls.conns = []
        cls.garbage = raw(b"SSH-2.0-OpenSSH_9.0\r\n")
        cls.silent = raw(None)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        for c in cls.conns + [cls.garbage, cls.silent]:
            c.close()

    def at(self, path):
        return f"http://127.0.0.1:{self.http.server_address[1]}/{path}"

    def test_status_codes(self):
        self.assertEqual(links.open_url(self.at("200"))[0], "ok")
        self.assertEqual(links.open_url(self.at("404"))[0], "fail")
        self.assertEqual(links.open_url(self.at("403"))[0], "unknown")
        self.assertEqual(links.open_url(self.at("503"))[0], "unknown")

    def test_silent_and_garbled_servers(self):
        self.assertEqual(links.open_url(f"http://127.0.0.1:{self.silent.getsockname()[1]}/", timeout=0.5)[0], "unknown")
        status, detail = links.open_url(f"http://127.0.0.1:{self.garbage.getsockname()[1]}/", timeout=2)
        self.assertIn(status, ("fail", "unknown"), detail)


class FinalGatesMore(unittest.TestCase):
    def test_marker_in_fenced_code_and_roman_numerals(self):
        body = FULL_TEXT.replace("Guests change nothing.", "Guests change nothing since the XXX Olympiad.") + \
            "\n```\nTODO in code\n```\n"
        f = Folder(**{"TEXT.md": body})
        try:
            self.assertEqual([x.line() for x in leftover_markers.gate_leftover_markers(f.doc())], [])
        finally:
            f.close()
        f = Folder(**{"TEXT.md": FULL_TEXT.replace("Guests change nothing.", "Guests change nothing XXX.")})
        try:
            self.assertEqual(len(leftover_markers.gate_leftover_markers(f.doc())), 1)
        finally:
            f.close()

    def test_hook_does_not_call_an_unfinished_text_done(self):
        f = Folder(**{"TEXT.md": up_to(FULL_TEXT, "S1.e3"), "BRIEF.md": polish_brief()})
        try:
            ids = [r.id for r in jg.text_requests(f.doc(), [])]
            (f.path / ".gates").mkdir()
            (f.path / ".gates" / "verdicts.json").write_text(json.dumps({i: {"verdict": "PASSED"} for i in ids}))
            ctx = hook_ctx(f.path / "TEXT.md")  # the fixture has no external link: the subprocess opens nothing
            self.assertIn("The text is NOT done: 2 elements of PLAN.md not written yet (next: S2.1.e1)", ctx)
            last = json.loads((f.path / ".gates" / "last_run.json").read_text())
            self.assertIn("text not complete", last["status"])
        finally:
            f.close()


class JudgeLimit(unittest.TestCase):
    """More judges due than one round of the runner: the ones over the round are still due, never passed."""

    def test_over_limit_judges_are_due_not_passed(self):
        import re
        f = Folder(**{"BRIEF.md": polish_brief()})
        try:
            ctx = hook_ctx(f.path / "TEXT.md")
            m = re.search(r"Judge gates: (\d+) in all, (\d+) passed earlier", ctx)
            self.assertIsNotNone(m, ctx[:400])
            total, passed = int(m.group(1)), int(m.group(2))
            self.assertGreater(total, 20)          # the case: more due than one round asks for
            self.assertEqual(passed, 0)            # nothing has a verdict yet
            self.assertIn(f"Judges due now: {total}.", ctx)
            out = runner("next", f.path, "TEXT.md")
            self.assertIn(f"ROUND: 20 judges ({total - 20} more after these)", out)
            # after the first round passes, the count of passed is exactly that round, the rest still due
            ids = re.findall(r"judge_id: (\S+)", out)
            self.assertEqual(len(ids), 20)
            v = f.path / ".gates" / "verdicts.json"
            v.write_text(json.dumps({j: {"verdict": "PASSED", "text": "PASSED"} for j in ids}))
            ctx = hook_ctx(f.path / "TEXT.md")
            m = re.search(r"Judge gates: (\d+) in all, (\d+) passed earlier", ctx)
            self.assertEqual(int(m.group(2)), 20)
            self.assertNotIn("Every gate passed", ctx)
        finally:
            f.close()


if __name__ == "__main__":
    unittest.main()
