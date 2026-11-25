"""Tests of the element library: the list and its schematics, and the gates that read element kinds.

  python3 -m unittest tests.test_elements -v
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import os
import re
import sys
import unittest
import xml.dom.minidom
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_gates import ROOT, Folder, docs, due_agents, hook_ctx, jg, polish_brief  # noqa: E402
import formats  # noqa: E402
import list_lead_in  # noqa: E402
import no_compound  # noqa: E402
import run_scripts  # noqa: E402
import slop_words  # noqa: E402
import term_first_use  # noqa: E402
from test_wall_and_blocks import plan_of, wall  # noqa: E402

ELEMENTS = ROOT / "elements"
KINDS = ["paragraph", "bulleted_list", "numbered_list", "table", "tiles", "diagram", "screenshot", "summary",
         "callout", "yes_no", "pull_quote", "steps", "stat", "faq", "definition", "chart", "generated_image"]


def library_kinds() -> list[str]:
    return re.findall(r"^- `([a-z_]+)` — ", (ELEMENTS / "library.md").read_text(encoding="utf-8"), re.M)


class Library(unittest.TestCase):
    def test_the_list_holds_the_picked_elements(self):
        self.assertEqual(library_kinds(), KINDS)

    def test_every_element_has_a_black_white_and_grey_schematic(self):
        files = {k: [f"{k}.svg"] for k in KINDS}
        files["steps"] = ["steps-horizontal.svg", "steps-vertical.svg"]
        lib = (ELEMENTS / "library.md").read_text(encoding="utf-8")
        for kind, names in files.items():
            for name in names:
                with self.subTest(name):
                    self.assertIn(f"`{name}`", lib)
                    svg = (ELEMENTS / name).read_text(encoding="utf-8")
                    dom = xml.dom.minidom.parseString(svg)
                    self.assertTrue(dom.getElementsByTagName("title"))
                    self.assertTrue(dom.getElementsByTagName("desc")[0].firstChild.data.strip())
                    for c in re.findall(r'(?:fill|stroke)="#([0-9a-fA-F]{6})"', svg):
                        r, g, b = c[0:2], c[2:4], c[4:6]
                        self.assertTrue(r == g == b, f"{name}: colour #{c} is not grey")
        self.assertEqual(sorted(p.name for p in ELEMENTS.glob("*.svg")), sorted(n for v in files.values() for n in v))


class Wall(unittest.TestCase):
    def ids(self, fs):
        return [f.where.split()[-1] for f in fs]

    def test_every_visual_element_of_the_library_resets_the_count(self):
        for kind in ("bulleted_list", "numbered_list", "table", "tiles", "diagram", "screenshot", "callout", "yes_no",
                     "pull_quote", "steps vertical", "steps horizontal", "stat", "definition", "chart"):
            with self.subTest(kind=kind):
                self.assertEqual(wall(plan_of("paragraph:12", f"{kind}:3", "paragraph:6")), [])

    def test_summary_and_faq_stay_neutral(self):
        for kind in ("summary", "faq"):
            with self.subTest(kind=kind):
                self.assertEqual(self.ids(wall(plan_of("paragraph:12", f"{kind}:2", "paragraph:2"))), ["S1.e3"])

    def test_library_names_are_the_known_kinds(self):
        self.assertEqual(docs.canon_kind("yes_no"), "yes-no")
        self.assertEqual(docs.canon_kind("Pull_Quote"), "pull-quote")
        self.assertEqual(docs.canon_kind("pull quote"), "pull-quote")
        self.assertEqual(docs.canon_kind("steps  Vertical"), "steps vertical")


# A pump document that uses every new fenced element once.
PLAN = """Approved sections by plan-approver for Test Author, 2026-11-19

Approved subsections by plan-approver for Test Author, 2026-11-19

Approved elements by plan-approver for Test Author, 2026-11-19

# Plan

- S1 · **The pump** · what the pump does · 11 lines
  - S1.e1 · paragraph · the pump lifts water from the well · facts: F1 · 2 lines
  - S1.e2 · definition · the check valve; explains: check valve · facts: F2 · 2 lines
  - S1.e3 · stat · the water the pump moves in an hour · facts: F3 · 1 lines
  - S1.e4 · pull_quote · a full tank in May · 1 lines
  - S1.e5 · paragraph · the tank keeps water for the garden · facts: F6 · 5 lines
- S2 · **The first start** · what the owner does before the first run · 16 lines
  - S2.e1 · steps vertical · open the cap; fill the body; close the cap; switch on · facts: F4 · 10 lines
  - S2.e2 · faq · can the pump run dry; can it lift pond water · facts: F5 · 6 lines
