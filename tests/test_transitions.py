"""Tests of the transition gates on TEXT.md: `transition-elements` (two directly neighbouring elements of one leaf),
`transition-subsections` (the seam between two neighbouring subsections of one section) and `transition-sections`
(the seam between two neighbouring sections). Their judge requests come from `judge_gates.text_requests`.

A section of PLAN.md may carry `subsections: parallel` before its size: its subsections stand side by side, so no
seam between its subsections is judged.

  python3 -m unittest tests.test_transitions -v
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_gates import FIXTURE, ROOT, Folder, docs, jg, polish_brief  # noqa: E402
import common  # noqa: E402
import run_scripts  # noqa: E402

TE, TSUB, TSEC = "transition-elements", "transition-subsections", "transition-sections"
EXISTING = ("flow-paragraphs", "flow-sections", "list-lead-in")


# ---------------------------------------------------------------- the main document
#
# S1 has no subsections; S2 has three; S3 has two. Every sentence is unique, so a request is found by the text it
# carries. The text's headings differ from the plan's working titles: the judges see the text's own headings.

MAIN_PLAN = """
    # Plan

    - S1 · **Basics** · what the pump is · 14 lines
      - S1.e1 · paragraph · where the pump sits · 2 lines
      - S1.e2 · table · the parts and their jobs · 3 lines
      - S1.e3 · paragraph · the motor wears out first · 2 lines
      - S1.e4 · bulleted_list · what harms the intake · 2 lines
      - S1.e5 · paragraph · a filter keeps it out · 2 lines
    - S2 · **Settings** · the settings worth changing · 10 lines
      - S2.1 · **Cutoff** · when the cutoff stops the pump · 4 lines
        - S2.1.e1 · paragraph · the cutoff watches the level · 2 lines
        - S2.1.e2 · paragraph · deep and shallow wells · 2 lines
      - S2.2 · **Limits** · who changes the limits · 4 lines
        - S2.2.e1 · paragraph · only the owner · 2 lines
        - S2.2.e2 · paragraph · what high and low limits do · 2 lines
      - S2.3 · **Timer** · the night timer · 2 lines
        - S2.3.e1 · paragraph · the pump runs at night · 2 lines
    - S3 · **Repairs** · what a plumber repairs · 4 lines
      - S3.1 · **Seals** · worn seals · 2 lines
        - S3.1.e1 · paragraph · seals leak · 2 lines
      - S3.2 · **Bearings** · noisy bearings · 2 lines
        - S3.2.e1 · paragraph · bearings hum · 2 lines
    """

TABLE = "| Part | Job |\n|---|---|\n| Impeller | spins the water |\n| Motor | turns the impeller |"
LIST = "- Gravel clogs the intake.\n- Sand scratches the seals."

# (section id, `##` heading, [(subsection id, `###` heading, [(element id, body)])]); a section without
# subsections has one entry with subsection id None.
MAIN = [
    ("S1", "What the pump is", [(None, None, [
        ("S1.e1", "The pump sits in the cellar. It draws water from the well."),
        ("S1.e2", TABLE),
        ("S1.e3", "The motor wears out first. Owners replace it every decade."),
        ("S1.e4", LIST),
        ("S1.e5", "A filter keeps both out. It costs little to fit."),
    ])]),
    ("S2", "Settings that protect the pump", [
        ("S2.1", "When the well runs dry", [
            ("S2.1.e1", "The cutoff watches the water level. It stops the motor on a low well."),
            ("S2.1.e2", "Deep wells rarely trip it. Shallow wells trip it every August."),
        ]),
        ("S2.2", "Who changes the pressure", [
            ("S2.2.e1", "Only the owner changes the pressure limits. A plumber may advise on them."),
            ("S2.2.e2", "High limits strain the tank. Low limits make the taps weak."),
        ]),
        ("S2.3", "Setting the night timer", [
            ("S2.3.e1", "The timer runs the pump at night. Power costs less after midnight."),
        ]),
    ]),
    ("S3", "Repairs a plumber makes", [
        ("S3.1", "Worn seals", [
            ("S3.1.e1", "Seals leak after many starts. A plumber swaps them in an hour."),
        ]),
        ("S3.2", "Noisy bearings", [
            ("S3.2.e1", "Bearings hum before they fail. The plumber greases or replaces them."),
        ]),
    ]),
]


def build_text(structure, drop: tuple = ()) -> str:
    """TEXT.md from `structure`: `##` per section, `###` per subsection, a marker before each element's body. An
    element in `drop` has no text yet; a heading whose elements all have no text is left out too."""
    out = ["# A well pump", ""]
    for sid, sh, subs in structure:
        if all(el in drop for _, _, els in subs for el, _ in els):
            continue
        out += [f"## {sh}", ""]
        for subid, subh, els in subs:
            written = [(el, body) for el, body in els if el not in drop]
            if not written:
                continue
            if subid:
                out += [f"### {subh}", ""]
            for el, body in written:
                out += [f"<!-- {el} -->", body, ""]
    return "\n".join(out)


def folder(plan: str = MAIN_PLAN, structure=MAIN, drop: tuple = (), **files) -> Folder:
    return Folder(PLAN=plan, **{"TEXT.md": build_text(structure, drop), "BRIEF.md": polish_brief()}, **files)


def parallel(plan: str, sid: str) -> str:
    """`plan` with `subsections: parallel` added to the item `sid` (a section, subsection or element)."""
    lines = textwrap.dedent(plan).splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith(f"- {sid} · "):
            head, size = line.rsplit(" · ", 1)
            lines[i] = f"{head} · subsections: parallel · {size}"
            return "\n".join(lines) + "\n"
    raise AssertionError(sid)


def reqs_of(doc, gate: str):
    return [r for r in jg.text_requests(doc, []) if r.gate == gate]


def carrying(reqs, *texts: str):
    """The requests whose input carries every one of `texts`."""
    return [r for r in reqs if all(t in r.input for t in texts)]


# ---------------------------------------------------------------- transition-elements

class TransitionElements(unittest.TestCase):
    """Done when 1-2: one request per pair of directly neighbouring elements inside one leaf; never across a leaf
    border, never skipping an element; no pair whose later element opens with a list, tiles, table, yes/no or steps
    block (list-lead-in covers it); a table or list followed by a paragraph is a pair."""

    def setUp(self):
        self.f = folder()
        self.reqs = reqs_of(self.f.doc(), TE)

    def tearDown(self):
        self.f.close()

    def test_one_request_per_built_pair_in_the_whole_text(self):
        # S1: table->para, list->para; S2.1: e1->e2; S2.2: e1->e2. Leaves with one element give none.
        self.assertEqual(len(self.reqs), 4, [r.unit for r in self.reqs])

    def test_neighbours_in_a_subsection_are_a_pair(self):
        self.assertEqual(len(carrying(self.reqs, "Shallow wells trip it every August.",
                                      "The cutoff watches the water level.")), 1)
        self.assertEqual(len(carrying(self.reqs, "A plumber may advise on them.",
                                      "High limits strain the tank.")), 1)

    def test_table_then_paragraph_is_a_pair_with_the_table_and_the_paragraphs_start(self):
        got = carrying(self.reqs, "spins the water", "turns the impeller", "The motor wears out first.")
        self.assertEqual(len(got), 1, [r.input for r in self.reqs])

    def test_list_then_paragraph_is_a_pair_with_the_list_and_the_paragraphs_start(self):
        got = carrying(self.reqs, "Gravel clogs the intake.", "Sand scratches the seals.", "A filter keeps both out.")
        self.assertEqual(len(got), 1, [r.input for r in self.reqs])

    def test_paragraph_then_table_or_list_is_not_a_pair(self):
        self.assertTrue(self.reqs, f"no {TE} request at all: nothing to check")
        self.assertEqual(carrying(self.reqs, "It draws water from the well.", "spins the water"), [])
        self.assertEqual(carrying(self.reqs, "Owners replace it every decade.", "Gravel clogs the intake."), [])

    def test_no_pair_skips_an_element(self):
        self.assertTrue(self.reqs, f"no {TE} request at all: nothing to check")
        # para (e1), table (e2), para (e3): no e1->e3; para (e3), list (e4), para (e5): no e3->e5
        self.assertEqual(carrying(self.reqs, "It draws water from the well.", "The motor wears out first."), [])
        self.assertEqual(carrying(self.reqs, "Owners replace it every decade.", "A filter keeps both out."), [])

    def test_no_pair_across_a_leaf_border(self):
        self.assertTrue(self.reqs, f"no {TE} request at all: nothing to check")
        for earlier, later in (
                ("Shallow wells trip it every August.", "Only the owner changes the pressure limits."),  # S2.1|S2.2
                ("Low limits make the taps weak.", "The timer runs the pump at night."),               # S2.2|S2.3
                ("A plumber swaps them in an hour.", "Bearings hum before they fail."),               # S3.1|S3.2
                ("It costs little to fit.", "The cutoff watches the water level."),                   # S1|S2
                ("Power costs less after midnight.", "Seals leak after many starts."),                # S2|S3
        ):
            with self.subTest(earlier=earlier):
                self.assertEqual(carrying(self.reqs, earlier, later), [])

    def test_a_leaf_with_one_element_gives_no_pair(self):
        self.assertTrue(self.reqs, f"no {TE} request at all: nothing to check")
        for only in ("The timer runs the pump at night.", "Seals leak after many starts.",
                     "Bearings hum before they fail."):
            with self.subTest(only=only):
                self.assertEqual(carrying(self.reqs, only), [])


    def test_an_element_with_no_plan_row_breaks_the_chain(self):
        # a block under a marker the plan does not know sits between S2.1.e1 and S2.1.e2: they are no neighbours
        text = build_text(MAIN).replace("<!-- S2.1.e2 -->", "<!-- S2.1.x -->\nA stray note on the cutoff.\n\n"
                                                             "<!-- S2.1.e2 -->")
        f = Folder(PLAN=MAIN_PLAN, **{"TEXT.md": text, "BRIEF.md": polish_brief()})
        try:
            reqs = reqs_of(f.doc(), TE)
            self.assertEqual(carrying(reqs, "It stops the motor on a low well.", "Deep wells rarely trip it."), [])
            self.assertEqual(carrying(reqs, "A stray note on the cutoff."), [])
            self.assertEqual(len(reqs), 3, [r.unit for r in reqs])
        finally:
            f.close()

# A leaf of four elements: a paragraph, another paragraph, the block under test, a paragraph.
BLOCKS = {
    "bulleted_list": ("list", LIST, "Gravel clogs the intake."),
    "table": ("table", TABLE, "spins the water"),
    "tiles": ("tiles", "- ![a coiled hose](figures/S1.e3.t1.svg) **Hose:** reaches every bed from one tap.\n"
                       "- ![a tin can](figures/S1.e3.t2.svg) **Can:** carries water to a few pots.",
              "reaches every bed from one tap"),
    "yes_no": ("yes-no", "::: yes-no\n- ✓ Moves clean water from a well.\n- ✗ Moves water with sand in it.\n:::",
               "Moves clean water from a well."),
    "steps vertical": ("steps", "::: steps vertical\n1. **Open the cap:** turn it to the left.\n"
                                "2. **Fill the body:** pour water in to the top.\n:::",
                       "turn it to the left"),
}
TILES = ("        - S1.e3.t1 · **Hose** · reaches every bed from one tap · graphic: a coiled hose · 1 lines\n"
         "        - S1.e3.t2 · **Can** · carries water to a few pots · graphic: a tin can · 1 lines\n")


def one_leaf(kind: str):
    plan = ("# Plan\n\n- S1 · **Basics** · what the pump is · 8 lines\n"
            "  - S1.e1 · paragraph · where the pump sits · 2 lines\n"
            "  - S1.e2 · paragraph · what it draws · 2 lines\n"
            f"  - S1.e3 · {kind} · the block · 2 lines\n"
            + (TILES.replace("        ", "    ") if kind == "tiles" else "") +
            "  - S1.e4 · paragraph · a filter keeps it out · 2 lines\n")
    structure = [("S1", "What the pump is", [(None, None, [
        ("S1.e1", "The pump sits in the cellar."),
        ("S1.e2", "It draws water from the well."),
        ("S1.e3", BLOCKS[kind][1]),
        ("S1.e4", "A filter keeps the grit out. It costs little to fit."),
    ])])]
    return Folder(PLAN=plan, **{"TEXT.md": build_text(structure), "BRIEF.md": polish_brief()})


class LaterElementOpensWithABlock(unittest.TestCase):
    """Done when 2: the pair is not built when the later element opens with a list, tiles, table, yes/no or steps
    block; the pair of two paragraphs before it in the same leaf still is."""

    def test_no_pair_into_the_block(self):
        for kind, (block_kind, _, block_text) in BLOCKS.items():
            with self.subTest(kind=kind):
                f = one_leaf(kind)
                try:
                    doc = f.doc()
                    first = next(b for b in doc.text.blocks if b.element == "S1.e3")
                    self.assertEqual(first.kind, block_kind)   # the fixture really opens with that block
                    reqs = reqs_of(doc, TE)
                    self.assertEqual(len(carrying(reqs, "The pump sits in the cellar.",
                                                  "It draws water from the well.")), 1)
                    self.assertEqual(carrying(reqs, "It draws water from the well.", block_text), [])
                finally:
                    f.close()

    def test_table_or_list_then_paragraph_is_a_pair(self):
        for kind in ("bulleted_list", "table"):
            with self.subTest(kind=kind):
                f = one_leaf(kind)
                try:
                    reqs = reqs_of(f.doc(), TE)
                    self.assertEqual(len(carrying(reqs, BLOCKS[kind][2], "A filter keeps the grit out.")), 1)
                finally:
                    f.close()


# ---------------------------------------------------------------- excerpts

E1 = ["Ada opens the gate.", "Ben checks the meter.", "Cal reads the gauge.", "Dan notes the level.",
      "Eve closes the valve.", "Fay locks the shed."]
E2 = ["Gus starts the motor.", "Hal hears a click.", "Ian waits a minute.", "Jon sees the pressure rise.",
      "Kim fills a glass.", "Lou tastes the water."]
E3 = ["Max drains the tank.", "Ned rinses the filter.", "Oli refits the cap."]
E4 = ["Pat primes the pump.", "Quin restarts it.", "Ray watches the gauge.", "Sam signs the log."]


class Excerpts(unittest.TestCase):
    """Done when 3: a paragraph of more than three sentences goes into the input as its last two sentences (the
    earlier element) or its first two (the later one), never its middle; a paragraph of up to three goes whole."""

    def setUp(self):
        plan = ("# Plan\n\n- S1 · **Start** · the first start · 16 lines\n"
                + "".join(f"  - S1.e{k} · paragraph · step {k} · 4 lines\n" for k in (1, 2, 3, 4)))
        structure = [("S1", "The first start", [(None, None, [
            (f"S1.e{k}", " ".join(s)) for k, s in ((1, E1), (2, E2), (3, E3), (4, E4))])])]
        self.f = Folder(PLAN=plan, **{"TEXT.md": build_text(structure), "BRIEF.md": polish_brief()})
        self.reqs = reqs_of(self.f.doc(), TE)

    def tearDown(self):
        self.f.close()

    def pair(self, earlier: str, later: str):
        got = carrying(self.reqs, earlier, later)
        self.assertEqual(len(got), 1, [r.input for r in self.reqs])
        return got[0].input

    def test_three_pairs(self):
        self.assertEqual(len(self.reqs), 3)

    def test_long_then_long(self):
        inp = self.pair(E1[-1], E2[0])
        for s in E1[-2:] + E2[:2]:
            self.assertIn(s, inp)
        for s in E1[1:4] + E2[2:5]:
            self.assertNotIn(s, inp)

    def test_long_then_short_goes_whole(self):
        inp = self.pair(E2[-1], E3[0])
        for s in E2[-2:] + E3:
            self.assertIn(s, inp)
        for s in E2[1:4]:
            self.assertNotIn(s, inp)

    def test_short_then_four_sentences(self):
        inp = self.pair(E3[-1], E4[0])
        for s in E3 + E4[:2]:
            self.assertIn(s, inp)
        self.assertNotIn(E4[2], inp)

    def test_a_long_table_goes_as_its_first_lines(self):
        rows = "".join(f"| Model {k:02d} | {'a long description of this pump model ' * 3}|\n" for k in range(40))
        table = "| Model | What it does |\n|---|---|\n" + rows.rstrip("\n")
        f = one_leaf("table")
        try:
            text = (f.path / "TEXT.md").read_text(encoding="utf-8").replace(BLOCKS["table"][1], table)
            (f.path / "TEXT.md").write_text(text, encoding="utf-8")
            reqs = carrying(reqs_of(f.doc(), TE), "Model 00", "A filter keeps the grit out.")
            self.assertEqual(len(reqs), 1)
            self.assertNotIn("Model 39", reqs[0].input)
            self.assertIn("more lines not shown", reqs[0].input)
        finally:
            f.close()


# ---------------------------------------------------------------- transition-subsections

class TransitionSubsections(unittest.TestCase):
    """Done when 4: one request per seam between two neighbouring subsections of one section, once the later one has
    text; its input has the end of the earlier subsection, the next one's `###` heading and the start of its first
    element. No seam across sections."""

    SEAMS = (("Shallow wells trip it every August.", "Who changes the pressure",
              "Only the owner changes the pressure limits."),
             ("Low limits make the taps weak.", "Setting the night timer", "The timer runs the pump at night."),
             ("A plumber swaps them in an hour.", "Noisy bearings", "Bearings hum before they fail."))

    def test_one_request_per_seam_with_end_heading_and_start(self):
        f = folder()
        try:
            reqs = reqs_of(f.doc(), TSUB)
            self.assertEqual(len(reqs), 3, [r.unit for r in reqs])
            for end, heading, start in self.SEAMS:
                with self.subTest(heading=heading):
                    self.assertEqual(len(carrying(reqs, end, heading, start)), 1)
        finally:
            f.close()

    def test_no_seam_across_sections(self):
        f = folder()
        try:
            reqs = reqs_of(f.doc(), TSUB)
            self.assertTrue(reqs, "no transition-subsections request at all: nothing to check")
            # S2.3 (last of S2) -> S3.1 (first of S3) is a section seam, not a subsection seam
            self.assertEqual(carrying(reqs, "Power costs less after midnight.", "Seals leak after many starts."), [])
        finally:
            f.close()

    def test_waits_for_the_later_subsection_to_have_text(self):
        f = folder(drop=("S2.3.e1", "S3.2.e1"))
        try:
            reqs = reqs_of(f.doc(), TSUB)
            self.assertEqual(len(reqs), 1, [r.unit for r in reqs])
            self.assertEqual(len(carrying(reqs, *self.SEAMS[0])), 1)
        finally:
            f.close()


    def test_the_intro_of_a_section_and_its_first_subsection(self):
        # S2 opens with an intro, a subsection of its own the text gives no `###` heading
        plan = MAIN_PLAN.replace("      - S2.1 · **Cutoff**",
                                 "      - S2.0 · **Intro** · why settings matter · 2 lines\n"
                                 "        - S2.0.e1 · paragraph · wrong settings wear the pump · 2 lines\n"
                                 "      - S2.1 · **Cutoff**")
        structure = [(sid, sh, ([(None, None, [("S2.0.e1", "Wrong settings wear the pump out. Three guard it.")])]
                                if sid == "S2" else []) + subs) for sid, sh, subs in MAIN]
        text = build_text(structure)
        f = Folder(PLAN=plan, **{"TEXT.md": text, "BRIEF.md": polish_brief()})
        try:
            doc = f.doc()
            self.assertEqual(doc.plan_problems, [])
            sub = carrying(reqs_of(doc, TSUB), "Three guard it.", "### When the well runs dry",
                           "The cutoff watches the water level.")
            self.assertEqual(len(sub), 1, [r.input for r in reqs_of(doc, TSUB)])
            self.assertIn("## Settings that protect the pump", sub[0].input)
            self.assertIn("intro", sub[0].input)
            self.assertEqual(carrying(reqs_of(doc, TE), "Three guard it.", "The cutoff watches the water level."), [])
            sec = carrying(reqs_of(doc, TSEC), "It costs little to fit.", "Wrong settings wear the pump out.")
            self.assertEqual(len(sec), 1)
            self.assertNotIn("When the well runs dry", sec[0].input)
        finally:
            f.close()

# ---------------------------------------------------------------- subsections: parallel

class ParallelSubsections(unittest.TestCase):
    """Done when 5: a section marked `subsections: parallel` gets no transition-subsections request for any seam
    inside it; other sections keep theirs; element pairs inside its subsections and the section seams around it
    stay."""

    def test_the_plan_field(self):
        plans, problems = docs.read_plan(parallel(MAIN_PLAN, "S2"))
        self.assertEqual(problems, [])
        rows = {r.id: r for r in plans[1]}
        self.assertEqual(rows["S2"].get("subsections"), "parallel")
        self.assertFalse(rows["S3"].get("subsections"))
        self.assertIn("subsections: parallel", docs.level_text(plans[1]))
        self.assertIn("subsections: parallel", docs.plan_text(plans, 3))

    def test_the_field_on_a_subsection_or_an_element_is_a_format_problem(self):
        for rid in ("S2.1", "S2.1.e1"):
            with self.subTest(rid=rid):
                _, problems = docs.read_plan(parallel(MAIN_PLAN, rid))
                self.assertTrue([p for p in problems if rid in p], problems)

    def test_a_marked_section_needs_two_subsections_once_they_are_written(self):
        one_sub = parallel(MAIN_PLAN, "S3").replace(
            "  - S3.2 · **Bearings** · noisy bearings · 2 lines\n"
            "    - S3.2.e1 · paragraph · bearings hum · 2 lines\n", "")
        self.assertNotIn("S3.2", one_sub)
        _, problems = docs.read_plan(one_sub)
        self.assertTrue([p for p in problems if p.startswith("S3:")], problems)
        sections_only = "# Plan\n\n- S1 · **Basics** · what the pump is · subsections: parallel · 4 lines\n"
        self.assertEqual(docs.read_plan(sections_only)[1], [])

    def test_the_field_on_a_subsection_reports_only_that(self):
        _, problems = docs.read_plan(parallel(MAIN_PLAN, "S2.1"))
        self.assertEqual(len(problems), 1, problems)

    def test_no_subsection_seam_inside_a_parallel_section(self):
        f = folder(plan=parallel(MAIN_PLAN, "S2"))
        try:
            doc = f.doc()
            self.assertEqual(doc.plan_problems, [])
            sub = reqs_of(doc, TSUB)
            self.assertEqual(len(sub), 1, [r.unit for r in sub])                   # S3.1 -> S3.2 only
            self.assertEqual(len(carrying(sub, "Noisy bearings", "Bearings hum before they fail.")), 1)
            for heading in ("Who changes the pressure", "Setting the night timer"):
                self.assertEqual(carrying(sub, heading), [])
            el = reqs_of(doc, TE)
            self.assertEqual(len(el), 4)
            self.assertEqual(len(carrying(el, "Shallow wells trip it every August.",
                                          "The cutoff watches the water level.")), 1)
            self.assertEqual(len(carrying(el, "High limits strain the tank.")), 1)
            self.assertEqual(len(reqs_of(doc, TSEC)), 2)
        finally:
            f.close()


# ---------------------------------------------------------------- transition-sections

class TransitionSections(unittest.TestCase):
    """Done when 6: one request per seam between two neighbouring sections, once the later section has text; its
    input has the end of the earlier section, the next section's `##` heading and the start of its first element."""

    SEAMS = (("It costs little to fit.", "Settings that protect the pump", "The cutoff watches the water level."),
             ("Power costs less after midnight.", "Repairs a plumber makes", "Seals leak after many starts."))

    def test_one_request_per_seam_with_end_heading_and_start(self):
        f = folder()
        try:
            reqs = reqs_of(f.doc(), TSEC)
            self.assertEqual(len(reqs), 2, [r.unit for r in reqs])
            for end, heading, start in self.SEAMS:
                with self.subTest(heading=heading):
                    self.assertEqual(len(carrying(reqs, end, heading, start)), 1)
        finally:
            f.close()

    def test_the_earlier_sections_heading_is_its_own_and_its_last_subsections(self):
        # S2 -> S3: S2's heading and its last subsection's, never its first subsection's (the end is not there)
        f = folder()
        try:
            got = carrying(reqs_of(f.doc(), TSEC), *self.SEAMS[1])
            self.assertEqual(len(got), 1)
            inp = got[0].input
            self.assertIn("## Settings that protect the pump", inp)
            self.assertIn("### Setting the night timer", inp)
            self.assertNotIn("When the well runs dry", inp)
        finally:
            f.close()

    def test_waits_for_the_later_section_to_have_text(self):
        f = folder(drop=("S3.1.e1", "S3.2.e1"))
        try:
            reqs = reqs_of(f.doc(), TSEC)
            self.assertEqual(len(reqs), 1, [r.unit for r in reqs])
            self.assertEqual(len(carrying(reqs, *self.SEAMS[0])), 1)
        finally:
            f.close()

    def test_built_once_the_later_section_has_some_text(self):
        # S3 has text in S3.1 only: the S2 -> S3 seam is built, the S3.1 -> S3.2 seam is not yet
        f = folder(drop=("S3.2.e1",))
        try:
            doc = f.doc()
            self.assertEqual(len(carrying(reqs_of(doc, TSEC), *self.SEAMS[1])), 1)
            self.assertEqual(carrying(reqs_of(doc, TSUB), "Noisy bearings"), [])
        finally:
            f.close()


