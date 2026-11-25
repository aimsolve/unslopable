"""Tests of the tiles gate: every tile has a graphic drawn for it, and a tile's body is at most 2 lines.

Tiles are a plan element of kind `tiles`. In PLAN.md each tile is a sub-item of that element,
`id · **title** · body · graphic: what the picture shows · N lines`; in TEXT.md each tile is a list item,
`- ![alt](figures/<tile id>.svg) **Title:** body`.

The document used here is a small one about watering a garden (GARDEN_* below), written into a copy of the fixture
folder by test_gates.Folder. Its plan and text pass every plan gate, so a failure in a test comes from the tile.

  python3 -m unittest tests.test_tiles -v
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

from test_gates import FIXTURE, ROOT, Folder, png_bytes  # noqa: E402

import docs  # noqa: E402  (test_gates put gates/lib and gates/scripts on sys.path)
import figure_files  # noqa: E402
import figure_gates  # noqa: E402
import common  # noqa: E402
import formats  # noqa: E402
import run_scripts  # noqa: E402

TILE_GATES = ("tile-length", "tile-graphic")

GARDEN_BRIEF = """
Approved by Test Author, 2026-11-19

# Brief

## Reader
A person with a small garden who waters it by hand.

## Need
They must pick one way to water the beds this summer.

## After reading
They pick a hose or a watering can.

## Goals
1. Know why the beds dry out.
2. Know which tool suits which garden.

## Format
A 1-page PDF.

## Tone
Plain.

## Out of scope
Buying seeds.

## Language, brand, author
Polish. No brand. Test Author.
"""
# The brief says Polish so that run_text skips the spaCy gate (it needs uv and takes seconds); the tile gates do not
# depend on the language.

GARDEN_TERMS = "# Terms\n"

# Sections 10 + 10 = 20 lines (GATES.md total_lines: 20); every part's elements add up to the part.
GARDEN_PLAN = """
# Plan

- S1 · **Dry beds** · why the beds dry out · 10 lines
  - S1.e1 · paragraph · the sun dries the beds by noon · facts: F1 · 4 lines
  - S1.e2 · figure · the beds of one garden · 6 lines
- S2 · **Tools for watering** · the tools a gardener picks from · 10 lines
  - S2.1 · **Rain** · what rain gives the beds · 3 lines
    - S2.1.e1 · paragraph · rain waters the beds for free · facts: F2 · 3 lines
  - S2.2 · **Tools** · the tools to pick from · 7 lines
    - S2.2.e1 · tiles · the ways to water a garden the reader picks from · 6 lines
      - S2.2.e1.t1 · **Hose** · reaches every bed from one tap · graphic: a coiled green hose with a spray nozzle · 2 lines
      - S2.2.e1.t2 · **Watering can** · carries water to a few pots · graphic: a tin watering can pouring on a pot · 1 line
"""

HOSE = "- S2.2.e1.t1 · **Hose** · reaches every bed from one tap · graphic: a coiled green hose with a spray nozzle · 2 lines"
CAN = "- S2.2.e1.t2 · **Watering can** · carries water to a few pots · graphic: a tin watering can pouring on a pot · 1 line"

# The same garden plan with the tiles element written as a plain list and no tile sub-items.
GARDEN_PLAN_NO_TILES = "\n".join(
    ln for ln in GARDEN_PLAN.splitlines() if "S2.2.e1.t" not in ln
).replace("S2.2.e1 · tiles · the ways to water a garden the reader picks from", "S2.2.e1 · list · the ways to water a garden")

TWELVE_WORDS = "reaches every bed in the garden from one tap by the door"           # 12 words: 2 lines × 6
THIRTEEN_WORDS = "reaches every bed in the garden from one tap by the back door"    # 13 words: over the budget

HOSE_ALT = "A coiled green hose with a spray nozzle"
CAN_ALT = "A tin watering can pouring on a pot"
HOSE_ITEM = f"- ![{HOSE_ALT}](figures/S2.2.e1.t1.svg) **Hose:** reaches every bed from one tap."
CAN_ITEM = f"- ![{CAN_ALT}](figures/S2.2.e1.t2.svg) **Watering can:** carries water to a few pots."

GARDEN_TEXT = f"""
# Watering a small garden

