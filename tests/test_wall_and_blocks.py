"""Tests of the plan gate «no wall of plain text» and of the callout and yes/no blocks.

  python3 -m unittest tests.test_wall_and_blocks -v
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_gates import FIXTURE, Folder, docs, jg, polish_brief  # noqa: E402
import common  # noqa: E402
import formats  # noqa: E402
import list_lead_in  # noqa: E402
import no_truncated  # noqa: E402
import plan_wall  # noqa: E402
import run_scripts  # noqa: E402
import slop_words  # noqa: E402
import term_marked  # noqa: E402


def wall(plan: str, gates: str | None = None) -> list:
    files = {"PLAN": plan}
    if gates is not None:
        files["GATES.md"] = (FIXTURE / "GATES.md").read_text(encoding="utf-8") + gates
    f = Folder(**files)
    try:
        return plan_wall.gate_plan_wall(f.doc())
    finally:
        f.close()


def plan_of(*elements: str, sub: bool = False) -> str:
    """One section with the given elements, `kind:lines` each (`|` starts a new subsection when sub)."""
    out = ["- S1 · **Pumps** · what a pump does · 40 lines"]
    n, s = 0, 0
    if sub:
        s = 1
        out.append(f"  - S1.{s} · **Part {s}** · a part · 20 lines")
    for e in elements:
        if e == "|":
            s += 1
            out.append(f"  - S1.{s} · **Part {s}** · a part · 20 lines")
            continue
        kind, lines = e.split(":")
        n += 1
        pid = f"S1.{s}" if sub else "S1"
        ind = "    " if sub else "  "
        out.append(f"{ind}- {pid}.e{n} · {kind} · what it says · {lines} lines")
    return "\n".join(out) + "\n"


class PlainTextWall(unittest.TestCase):
    def ids(self, fs):
        return [f.where.split()[-1] for f in fs]

    def test_the_paragraph_that_goes_over_is_allowed_and_the_next_one_fails(self):
        self.assertEqual(wall(plan_of("paragraph:6", "paragraph:6")), [])
        self.assertEqual(wall(plan_of("paragraph:6", "paragraph:6", "list:3")), [])
        fs = wall(plan_of("paragraph:6", "paragraph:6", "paragraph:2"))
        self.assertEqual(self.ids(fs), ["S1.e3"])
        self.assertEqual(fs[0].gate, "plain-text-wall")
        self.assertIn("12 lines", fs[0].quote)
        self.assertIn("S1.e1 to S1.e2", fs[0].why)
        self.assertIn("right after S1.e2", fs[0].why)

    def test_exactly_the_limit_is_not_over_it(self):
        self.assertEqual(wall(plan_of("paragraph:5", "paragraph:5", "paragraph:3")), [])
        self.assertEqual(self.ids(wall(plan_of("paragraph:5", "paragraph:5", "paragraph:3", "paragraph:1"))),
                         ["S1.e4"])

    def test_one_failure_per_place_to_break(self):
        fs = wall(plan_of("paragraph:6", "paragraph:6", "paragraph:6", "paragraph:6", "paragraph:2"))
        self.assertEqual(self.ids(fs), ["S1.e3", "S1.e5"])

    def test_a_single_long_paragraph_is_allowed_but_must_be_followed_by_a_break(self):
        self.assertEqual(wall(plan_of("paragraph:12")), [])
        self.assertEqual(wall(plan_of("paragraph:12", "list:3", "paragraph:4")), [])
        self.assertEqual(self.ids(wall(plan_of("paragraph:12", "paragraph:2"))), ["S1.e2"])
        self.assertEqual(wall(plan_of("paragraph:3", "paragraph:12")), [])

    def test_every_break_kind_resets_the_count(self):
        for kind in ("list", "tiles", "table", "figure", "callout", "yes-no"):
            with self.subTest(kind=kind):
                self.assertEqual(wall(plan_of("paragraph:12", f"{kind}:3", "paragraph:6")), [])

    def test_other_kinds_neither_add_nor_reset(self):
        # A summary, a FAQ and the like are neutral
        self.assertEqual(wall(plan_of("paragraph:6", "summary:8", "paragraph:4")), [])
        self.assertEqual(self.ids(wall(plan_of("paragraph:12", "summary:2", "paragraph:2"))), ["S1.e3"])
        self.assertEqual(self.ids(wall(plan_of("paragraph:6", "faq:3", "paragraph:6", "paragraph:1"))), ["S1.e4"])

    def test_a_heading_resets_the_count(self):
        self.assertEqual(wall(plan_of("paragraph:12", "|", "paragraph:6", sub=True)), [])
        self.assertEqual(self.ids(wall(plan_of("paragraph:12", "paragraph:6", sub=True))), ["S1.1.e2"])
        two_sections = ("- S1 · **Pumps** · a · 12 lines\n  - S1.e1 · paragraph · a · 12 lines\n"
                        "- S2 · **Wells** · b · 6 lines\n  - S2.e2 · paragraph · b · 6 lines\n")
        self.assertEqual(wall(two_sections), [])

    def test_kinds_are_read_by_their_words(self):
        for kind in ("numbered list", "comparison table", "screenshot", "diagram", "yes/no", "generated image"):
            with self.subTest(kind=kind):
                # a generated image names its style (`style: …`), or the plan does not read it
                plan = plan_of("paragraph:12", f"{kind}:3", "paragraph:2").replace(
                    "generated image · what it says", "generated image · what it says · style: flat")
                self.assertEqual(wall(plan), [])
        self.assertEqual(self.ids(wall(plan_of("paragraph:12", "checklist:3", "paragraph:2"))), ["S1.e3"])

    def test_a_limit_with_no_number_is_a_config_failure(self):
        fs = wall(plan_of("paragraph:6"), "plain_text_max_lines: ten\n")
        self.assertEqual([f.gate for f in fs], ["config"])

    def test_the_limit_comes_from_gates_md(self):
        self.assertEqual(wall(plan_of("paragraph:6", "paragraph:6", "paragraph:2"), "plain_text_max_lines: 15\n"),
                         [])
        self.assertEqual(self.ids(wall(plan_of("paragraph:3", "paragraph:3", "paragraph:1"),
                                       "plain_text_max_lines: 5\n")), ["S1.e3"])

    def test_it_runs_with_plan_level_3_only(self):
        f = Folder(PLAN=plan_of("paragraph:6", "paragraph:6", "paragraph:6"))
        try:
            self.assertIn("plain-text-wall", [x.gate for x in run_scripts.run_plan(f.doc(), 3)])
            self.assertNotIn("plain-text-wall", [x.gate for x in run_scripts.run_plan(f.doc(), 2)])
        finally:
            f.close()

    def test_the_fixture_plan_passes(self):
        f = Folder()
        try:
            self.assertEqual(plan_wall.gate_plan_wall(f.doc()), [])
        finally:
            f.close()


# The fixture with S1.e3 a callout and S2.2.e1 a yes/no block.
BLOCKS_PLAN = ((FIXTURE / "PLAN.md").read_text(encoding="utf-8")
               .replace("S1.e3 · paragraph · the valve keeps", "S1.e3 · callout · the valve keeps")
               .replace("S2.2.e1 · list · who can change them", "S2.2.e1 · yes-no · what a guest can do"))
CALLOUT = """::: callout
The pump must not lose its water when it stops. The *check valve*, a part that holds the water, keeps it primed.
:::"""
YES_NO = """A guest can read the gauge and cannot change it.