"""

TERMS = """# Terms

## Known

- pump — the machine that moves water from the well to the tank

## Explain

- check valve — a valve that lets water flow one way only
"""

TEXT = """# The garden pump

## The pump

<!-- S1.e1 -->
The pump lifts water from the well to the tank. It runs only while the well holds enough water.

<!-- S1.e2 -->
::: definition
**Check valve** — a valve that lets water flow one way only. It keeps the pipe full when the pump stops.
:::

<!-- S1.e3 -->
::: stat
**900 litres** of water reach the tank in one hour.
:::

<!-- S1.e4 -->
::: pull-quote
A full tank in May means a quiet summer.
— Anna Berg, who keeps the orchard
:::

<!-- S1.e5 -->
The tank keeps the water for the garden. A full tank waters the beds for three dry days. The pump fills it again at night, when the well is full. The owner sets the hour on a timer next to the tank.

## The first start

<!-- S2.e1 -->
The pump body has to be full of water before the first run.

::: steps vertical
1. **Open the cap:** turn the brass cap on top of the pump to the left.
2. **Fill the body:** pour water in until it reaches the rim.
3. **Close the cap:** turn the cap to the right until it stops.
4. **Switch on:** the pump draws water from the well within a minute.
:::

<!-- S2.e2 -->
::: faq
**Can the pump run dry?**
No. A float switch stops it when the well runs low.