## Dry beds

<!-- S1.e1 -->
The summer sun dries the beds by noon. A bed that dries out every day loses its young plants.

<!-- S1.e2 -->
![The beds of one garden](figures/S1.e2.svg)

## Tools for watering

### Rain

<!-- S2.1.e1 -->
Rain waters every bed for free. In a dry month it does not come often enough.

### Tools

<!-- S2.2.e1 -->
A gardener picks one way to water the beds.

{HOSE_ITEM}
{CAN_ITEM}
"""


def drawing(*shapes: str) -> str:
    """A small valid SVG; different shapes give different bytes."""
    body = "".join(shapes) or '<rect x="0" y="0" width="80" height="40" fill="#12A98D"/>'
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">{body}</svg>'


HOSE_SVG = drawing('<circle cx="50" cy="50" r="30" fill="none" stroke="#2E7D32" stroke-width="6"/>')
CAN_SVG = drawing('<rect x="20" y="40" width="50" height="40" fill="#9E9E9E"/>', '<line x1="70" y1="45" x2="95" y2="25" stroke="#9E9E9E"/>')
BEDS_SVG = drawing('<rect x="5" y="5" width="40" height="90" fill="#795548"/>', '<rect x="55" y="5" width="40" height="90" fill="#795548"/>')


def garden(plan: str = GARDEN_PLAN, text: str | None = GARDEN_TEXT, gates_extra: str = "",
           figures: dict | None = None) -> Folder:
    """The garden document in a temp folder. `figures` maps a name under figures/ to its str or bytes content;
    by default the two tile graphics and the S1.e2 diagram are there, each different."""
    gates = (FIXTURE / "GATES.md").read_text(encoding="utf-8") + gates_extra
    f = Folder(PLAN=plan, **{"BRIEF.md": GARDEN_BRIEF, "TERMS.md": GARDEN_TERMS, "GATES.md": gates,
                             "TEXT.md": text})
    figs = {"S2.2.e1.t1.svg": HOSE_SVG, "S2.2.e1.t2.svg": CAN_SVG, "S1.e2.svg": BEDS_SVG} if figures is None \
        else figures
    (f.path / "figures").mkdir(exist_ok=True)
    for name, body in figs.items():
        p = f.path / "figures" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
    return f


def tiles_of(row) -> list:
    """A plan row's tiles; a missing attribute is a test failure, not an error."""
    if not hasattr(row, "tiles"):
        raise AssertionError(f"PlanRow {row.id} has no attribute `tiles`")
    return row.tiles


def plan_fails(f: Folder, gate: str, upto: int = 3):
    return [x for x in run_scripts.run_plan(f.doc(), upto) if x.gate == gate]


def text_fails(f: Folder, gate: str):
    fails, _ = run_scripts.run_text(f.doc(), [])
    return [x for x in fails if x.gate == gate]


def said(x) -> str:
    """Everything a failure says, to look for a name in it."""
    return f"{x.where} {x.quote} {x.why}"


# ---------------------------------------------------------------- PLAN.md