# ---------------------------------------------------------------- switching off, library

def gates_off_md(value: str) -> str:
    return (FIXTURE / "GATES.md").read_text(encoding="utf-8").rstrip("\n") + f"\ngates_off: {value}\n"


class SwitchedOff(unittest.TestCase):
    """Done when 7: the three are gates of gates/library.md, and a gate switched off in GATES.md loses its
    requests to `common.drop_off`, the others keep theirs."""

    def test_library_knows_the_three(self):
        names = common.library_gates()
        for g in (TE, TSUB, TSEC):
            self.assertIn(g, names)

    def test_every_transition_gate_has_a_judge(self):
        for g in (TE, TSUB, TSEC):
            self.assertTrue((ROOT / "gates" / "judges" / f"gate-{g}.md").exists(), g)

    def test_one_gate_off(self):
        f = folder(**{"GATES.md": gates_off_md(f"{TE} (the brief wants short hops)")})
        try:
            doc = f.doc()
            kept = common.drop_off(doc, jg.text_requests(doc, []), "text")
            gates = [r.gate for r in kept]
            self.assertNotIn(TE, gates)
            self.assertIn(TSUB, gates)
            self.assertIn(TSEC, gates)
        finally:
            f.close()

    def test_all_three_off_leave_the_other_gates(self):
        f = folder(**{"GATES.md": gates_off_md(f"{TE} (a); {TSUB} (b); {TSEC} (c)")})
        try:
            doc = f.doc()
            reqs = jg.text_requests(doc, [])
            self.assertTrue({TE, TSUB, TSEC} <= {r.gate for r in reqs})      # built, then dropped
            gates = {r.gate for r in common.drop_off(doc, reqs, "text")}
            self.assertFalse(gates & {TE, TSUB, TSEC})
            self.assertIn("flow-paragraphs", gates)
        finally:
            f.close()

    def test_switching_them_off_is_no_config_failure(self):
        f = folder(**{"GATES.md": gates_off_md(f"{TE} (a); {TSUB} (b); {TSEC} (c)")})
        try:
            fails, _ = run_scripts.run_text(f.doc(), [])
            self.assertEqual([x.line() for x in fails if x.gate == "config"], [])
        finally:
            f.close()


