"""Format checks of TEXT.md (not gates of the library): every block has a plan element marker, tiles, callouts and
yes/no blocks are written the way the plan's kind says, and GATES.md `gates_on` names real gates."""
from __future__ import annotations

from docs import Block, Doc, FENCED_KINDS, NO, PLAN_FILE, STEPS_FORMS, YES, fenced_kind, tile_parts
from common import Failure, OFF_BY_DEFAULT, block_name, gates_off, gates_on, library_gates


def tiles_format(doc: Doc) -> list[Failure]:
    """Format: tiles are written as a list, one `- **Title:** body` item per tile, so the gates can read each tile's
    title and body (README «Text»). A `tiles` element of the plan whose text has no such list fails."""
    out = []
    kinds = {r.id: r.get("kind").strip().lower() for r in doc.plans.get(3, [])}
    blocks = doc.text.blocks
    for el in dict.fromkeys(b.element for b in blocks if b.element and kinds.get(b.element) == "tiles"):
        mine = [b for b in blocks if b.element == el]
        tiles = [b for b in mine if b.kind == "tiles"]
        if not tiles:
            out.append(Failure("format", f"TEXT.md line {mine[0].line_no} ({el})", "",
                               "the plan makes this element tiles, and its text has no list of tiles: write one "
                               "list item per tile, `- ![what it shows](figures/<tile id>.svg) **Tile title:** what "
                               "the tile says`"))
        for b in tiles:
            for k, it in enumerate(b.items, 1):
                title, body = tile_parts(it)
                if not title or not body:
                    out.append(Failure("format", f"TEXT.md line {b.line_no} ({el}, tile {k})", it.strip()[:160],
                                       f"a tile with no {'title' if not title else 'body after its title'}: write "
                                       "`**Tile title:** what the tile says`, only the title in bold"))
    return out


# what goes inside each fenced block, for the message when an element of that kind has none
_INSIDE = {
    "callout": "the conclusion inside",
    "yes-no": f"one list inside, each item starting `- {YES} ` or `- {NO} `",
    "pull-quote": "the phrase inside, and a last line `— Name` when the words are a person's",
    "steps": "one numbered list inside, `1. **Short title:** what the reader does` per step",
    "stat": "one sentence inside that opens with the number in bold",
    "faq": "question and answer pairs inside, each question a line of its own in bold",
    "definition": "the term in bold inside, then a dash and what it means",
}


def fenced_format(doc: Doc) -> list[Failure]:
    """Format: an element of a kind that has a fenced block (callout, yes/no, pull quote, steps, stat, FAQ,
    definition) is written as that `::: <kind>` block, steps in the form the plan gives (`::: steps vertical` or
    `::: steps horizontal`), and such a block stands only under an element of its kind, so a PDF builder can find and
    draw them (README «Text»). A yes/no block's items start with ✓ (what it does) or ✗ (what it does not do), at least
    one of each."""
    out = []
    kinds = {r.id: fenced_kind(r.get("kind")) for r in doc.plans.get(3, [])}
    names = {r.id: r.get("kind").strip() for r in doc.plans.get(3, [])}
    blocks = doc.text.blocks
    for ln, what in doc.text.problems:
        out.append(Failure("format", f"TEXT.md line {ln}", "", what))
    for el in dict.fromkeys(b.element for b in blocks if b.element):
        want, form = kinds.get(el, ("", ""))
        mine = [b for b in blocks if b.element == el]
        for b in mine:
            if b.kind in FENCED_KINDS and b.kind != want:
                out.append(Failure("format", f"TEXT.md line {b.line_no} ({el})", "",
                                   f"a `::: {b.kind}` block under an element the plan makes «{names.get(el) or '?'}»: "
                                   f"write the element in the kind the plan names"))
        if want == "steps" and form in STEPS_FORMS:
            for b in mine:
                if b.kind == "steps" and b.form in STEPS_FORMS and b.form != form:
                    out.append(Failure("format", f"TEXT.md line {b.line_no} ({el})", "",
                                       f"`::: steps {b.form}` under an element the plan makes `steps {form}`: write "
                                       f"`::: steps {form}`"))
        if want and not any(b.kind == want for b in mine):
            line = f"::: {want} {form}".rstrip() if want == "steps" else f"::: {want}"
            out.append(Failure("format", f"TEXT.md line {mine[0].line_no} ({el})", "",
                               f"the plan makes this element a {block_name(Block(want, el, '', 0))}, and its text "
                               f"has none: write a line `{line}`, {_INSIDE[want]}, then a line `:::`"))
        for b in mine:
            if b.kind != "yes-no":
                continue
            for k, (side, it) in enumerate(zip(b.sides, b.items), 1):
                if not side:
                    out.append(Failure("format", f"TEXT.md line {b.line_no} ({el}, item {k})", it[:160],
                                       f"an item of a yes/no block with no {YES} or {NO} first: start it `{YES} ` "
                                       f"when it is what the thing does, `{NO} ` when it is what it does not do"))
            for side, icon in (("yes", YES), ("no", NO)):
                if b.items and side not in b.sides:
                    out.append(Failure("format", f"TEXT.md line {b.line_no} ({el})", "",
                                       f"the yes/no block has no item with {icon}: it sets what a thing does against "
                                       "what it does not do, so both columns have items"))
    return out


def plan_steps_form(doc: Doc) -> list[Failure]:
    """Format of plan level 3: a `steps` element names its form, `steps vertical` or `steps horizontal`, so the writer
    knows which block to write; checked on the plan, before the level is approved."""
    out = []
    for r in doc.plans.get(3, []):
        want, form = fenced_kind(r.get("kind"))
        if want == "steps" and form not in STEPS_FORMS:
            out.append(Failure("format", f"{PLAN_FILE} {r.id}", r.get("kind").strip(),
                               "steps need their form in the kind: `steps vertical` (down the page, for more steps or "
                               "longer bodies) or `steps horizontal` (across the page, three to five short steps)"))
    return out


# ---------------------------------------------------------------- format checks

def text_format(doc: Doc) -> list[Failure]:
    out = []
    for ln in doc.text.unmarked:
        out.append(Failure("format", f"TEXT.md line {ln}", "", "a block with no plan element marker "
                                                              "(`<!-- <element id> -->` on the line before it)"))
    ids3 = {r.id for r in doc.plans.get(3, [])}
    for el in sorted({b.element for b in doc.text.blocks if b.element}):
        if el not in ids3:
            out.append(Failure("format", f"TEXT.md element {el}", el, f"this id is not an element of {PLAN_FILE}"))
    return out


def gate_switches(doc: Doc) -> list[Failure]:
    """A name in `gates_on` that is not an off-by-default gate: a typo would leave the gate off without a word. A name
    in `gates_off` that is not a gate of the library, or has no reason: the switch would do nothing, or nobody could
    tell why the gate is off."""
    out = [Failure("config", "GATES.md", n, f"`gates_on` names «{n}», which is not a gate that is off by default; "
                                           f"those are: {', '.join(OFF_BY_DEFAULT)}")
           for n in sorted(gates_on(doc)) if n not in OFF_BY_DEFAULT]
    known = set(library_gates())
    for n, reason in gates_off(doc).items():
        if n not in known:
            out.append(Failure("config", "GATES.md", n, f"`gates_off` names «{n}», which is not a gate of "
                                                       "gates/library.md: write the gate's name as the library has it"))
        elif not reason:
            out.append(Failure("config", "GATES.md", n, f"`gates_off` switches «{n}» off with no reason: write why "
                                                       f"in brackets after it, `{n} (what in the brief it argues "
                                                       "with)`"))
    return out