class PlanTiles(unittest.TestCase):
    """The plan gives each tile its title, a body of at most 2 lines and what its graphic shows."""

    # -- reading the plan

    def test_tiles_are_read_under_their_element(self):
        plans, probs = docs.read_plan(GARDEN_PLAN.lstrip("\n"))
        self.assertEqual(probs, [])
        el = next(r for r in plans[3] if r.id == "S2.2.e1")
        tiles = tiles_of(el)
        self.assertEqual([t.id for t in tiles], ["S2.2.e1.t1", "S2.2.e1.t2"])
        hose = tiles[0]
        self.assertEqual(hose.level, 4)
        self.assertEqual(hose.get("parent"), "S2.2.e1")
        self.assertEqual(hose.get("title"), "Hose")
        self.assertEqual(hose.get("body"), "reaches every bed from one tap")
        self.assertEqual(hose.get("graphic"), "a coiled green hose with a spray nozzle")
        self.assertEqual(hose.lines, 2)
        self.assertEqual(tiles[1].get("title"), "Watering can")
        self.assertEqual(tiles[1].lines, 1)

    def test_tiles_are_not_elements(self):
        f = garden()
        try:
            d = f.doc()
            self.assertEqual(d.plan_problems, [])
            self.assertEqual([r.id for r in d.plans[3]], ["S1.e1", "S1.e2", "S2.1.e1", "S2.2.e1"])
            for r in d.plans[3]:
                if r.id != "S2.2.e1":
                    self.assertEqual(tiles_of(r), [], r.id)
            self.assertEqual(len(tiles_of(d.plan_row("S2.2.e1"))), 2)
        finally:
            f.close()

    # -- format problems

    def test_sub_item_under_an_element_that_is_not_tiles_is_still_a_problem(self):
        # regression: only a tiles element has items under it
        _, probs = docs.read_plan(GARDEN_PLAN.replace(
            "S2.2.e1 · tiles · the ways to water a garden the reader picks from",
            "S2.2.e1 · list · the ways to water a garden").lstrip("\n"))
        self.assertTrue(any("S2.2.e1.t1" in p for p in probs), probs)

    def test_tile_with_four_fields_is_a_format_problem(self):
        plan = GARDEN_PLAN.replace(CAN, "- S2.2.e1.t2 · **Watering can** · carries water to a few pots · 1 line")
        _, probs = docs.read_plan(plan.lstrip("\n"))
        self.assertTrue(any("S2.2.e1.t2" in p for p in probs), probs)
        self.assertFalse(any("S2.2.e1.t1" in p for p in probs), f"the well-formed tile was reported: {probs}")

    def test_tile_whose_fourth_field_is_not_graphic_is_a_format_problem(self):
        plan = GARDEN_PLAN.replace(CAN, "- S2.2.e1.t2 · **Watering can** · carries water to a few pots · "
                                        "facts: F3 · 1 line")
        _, probs = docs.read_plan(plan.lstrip("\n"))
        self.assertTrue(any("S2.2.e1.t2" in p for p in probs), probs)
        self.assertFalse(any("S2.2.e1.t1" in p for p in probs), f"the well-formed tile was reported: {probs}")
        f = garden(plan)
        try:
            self.assertIn(("format", "PLAN.md"), {(x.gate, x.where) for x in run_scripts.run_plan(f.doc(), 3)})
        finally:
            f.close()

    # -- approval covers the tiles

    def test_level_text_of_the_elements_shows_the_tiles(self):
        plans, _ = docs.read_plan(GARDEN_PLAN.lstrip("\n"))
        lt = docs.level_text(plans[3])
        self.assertIn("S2.2.e1.t1", lt)
        self.assertIn("a coiled green hose with a spray nozzle", lt)
        self.assertIn("carries water to a few pots", lt)
        # editing one tile changes what the elements' approval is about, so the approval goes stale
        edited, _ = docs.read_plan(GARDEN_PLAN.replace("from one tap", "from the tap by the shed").lstrip("\n"))
        self.assertNotEqual(docs.level_text(edited[3]), lt)

    def test_level_text_without_tiles_is_unchanged(self):
        plans, probs = docs.read_plan(GARDEN_PLAN_NO_TILES.lstrip("\n"))
        self.assertEqual(probs, [])
        self.assertEqual(docs.level_text(plans[3]),
                         "- S1.e1 (under S1) · paragraph · the sun dries the beds by noon · facts: F1 · 4 lines\n"
                         "- S1.e2 (under S1) · figure · the beds of one garden · 6 lines\n"
                         "- S2.1.e1 (under S2.1) · paragraph · rain waters the beds for free · facts: F2 · 3 lines\n"
                         "- S2.2.e1 (under S2.2) · list · the ways to water a garden · 6 lines\n")

    # -- the plan gates

    def test_a_plan_with_good_tiles_passes_every_plan_gate(self):
        f = garden()
        try:
            d = f.doc()
            self.assertEqual(len(tiles_of(d.plan_row("S2.2.e1"))), 2)
            for lvl in (1, 2, 3):
                self.assertEqual([x.line() for x in run_scripts.run_plan(d, lvl)], [], lvl)
        finally:
            f.close()

    def test_tile_planned_over_two_lines_fails(self):
        f = garden(GARDEN_PLAN.replace("graphic: a tin watering can pouring on a pot · 1 line",
                                       "graphic: a tin watering can pouring on a pot · 3 lines"))
        try:
            fails = plan_fails(f, "tile-length")
            self.assertEqual(len(fails), 1, [x.line() for x in fails])
            self.assertIn("S2.2.e1.t2", fails[0].where)
            why = fails[0].why.lower()
            self.assertIn("shorten", why)   # the planner shortens the tile ...
            self.assertIn("text", why)      # ... or moves the explanation into the text next to the tiles
        finally:
            f.close()

    def test_tile_body_over_the_word_budget_fails_and_at_the_budget_passes(self):
        # budget: 2 lines × tile_words_per_line (default 6) = 12 words
        at = garden(GARDEN_PLAN.replace("reaches every bed from one tap", TWELVE_WORDS))
        over = garden(GARDEN_PLAN.replace("reaches every bed from one tap", THIRTEEN_WORDS))
        try:
            self.assertEqual(plan_fails(at, "tile-length"), [])
            fails = plan_fails(over, "tile-length")
            self.assertEqual(len(fails), 1, [x.line() for x in fails])
            self.assertIn("S2.2.e1.t1", fails[0].where)
        finally:
            at.close()
            over.close()

    def test_tile_words_per_line_comes_from_gates_md(self):
        eight = "reaches every bed from the one tap outside"           # 8 words: 2 lines × 4
        nine = "reaches every bed from the one tap outside today"      # 9 words
        at = garden(GARDEN_PLAN.replace("reaches every bed from one tap", eight), gates_extra="tile_words_per_line: 4\n")
        over = garden(GARDEN_PLAN.replace("reaches every bed from one tap", nine), gates_extra="tile_words_per_line: 4\n")
        try:
            self.assertEqual(plan_fails(at, "tile-length"), [])
            self.assertEqual(len(plan_fails(over, "tile-length")), 1)
        finally:
            at.close()
            over.close()

    def test_tile_gates_run_on_the_elements_level(self):
        f = garden(GARDEN_PLAN.replace("reaches every bed from one tap", THIRTEEN_WORDS))
        try:
            self.assertEqual(plan_fails(f, "tile-length", upto=2), [])
            self.assertEqual(len(plan_fails(f, "tile-length", upto=3)), 1)
        finally:
            f.close()

    def test_the_gate_reports_and_never_edits_the_plan(self):
        f = garden(GARDEN_PLAN.replace("reaches every bed from one tap", THIRTEEN_WORDS))
        try:
            before = (f.path / "PLAN.md").read_bytes()
            self.assertTrue(plan_fails(f, "tile-length"))
            self.assertEqual((f.path / "PLAN.md").read_bytes(), before)
        finally:
            f.close()

    def test_tiles_element_with_no_tiles_fails_graphic(self):
        plan = GARDEN_PLAN.replace("      " + HOSE + "\n", "").replace("      " + CAN + "\n", "")
        f = garden(plan)
        try:
            self.assertNotIn("S2.2.e1.t", (f.path / "PLAN.md").read_text())
            fails = plan_fails(f, "tile-graphic")
            self.assertEqual(len(fails), 1, [x.line() for x in fails])
            self.assertIn("S2.2.e1", said(fails[0]))
        finally:
            f.close()

    def test_tile_with_empty_graphic_fails(self):
        f = garden(GARDEN_PLAN.replace("graphic: a tin watering can pouring on a pot", "graphic:"))
        try:
            fails = plan_fails(f, "tile-graphic")
            self.assertEqual(len(fails), 1, [x.line() for x in fails])
            self.assertIn("S2.2.e1.t2", said(fails[0]))
            self.assertNotIn("S2.2.e1.t1", said(fails[0]))
        finally:
            f.close()