# ---------------------------------------------------------------- the existing gates stay as they are

# (gate, unit, id) of flow-paragraphs, flow-sections and list-lead-in, recorded before the transition gates existed.
SNAPSHOT_MAIN = [
    ("flow-paragraphs", "paragraph at TEXT.md line 15 (S1.e3)", "flow-paragraphs-8d4a33a37af0"),
    ("flow-paragraphs", "paragraph at TEXT.md line 22 (S1.e5)", "flow-paragraphs-eeac367b7c10"),
    ("flow-paragraphs", "paragraph at TEXT.md line 32 (S2.1.e2)", "flow-paragraphs-05960f33d0d4"),
    ("flow-paragraphs", "paragraph at TEXT.md line 40 (S2.2.e2)", "flow-paragraphs-ee9ed8b32b4b"),
    ("flow-sections", "section S1", "flow-sections-d7dc4e6a1f9c"),
    ("flow-sections", "section S2", "flow-sections-ba0c72b85f20"),
    ("flow-sections", "section S3", "flow-sections-1a36434b84f9"),
    ("list-lead-in", "list at TEXT.md line 18 (S1.e4)", "list-lead-in-7d843a6bf1c5"),
    ("list-lead-in", "table at TEXT.md line 9 (S1.e2)", "list-lead-in-486122b94d47"),
]
SNAPSHOT_FIXTURE = [
    ("flow-paragraphs", "paragraph at TEXT.md line 12 (S1.e3)", "flow-paragraphs-e9ebb15ba9a7"),
    ("flow-sections", "section S1", "flow-sections-ee1fe114e490"),
    ("flow-sections", "section S2", "flow-sections-be6cc621c854"),
    ("list-lead-in", "list at TEXT.md line 26 (S2.2.e1)", "list-lead-in-a725329a036e"),
]


def existing(doc):
    return sorted((r.gate, r.unit, r.id) for r in jg.text_requests(doc, []) if r.gate in EXISTING)


class ExistingGatesUnchanged(unittest.TestCase):
    """flow-paragraphs, flow-sections and list-lead-in produce exactly what they produced before."""

    def test_main_document(self):
        f = folder()
        try:
            self.assertEqual(existing(f.doc()), SNAPSHOT_MAIN)
        finally:
            f.close()

    def test_fixture_document(self):
        self.assertEqual(existing(docs.load(FIXTURE)), SNAPSHOT_FIXTURE)


if __name__ == "__main__":
    unittest.main()