**Can it lift water from a pond?**
Only clean water. Sand wears the seal in a few weeks.
:::
"""


GATES = """# Gates
sentence_max_words: 20
heading_max_words: 6
terms_before_first_figure: 2
new_terms_per_unit: 1
total_lines: 27
words_per_line: 10
length_tolerance_pct: 20
out_of_scope_terms: Bluebird
"""


def pump(text: str = TEXT, plan: str = PLAN) -> Folder:
    return Folder(PLAN=plan, **{"TEXT.md": text, "TERMS.md": TERMS, "BRIEF.md": polish_brief(), "GATES.md": GATES})


class Blocks(unittest.TestCase):
    def test_parsing(self):
        f = pump()
        try:
            t = f.doc().text
            self.assertEqual(t.problems, [])
            kinds = [(b.kind, b.element) for b in t.blocks]
            self.assertEqual(kinds, [("paragraph", "S1.e1"), ("definition", "S1.e2"), ("stat", "S1.e3"),
                                     ("pull-quote", "S1.e4"), ("paragraph", "S1.e5"), ("paragraph", "S2.e1"),
                                     ("steps", "S2.e1"), ("faq", "S2.e2")])
            steps = t.blocks[6]
            self.assertEqual(steps.form, "vertical")
            self.assertEqual(steps.titles, ["Open the cap", "Fill the body", "Close the cap", "Switch on"])
            self.assertEqual(len(steps.items), 4)
            faq = t.blocks[7]
            self.assertEqual(faq.titles, ["Can the pump run dry?", "Can it lift water from a pond?"])
            quote = t.blocks[3]
            self.assertNotIn("Anna", " ".join(quote.sentences))
        finally:
            f.close()

    def test_the_whole_text_passes_its_script_gates(self):
        f = pump()
        try:
            fs = run_scripts.run_text(f.doc(), [])[0]
            self.assertEqual([x.line() for x in fs], [])
        finally:
            f.close()

    def test_plan_gates_take_the_new_kinds(self):
        f = pump()
        try:
            self.assertEqual([x.line() for x in run_scripts.run_plan(f.doc(), 3)], [])
        finally:
            f.close()

    def test_format_of_the_new_blocks(self):
        cases = {
            "steps with no form": ("::: steps vertical", "::: steps"),
            "steps in the other form than the plan's": ("::: steps vertical", "::: steps horizontal"),
            "a step with no bold title": ("1. **Open the cap:** turn", "1. Turn"),
            "steps that are not a numbered list": ("1. **Open the cap:**", "- **Open the cap:**"),
            "a stat with no bold number first": ("**900 litres** of water", "Of water, **900 litres**"),
            "a definition with no bold term first": ("**Check valve** — a valve", "A check valve is a valve"),
            "a faq question that is not bold": ("**Can the pump run dry?**", "Can the pump run dry?"),
            "a stat written as a paragraph": ("::: stat\n**900 litres** of water reach the tank in one hour.\n:::",
                                              "**900 litres** of water reach the tank in one hour."),
            "a pull quote under a paragraph element": ("::: definition", "::: pull-quote"),
        }
        for name, (old, new) in cases.items():
            with self.subTest(name):
                self.assertIn(old, TEXT)
                f = pump(TEXT.replace(old, new, 1))
                try:
                    doc = f.doc()
                    fs = [x for x in run_scripts.run_text(doc, [])[0] if x.gate == "format"]
                    self.assertTrue(fs, name)
                finally:
                    f.close()

    def test_steps_are_led_in(self):
        f = pump(TEXT.replace("The pump body has to be full of water before the first run.\n\n", ""))
        try:
            fs = list_lead_in.gate_list_lead_in(f.doc())
            self.assertEqual([x.where for x in fs], [fs[0].where])
            self.assertIn("S2.e1, steps", fs[0].where)
        finally:
            f.close()

    def test_steps_with_no_form_fail_on_the_plan(self):
        f = pump(plan=PLAN.replace("· steps vertical ·", "· steps ·"))
        try:
            fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "format"]
            self.assertEqual([x.where for x in fs], ["PLAN.md S2.e1"])
        finally:
            f.close()

    def test_a_definition_may_open_with_its_term_and_still_goes_to_the_judge(self):
        f = pump()
        try:
            doc = f.doc()
            self.assertEqual(term_first_use.gate_term_first_sentence(doc), [])
            self.assertIn("term «check valve»", [r.unit for r in jg.text_requests(doc, []) if r.gate == "term-explained"])
        finally:
            f.close()

    def test_plan_lists_split_by_semicolons_are_parsed_part_by_part(self):
        # a FAQ's questions, steps and a diagram's links are one field separated by semicolons (the plan skill)
        if os.environ.get("SKIP_SPACY") == "1":
            self.skipTest("spaCy")
        plan = PLAN.replace("can the pump run dry; can it lift pond water",
                            "can the pump run dry; can it lift water from a pond")
        f = pump(plan=plan)
        try:
            (f.path / "BRIEF.md").write_text(polish_brief().replace("Polish.", "English."), encoding="utf-8")
            errors, _ = no_compound.gate_plan_compound(f.doc(), [3], [])
            self.assertEqual([e.where for e in errors], [])
            bad = plan.replace("the tank keeps water for the garden", "the tank keeps water; the owner waters the beds")
            (f.path / "PLAN.md").write_text(bad, encoding="utf-8")
            errors, _ = no_compound.gate_plan_compound(f.doc(), [3], [])
            self.assertEqual([e.where for e in errors], ["PLAN.md S1.e5"])
        finally:
            f.close()

    def test_lengths_of_the_blocks(self):
        t = docs.read_text("<!-- a -->\n::: steps horizontal\n1. **One:** " + " ".join(["w"] * 12)
                           + "\n2. **Two:** w\n:::\n\n<!-- b -->\n::: faq\n**Why?**\n" + " ".join(["w"] * 15)
                           + "\n:::\n\n<!-- c -->\n::: stat\n**4** w w w\n:::\n")
        self.assertEqual([docs.block_lines(b, 10) for b in t.blocks], [3, 3, 1])

    def test_element_judges_and_slop_read_the_new_blocks(self):
        f = pump(TEXT.replace("reach the tank in one hour.", "reach the tank in one hour, a testament to its power.")
                 .replace("pour water in until", "pour water in, a testament to care, until"))
        try:
            doc = f.doc()
            hit = {doc.text.blocks[i].kind for i, _ in slop_words.slop_hits(doc)}
            self.assertLessEqual({"stat", "steps"}, hit)
            inputs = " ".join(r.input for r in jg.text_requests(doc, []) if r.gate == "cliche")
            for words in ("Check valve", "900 litres", "quiet summer", "Open the cap", "run dry"):
                self.assertIn(words, inputs)
        finally:
            f.close()



class GatesOff(unittest.TestCase):
    """GATES.md `gates_off`: the gates stage switches off a gate that argues with the brief, with the reason; the hook
    and the runner do not run it, every other gate runs."""

    def folder(self, off: str = "", text: str = TEXT, plan: str = PLAN) -> Folder:
        f = pump(text, plan)
        (f.path / "GATES.md").write_text(GATES + (f"gates_off: {off}\n" if off else ""), encoding="utf-8")
        return f

    def gates(self, fs):
        return sorted({x.gate for x in fs})

    def test_a_script_gate_switched_off_reports_nothing_and_the_others_still_run(self):
        long = TEXT.replace("It runs only while the well holds enough water.",
                            "It runs only while the well holds enough water for the pump to lift it up the long pipe "
                            "to the tank on the hill behind the house.")
        f = self.folder(text=long)
        try:
            self.assertIn("sentence-max-words", self.gates(run_scripts.run_text(f.doc(), [])[0]))
        finally:
            f.close()
        f = self.folder("sentence-max-words (the brief wants long sentences)", text=long)
        try:
            fs = run_scripts.run_text(f.doc(), [])[0]
            self.assertNotIn("sentence-max-words", self.gates(fs))
            self.assertIn("length", self.gates(fs))   # the longer sentence still misses the element's size
        finally:
            f.close()

    def test_plan_gates_by_their_library_names(self):
        wall_plan = PLAN.replace("  - S1.e2 · definition ·", "  - S1.e2 · paragraph ·") \
            .replace("  - S1.e3 · stat ·", "  - S1.e3 · paragraph ·").replace("  - S1.e4 · pull_quote ·", "  - S1.e4 · paragraph ·") \
            .replace("from the well · facts: F1 · 2 lines", "from the well · facts: F1 · 8 lines")
        f = self.folder(plan=wall_plan)
        try:
            self.assertEqual(self.gates(run_scripts.run_plan(f.doc(), 3)), ["length", "plain-text-wall"])
        finally:
            f.close()
        f = self.folder("plan-wall (the brief rules out lists, tables and pictures)", plan=wall_plan)
        try:
            self.assertEqual(self.gates(run_scripts.run_plan(f.doc(), 3)), ["length"])
        finally:
            f.close()
        f = self.folder("plan-length (the author sizes by hand)", plan=wall_plan)
        try:
            self.assertEqual(self.gates(run_scripts.run_plan(f.doc(), 3)), ["plain-text-wall"])
        finally:
            f.close()

    def test_a_judge_switched_off_is_not_due_and_the_others_are(self):
        f = self.folder()
        try:
            hook_ctx(f.path / "TEXT.md")
            on = due_agents(f.path, "TEXT.md")
            self.assertIn("unslopable:gate-cliche", on)
        finally:
            f.close()
        f = self.folder("cliche (the brief asks for set phrases of the trade)")
        try:
            hook_ctx(f.path / "TEXT.md")
            off = due_agents(f.path, "TEXT.md")
            self.assertNotIn("unslopable:gate-cliche", off)
            self.assertEqual(sorted(set(on) - set(off)), ["unslopable:gate-cliche"])
        finally:
            f.close()

    def test_a_name_not_in_the_library_or_without_a_reason_is_a_config_failure(self):
        for off, word in (("plan-walls (a typo)", "not a gate"), ("plan-wall", "no reason")):
            with self.subTest(off):
                f = self.folder(off)
                try:
                    fs = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "config"]
                    self.assertTrue(fs and word in fs[0].why, fs)
                finally:
                    f.close()

    def test_a_semicolon_inside_the_reason_stays_in_the_reason(self):
        f = self.folder("plan-wall (no lists; no tables); cliche (set phrases)")
        try:
            from common import gates_off
            self.assertEqual(gates_off(f.doc()), {"plan-wall": "no lists; no tables", "cliche": "set phrases"})
            self.assertEqual([x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "config"], [])
        finally:
            f.close()

    def test_no_compound_switched_off_runs_no_parse(self):
        f = self.folder("no-compound (the brief allows joined clauses)")
        try:
            (f.path / "BRIEF.md").write_text(polish_brief().replace("Polish.", "English."), encoding="utf-8")
            notices: list = []
            fs, cands = run_scripts.run_text(f.doc(), notices)
            self.assertEqual((cands, [n for n in notices if "no-compound" in n]), ([], []))
        finally:
            f.close()

    def test_a_plan_judge_switched_off_is_not_due(self):
        plan = PLAN.replace("Approved elements by plan-approver for Test Author, 2026-11-19\n\n", "")
        f = self.folder(plan=plan)
        try:
            hook_ctx(f.path / "PLAN.md")
            on = due_agents(f.path, "PLAN.md")
        finally:
            f.close()
        f = self.folder("goals-covered (the brief has one goal only)", plan=plan)
        try:
            hook_ctx(f.path / "PLAN.md")
            off = due_agents(f.path, "PLAN.md")
            self.assertIn("unslopable:gate-goals-covered", on)
            self.assertEqual(sorted(set(on) - set(off)), ["unslopable:gate-goals-covered"])
        finally:
            f.close()

    def test_format_failures_stay_whatever_is_off(self):
        f = self.folder("list-lead-in (no lead-ins in this document)", text=TEXT.replace("::: stat\n", ""))
        try:
            self.assertIn("format", self.gates(run_scripts.run_text(f.doc(), [])[0]))
        finally:
            f.close()


if __name__ == "__main__":
    unittest.main()