# ---------------------------------------------------------------- TEXT.md


class TextTiles(unittest.TestCase):
    """In the text, each tile has its own graphic drawn for it, and a body of at most 2 lines."""

    # -- reading a tile written with its image first

    def test_tile_parts_leave_the_image_out(self):
        self.assertEqual(docs.tile_parts(HOSE_ITEM[2:]), ("Hose", "reaches every bed from one tap."))
        self.assertEqual(docs.tile_parts(CAN_ITEM[2:]), ("Watering can", "carries water to a few pots."))

    def test_tile_image(self):
        self.assertTrue(hasattr(docs, "tile_image"), "docs has no tile_image()")
        self.assertEqual(docs.tile_image(HOSE_ITEM[2:]), "figures/S2.2.e1.t1.svg")
        self.assertEqual(docs.tile_image("**Hose:** reaches every bed from one tap."), "")

    def test_tiles_with_images_read_as_tiles_and_pass_the_tiles_format(self):
        f = garden()
        try:
            d = f.doc()
            (t,) = [b for b in d.text.blocks if b.kind == "tiles"]
            self.assertEqual(t.titles, ["Hose", "Watering can"])
            self.assertEqual(formats.tiles_format(d), [])
        finally:
            f.close()

    # -- tile-length

    def test_tile_body_over_the_budget_fails_and_at_the_budget_passes(self):
        at = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", TWELVE_WORDS))
        over = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", THIRTEEN_WORDS))
        try:
            self.assertEqual(text_fails(at, "tile-length"), [])
            self.assertEqual(len(text_fails(over, "tile-length")), 1)
        finally:
            at.close()
            over.close()

    def test_tile_words_per_line_comes_from_gates_md(self):
        eight = "reaches every bed from the one tap outside"
        nine = "reaches every bed from the one tap outside today"
        at = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", eight),
                    gates_extra="tile_words_per_line: 4\n")
        over = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", nine),
                      gates_extra="tile_words_per_line: 4\n")
        try:
            self.assertEqual(text_fails(at, "tile-length"), [])
            self.assertEqual(len(text_fails(over, "tile-length")), 1)
        finally:
            at.close()
            over.close()

    def test_alt_text_is_not_counted_in_the_body(self):
        long_alt = "A long coiled green garden hose lying on the lawn beside a red tap with a brass spray nozzle"
        at = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", TWELVE_WORDS).replace(HOSE_ALT, long_alt))
        over = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", THIRTEEN_WORDS).replace(HOSE_ALT, long_alt))
        try:
            self.assertEqual(text_fails(at, "tile-length"), [])
            self.assertEqual(len(text_fails(over, "tile-length")), 1)
        finally:
            at.close()
            over.close()

    # -- tile-graphic

    def test_two_drawn_graphics_pass(self):
        f = garden()
        try:
            self.assertEqual(formats.tiles_format(f.doc()), [])
            self.assertEqual([x.line() for x in text_fails(f, "tile-graphic")], [])
            self.assertEqual([x.line() for x in text_fails(f, "tile-length")], [])
        finally:
            f.close()

    def test_tile_without_an_image_fails(self):
        f = garden(text=GARDEN_TEXT.replace(f"![{CAN_ALT}](figures/S2.2.e1.t2.svg) ", ""))
        try:
            self.assertEqual(len(text_fails(f, "tile-graphic")), 1)
        finally:
            f.close()

    def test_image_file_that_does_not_exist_fails(self):
        f = garden(figures={"S2.2.e1.t1.svg": HOSE_SVG, "S1.e2.svg": BEDS_SVG})
        try:
            fails = text_fails(f, "tile-graphic")
            self.assertTrue(fails)
            self.assertTrue(any("S2.2.e1.t2" in said(x) for x in fails), [x.line() for x in fails])
        finally:
            f.close()

    def test_image_not_named_for_a_tile_fails(self):
        f = garden(text=GARDEN_TEXT.replace("figures/S2.2.e1.t2.svg", "figures/house.svg"),
                   figures={"S2.2.e1.t1.svg": HOSE_SVG, "house.svg": CAN_SVG, "S1.e2.svg": BEDS_SVG})
        try:
            fails = text_fails(f, "tile-graphic")
            self.assertTrue(fails)
            self.assertTrue(any("house.svg" in said(x) for x in fails), [x.line() for x in fails])
        finally:
            f.close()

    def test_image_named_for_another_tile_of_the_element_fails(self):
        # the second tile shows the first tile's file: both point to S2.2.e1.t1.svg
        f = garden(text=GARDEN_TEXT.replace("figures/S2.2.e1.t2.svg", "figures/S2.2.e1.t1.svg"))
        try:
            self.assertTrue(text_fails(f, "tile-graphic"))
        finally:
            f.close()

    def test_image_named_for_a_tile_of_another_element_fails(self):
        # the diagram of S1.e2 is not drawn for a tile
        f = garden(text=GARDEN_TEXT.replace("figures/S2.2.e1.t2.svg", "figures/S1.e2.svg"))
        try:
            self.assertTrue(text_fails(f, "tile-graphic"))
        finally:
            f.close()

    def test_two_files_with_the_same_bytes_fail(self):
        # a copy of one picture under the second tile's name is not drawn for that tile
        f = garden(figures={"S2.2.e1.t1.svg": HOSE_SVG, "S2.2.e1.t2.svg": HOSE_SVG, "S1.e2.svg": BEDS_SVG})
        try:
            self.assertTrue(text_fails(f, "tile-graphic"))
        finally:
            f.close()

    def test_raster_without_a_prompt_is_a_screenshot_and_fails(self):
        text = GARDEN_TEXT.replace("figures/S2.2.e1.t1.svg", "figures/S2.2.e1.t1.png")
        f = garden(text=text, figures={"S2.2.e1.t1.png": png_bytes(seed=1), "S2.2.e1.t2.svg": CAN_SVG,
                                       "S1.e2.svg": BEDS_SVG})
        try:
            fails = text_fails(f, "tile-graphic")
            self.assertTrue(fails)
            self.assertTrue(any("S2.2.e1.t1" in said(x) for x in fails), [x.line() for x in fails])
            # the same raster with its prompt file beside it is a generated image, drawn for the tile
            (f.path / "figures" / "S2.2.e1.t1.prompt.md").write_text(
                "## Prompt\nA coiled green hose with a spray nozzle, flat drawing.\n\n## Style\nFlat, two colours.\n")
            self.assertEqual([x.line() for x in text_fails(f, "tile-graphic")], [])
        finally:
            f.close()

    def test_jpg_without_a_prompt_fails(self):
        text = GARDEN_TEXT.replace("figures/S2.2.e1.t2.svg", "figures/S2.2.e1.t2.jpg")
        f = garden(text=text, figures={"S2.2.e1.t1.svg": HOSE_SVG, "S2.2.e1.t2.jpg": png_bytes(seed=2),
                                       "S1.e2.svg": BEDS_SVG})
        try:
            self.assertTrue(text_fails(f, "tile-graphic"))
        finally:
            f.close()