::: yes-no
- ✓ Reads the pressure gauge.
- ✓ Asks the owner a question.
- ✗ Changes the pump's settings.
- ✗ Fits a part.
:::"""


def blocks_text() -> str:
    t = (FIXTURE / "TEXT.md").read_text(encoding="utf-8")
    old_callout = ("The pump must not lose its water when it stops. The *check valve*, a part that holds "
                   "the water, keeps it primed.")
    head, rest = t.split("<!-- S2.2.e1 -->")
    return head.replace(old_callout, CALLOUT) + "<!-- S2.2.e1 -->\n" + YES_NO + "\n"


class Blocks(unittest.TestCase):
    def folder(self, text: str | None = None, plan: str = BLOCKS_PLAN) -> Folder:
        return Folder(PLAN=plan, **{"TEXT.md": text if text is not None else blocks_text(),
                                    "BRIEF.md": polish_brief()})

    def test_parsing(self):
        f = self.folder()
        try:
            bs = f.doc().text.blocks
            (c,) = [b for b in bs if b.kind == "callout"]
            self.assertEqual(c.element, "S1.e3")
            self.assertNotIn(":::", c.text)
            self.assertEqual(len(c.sentences), 2)
            (y,) = [b for b in bs if b.kind == "yes-no"]
            self.assertEqual(y.element, "S2.2.e1")
            self.assertEqual(y.sides, ["yes", "yes", "no", "no"])
            self.assertEqual(y.items[0], "Reads the pressure gauge.")
            self.assertEqual(f.doc().text.problems, [])
        finally:
            f.close()

    def test_the_whole_text_passes_its_script_gates(self):
        f = self.folder()
        try:
            fs = run_scripts.run_text(f.doc(), [])[0]
            self.assertEqual([x.line() for x in fs], [])
        finally:
            f.close()

    def test_format_of_the_fenced_blocks(self):
        cases = {
            "a callout element written as a paragraph": (CALLOUT, CALLOUT.replace("::: callout\n", "").replace("\n:::", "")),
            "a fenced block of another kind": (CALLOUT, CALLOUT.replace("::: callout", "::: yes-no")),
            "an unknown fenced block": (CALLOUT, CALLOUT.replace("::: callout", "::: warning")),
            "an unclosed block": (YES_NO, YES_NO.replace("\n:::", "")),
            "an item with no icon": (YES_NO, YES_NO.replace("- ✗ Fits a part.", "- Fits a part.")),
            "no item with ✗": (YES_NO, YES_NO.replace("- ✗", "- ✓")),
            "a stray closing line": (YES_NO, YES_NO + "\n\n:::"),
            "a pandoc-style opening line": (CALLOUT, CALLOUT.replace("::: callout", "::: {.callout}")),
            "an indented opening line": (CALLOUT, CALLOUT.replace("::: callout", "  ::: callout")),
            "another check mark": (YES_NO, YES_NO.replace("- ✓ Asks", "- ✔ Asks")),
        }
        for name, (old, new) in cases.items():
            with self.subTest(name):
                f = self.folder(blocks_text().replace(old, new))
                try:
                    fs = [x for x in run_scripts.run_text(f.doc(), [])[0] if x.gate == "format"]
                    self.assertTrue(fs, name)
                finally:
                    f.close()

    def test_a_stray_closing_line_swallows_nothing(self):
        t = docs.read_text("<!-- a -->\n:::\nThe pump moves water.\n\n<!-- b -->\nIt runs.\n")
        self.assertEqual([(b.kind, b.element) for b in t.blocks], [("paragraph", "a"), ("paragraph", "b")])
        self.assertEqual(len(t.problems), 1)

    def test_a_plan_kind_written_yes_slash_no_takes_the_block(self):
        f = self.folder(plan=BLOCKS_PLAN.replace("· yes-no ·", "· yes/no ·"))
        try:
            self.assertEqual(formats.fenced_format(f.doc()), [])
        finally:
            f.close()

    def test_an_emoji_check_mark_leaves_no_invisible_character(self):
        y = docs.read_text("<!-- x -->\n::: yes-no\n- ✓\ufe0f Does a.\n- ✗ Does not b.\n:::\n").blocks[0]
        self.assertEqual((y.sides, y.items[0]), (["yes", "no"], "Does a."))

    def test_an_unclosed_callout_stops_at_the_next_marker(self):
        t = docs.read_text("<!-- a -->\n::: callout\nThe pump suits a well.\n\n<!-- b -->\nIt runs.\n")
        self.assertEqual([(b.kind, b.element) for b in t.blocks], [("callout", "a"), ("paragraph", "b")])
        self.assertIn("not closed", t.problems[0][1])

    def test_paragraph_judges_and_scripts_read_a_callout(self):
        two = "::: callout\nThe pump suits a clean well. A timer matters more than a bigger motor\n:::"
        f = self.folder(blocks_text().replace(CALLOUT, two))
        try:
            doc = f.doc()
            i = next(k for k, b in enumerate(doc.text.blocks) if b.kind == "callout")
            self.assertIn(i, no_truncated.gate_truncated(doc, []))
            reqs = jg.text_requests(doc, [])
            self.assertIn(f"callout at TEXT.md line {doc.text.blocks[i].line_no} (S1.e3)",
                          [r.unit for r in reqs if r.gate == "flow-sentences"])
        finally:
            f.close()

    def test_a_term_inside_a_bold_key_phrase_is_marked(self):
        f = self.folder(blocks_text().replace("The *check valve*, a part that holds the water,",
                                              "**The check valve holds the water** and"))
        try:
            self.assertEqual(term_marked.gate_term_marked(f.doc()), [])
        finally:
            f.close()
        f = self.folder(blocks_text().replace("The *check valve*, a part", "The check valve, a part"))
        try:
            self.assertEqual(len(term_marked.gate_term_marked(f.doc())), 1)
        finally:
            f.close()

    def test_a_fenced_block_under_a_paragraph_element_fails(self):
        f = self.folder(plan=BLOCKS_PLAN.replace("S1.e3 · callout", "S1.e3 · paragraph"))
        try:
            fs = formats.fenced_format(f.doc())
            self.assertEqual(len(fs), 1)
            self.assertIn("::: callout", fs[0].why)
        finally:
            f.close()

    def test_a_fenced_block_needs_its_marker(self):
        f = self.folder("::: callout\nA pump moves water.\n:::\n\n" + blocks_text())
        try:
            self.assertIn("a block with no plan element marker", " ".join(x.why for x in formats.text_format(f.doc())))
        finally:
            f.close()
        # without its own marker, the callout falls under the element before it, a figure
        f = self.folder(blocks_text().replace("<!-- S1.e3 -->\n", ""))
        try:
            whys = " ".join(x.why for x in formats.fenced_format(f.doc()))
            self.assertIn("under an element the plan makes «figure»", whys)
        finally:
            f.close()

    def test_sentence_gates_read_the_callout_and_the_yes_no_items(self):
        long = " ".join(["word"] * 25) + "."
        f = self.folder(blocks_text().replace("keeps it primed.", "keeps it primed; " + long)
                        .replace("Fits a part.", "Fits a part; it cannot."))
        try:
            fs = run_scripts.run_text(f.doc(), [])[0]
            where = {(x.gate, x.where.split("(")[1].split(",")[0]) for x in fs if "(" in x.where}
            self.assertIn(("no-semicolon", "S1.e3"), where)
            self.assertIn(("sentence-max-words", "S1.e3"), where)
            self.assertIn(("no-semicolon", "S2.2.e1"), where)
        finally:
            f.close()

    def test_a_term_first_used_in_a_callout_is_found(self):
        f = self.folder()
        try:
            doc = f.doc()
            u = common.first_uses(doc)["check valve"]
            self.assertEqual(doc.text.blocks[u.block].kind, "callout")
            self.assertEqual(term_marked.gate_term_marked(doc), [])
        finally:
            f.close()

    def test_the_yes_no_block_is_led_in_and_judged_for_same_kind(self):
        f = self.folder()
        try:
            doc = f.doc()
            reqs = jg.text_requests(doc, [])
            lead = [r for r in reqs if r.gate == "list-lead-in"]
            self.assertEqual([r.unit.split(" at ")[0] for r in lead], ["yes/no block"])
            same = [r for r in reqs if r.gate == "same-kind"]
            self.assertEqual(len(same), 1)
            self.assertIn("items with ✓ are what the thing does", same[0].input)
        finally:
            f.close()
        f = self.folder(blocks_text().replace("A guest can read the gauge and cannot change it.\n\n", ""))
        try:
            fs = list_lead_in.gate_list_lead_in(f.doc())
            self.assertEqual(len(fs), 1)
            self.assertIn("yes/no block", fs[0].why)
        finally:
            f.close()

    def test_a_callout_is_not_a_lead_in(self):
        f = self.folder(blocks_text().replace("A guest can read the gauge and cannot change it.\n\n",
                                              "::: callout\nA guest only reads.\n:::\n\n"),
                        plan=BLOCKS_PLAN)
        try:
            self.assertEqual(len(list_lead_in.gate_list_lead_in(f.doc())), 1)
        finally:
            f.close()

    def test_element_judges_and_slop_read_both_blocks(self):
        f = self.folder(blocks_text().replace("keeps it primed.", "keeps it primed, a testament to its tapestry.")
                        .replace("Fits a part.", "Fits a part to the tapestry."))
        try:
            doc = f.doc()
            hit = {doc.text.blocks[i].kind for i, _ in slop_words.slop_hits(doc)}
            self.assertLessEqual({"callout", "yes-no"}, hit)
            idio = [r for r in jg.text_requests(doc, []) if r.gate == "cliche"]
            texts = " ".join(r.input for r in idio)
            self.assertIn("testament", texts)
            self.assertIn("Fits a part to the tapestry", texts)
        finally:
            f.close()

    def test_lengths_of_the_blocks(self):
        b = docs.Block("callout", "x", " ".join(["w"] * 25), 1)
        self.assertEqual(docs.block_lines(b, 10), 3)
        y = docs.read_text("<!-- x -->\n::: yes-no\n- ✓ " + " ".join(["w"] * 12) + "\n- ✗ w\n:::\n").blocks[0]
        self.assertEqual(docs.block_lines(y, 10), 3)

    def test_plan_gates_that_read_kinds_take_the_new_kinds(self):
        f = Folder(PLAN=BLOCKS_PLAN)
        try:
            fs = run_scripts.run_plan(f.doc(), 3)
            self.assertEqual([x.line() for x in fs], [])
        finally:
            f.close()


if __name__ == "__main__":
    unittest.main()