# ---------------------------------------------------------------- the judge on the graphic file


class TileGraphicJudge(unittest.TestCase):
    """A judge looks at a tile's graphic and decides it was drawn for that tile."""

    def test_a_tiles_graphic_gets_the_judge_and_a_diagram_does_not(self):
        f = garden()
        try:
            d = f.doc()
            fails, reqs = figure_gates.run_figure(d, "figures/S2.2.e1.t1.svg", [])
            self.assertEqual([x.line() for x in fails], [])
            mine = [r for r in reqs if r.gate == "tile-graphic"]
            self.assertEqual(len(mine), 1, [r.gate for r in reqs])
            inp = mine[0].input
            # this tile: title, body and what the plan says its graphic shows
            self.assertIn("Hose", inp)
            self.assertIn("reaches every bed from one tap", inp)
            self.assertIn("a coiled green hose with a spray nozzle", inp)
            # the other tiles of the element, so the judge can tell the picture is for this one
            self.assertIn("Watering can", inp)
            self.assertIn("a tin watering can pouring on a pot", inp)
            # a diagram of another element is not a tile graphic
            _, reqs = figure_gates.run_figure(d, "figures/S1.e2.svg", [])
            self.assertEqual([r for r in reqs if r.gate == "tile-graphic"], [])
        finally:
            f.close()

    def test_the_judge_has_its_agent_file(self):
        self.assertTrue((ROOT / "gates" / "judges" / "gate-tile-graphic.md").exists())




# ---------------------------------------------------------------- after the first review


class TilesAfterReview(unittest.TestCase):
    """Cases the first review found: the graphic's alt text leaked into other gates, a text tile was never matched
    with its own plan tile, a graphic outside the document passed, a zero words-per-line crashed."""

    def test_alt_text_counts_for_no_gate_of_the_text(self):
        # a 12-word body (at the budget) under an 8-word alt: no sentence-length failure, no extra length lines
        f = garden(text=GARDEN_TEXT.replace("reaches every bed from one tap", TWELVE_WORDS))
        try:
            doc = f.doc()
            (t,) = [b for b in doc.text.blocks if b.kind == "tiles"]
            self.assertNotIn(HOSE_ALT, t.text)
            self.assertEqual(t.graphics[0], (HOSE_ALT, "figures/S2.2.e1.t1.svg"))
            self.assertTrue(all(HOSE_ALT not in u.text for u in common.body_units(doc.text.blocks)))
            fails, _ = run_scripts.run_text(doc, [])
            self.assertEqual([x.line() for x in fails if x.gate == "sentence-max-words"], [])
        finally:
            f.close()

    def test_swapped_graphics_fail(self):
        text = (GARDEN_TEXT.replace("figures/S2.2.e1.t1.svg", "figures/SWAP")
                .replace("figures/S2.2.e1.t2.svg", "figures/S2.2.e1.t1.svg").replace("figures/SWAP",
                                                                                    "figures/S2.2.e1.t2.svg"))
        f = garden(text=text)
        try:
            fails = text_fails(f, "tile-graphic")
            self.assertEqual(len(fails), 2, [x.line() for x in fails])
            self.assertIn("Hose", fails[0].why)
        finally:
            f.close()

    def test_a_plan_tile_missing_from_the_text_fails(self):
        f = garden(text=GARDEN_TEXT.replace(CAN_ITEM + "\n", ""))
        try:
            fails = text_fails(f, "tile-graphic")
            self.assertEqual(len(fails), 1, [x.line() for x in fails])
            self.assertIn("S2.2.e1.t2", said(fails[0]))
        finally:
            f.close()

    def test_a_graphic_outside_the_documents_figures_fails(self):
        f = garden()
        try:
            other = f.path.parent / "other" / "figures"
            other.mkdir(parents=True)
            (other / "S2.2.e1.t2.svg").write_text(CAN_SVG, encoding="utf-8")
            (f.path / "TEXT.md").write_text(GARDEN_TEXT.lstrip("\n").replace(
                "figures/S2.2.e1.t2.svg", "../other/figures/S2.2.e1.t2.svg"), encoding="utf-8")
            self.assertEqual(len(text_fails(f, "tile-graphic")), 1)
        finally:
            f.close()

    def test_zero_words_per_line_is_a_config_failure(self):
        f = garden(gates_extra="\ntile_words_per_line: 0\n")
        try:
            self.assertTrue([x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "config"])
            self.assertTrue([x for x in run_scripts.run_text(f.doc(), [])[0] if x.gate == "config"])
        finally:
            f.close()

    def test_an_out_of_scope_name_in_a_tile_fails_the_plan(self):
        f = garden(plan=GARDEN_PLAN.replace("carries water to a few pots", "carries water to a few Bluebird pots"))
        try:
            fails = [x for x in run_scripts.run_plan(f.doc(), 3) if x.gate == "out-of-scope"]
            self.assertEqual(len(fails), 1, [x.line() for x in run_scripts.run_plan(f.doc(), 3)])
            self.assertIn("S2.2.e1.t2", fails[0].where)
        finally:
            f.close()

    def test_the_marks_judge_sees_a_tile_graphics_alt_text(self):
        f = garden()
        try:
            self.assertIn(HOSE_ALT, figure_files.caption(f.doc(), "figures/S2.2.e1.t1.svg"))
        finally:
            f.close()

    def test_the_tile_judge_gets_the_other_tiles_drawn_graphics(self):
        f = garden()
        try:
            _, reqs = figure_gates.run_figure(f.doc(), "figures/S2.2.e1.t1.svg", [])
            (req,) = [r for r in reqs if r.gate == "tile-graphic"]
            self.assertIn("drawn already", req.input)
            self.assertIn("S2.2.e1.t2", req.input.split("## The other tiles")[1])
        finally:
            f.close()

    def test_a_graphic_that_is_not_an_image_fails(self):
        text = GARDEN_TEXT.replace("figures/S2.2.e1.t2.svg", "figures/S2.2.e1.t2.txt")
        f = garden(text=text, figures={"S2.2.e1.t1.svg": HOSE_SVG, "S2.2.e1.t2.txt": "a can",
                                       "S1.e2.svg": BEDS_SVG})
        try:
            self.assertEqual(len(text_fails(f, "tile-graphic")), 1)
        finally:
            f.close()

    def test_an_unreadable_words_per_line_is_a_config_failure(self):
        f = garden(gates_extra="\ntile_words_per_line: many\n")
        try:
            self.assertTrue([x for x in run_scripts.run_text(f.doc(), [])[0] if x.gate == "config"])
        finally:
            f.close()

    def test_tiles_split_into_two_lists_count_on(self):
        text = GARDEN_TEXT.replace(CAN_ITEM, "\nThe can suits pots.\n\n" + CAN_ITEM)
        f = garden(text=text)
        try:
            self.assertEqual([x.line() for x in text_fails(f, "tile-graphic")], [])
        finally:
            f.close()

    def test_an_item_under_a_tile_is_a_format_problem(self):
        plan = GARDEN_PLAN.replace(HOSE + "\n", HOSE + "\n        - X1 · **Nozzle** · sprays · graphic: a nozzle · 1 line\n")
        _, problems = docs.read_plan(plan)
        self.assertTrue(any("under the tile S2.2.e1.t1" in p for p in problems), problems)

    def test_the_readme_pattern_finds_a_tile_and_its_graphic(self):
        import re
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        pat = re.search(r"marker with `(\^.+?\$)`", readme).group(1)
        m = re.match(pat, HOSE_ITEM)
        self.assertEqual(m.groups(), (HOSE_ALT, "figures/S2.2.e1.t1.svg", "Hose", "reaches every bed from one tap."))


if __name__ == "__main__":
    unittest.main()
