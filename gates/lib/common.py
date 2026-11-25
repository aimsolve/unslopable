"""What many gate scripts share: the failure record, the units of the text body, terms, tables, the switches of
gates that are off by default, and the plan's element kinds."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from docs import Block, Doc, ITEM_KINDS, PLAN_FILE, PROSE_KINDS, TEXT_FILE, plain, split_sentences


LIB = Path(__file__).resolve().parent


@dataclass
class Failure:
    gate: str
    where: str
    quote: str
    why: str

    def line(self) -> str:
        q = f" «{self.quote}»" if self.quote else ""
        return f"[{self.gate}] {self.where}{q} — {self.why}"


def _num(doc: Doc, key: str, gate: str, out: list[Failure], default: float | None = None) -> float | None:
    v = doc.config.get(key)
    if v is not None:
        m = re.search(r"\d+(?:\.\d+)?", v)
        if m:
            return float(m.group(0))
    if default is not None:
        return default
    out.append(Failure("config", "GATES.md", "", f"has no number `{key}:`, so gate {gate} cannot run. Whoever writes "
                                                 "the document's gates sets it (in this run: you, from BRIEF.md); "
                                                 "then write the file again"))
    return None


def _cut(s: str, n: int = 160) -> str:
    s = plain(s)
    return s if len(s) <= n else s[:n] + "…"


# ---------------------------------------------------------------- iteration over the text body

@dataclass
class Unit:
    """One sentence-sized piece of the body in document order: a sentence of a paragraph or a callout, a list item
    (a yes/no block's items are list items, without their ✓ or ✗), a tile or a table cell."""
    block: int
    pos: int          # sentence index in a paragraph, item index in a list, cell index in a table
    kind: str         # sentence | item | tile | cell
    text: str
    element: str


def body_units(blocks: list[Block]) -> list[Unit]:
    out = []
    for bi, b in enumerate(blocks):
        if b.kind in PROSE_KINDS or b.kind == "faq":
            out += [Unit(bi, k, "sentence", s, b.element) for k, s in enumerate(b.sentences)]
        elif b.kind in ITEM_KINDS:
            out += [Unit(bi, k, "item", it, b.element) for k, it in enumerate(b.items)]
        elif b.kind == "tiles":
            out += [Unit(bi, k, "tile", it, b.element) for k, it in enumerate(b.items)]
        elif b.kind == "table":
            k = 0
            for row in b.rows:
                for c in row:
                    if plain(c):
                        out.append(Unit(bi, k, "cell", c, b.element))
                    k += 1
    return out


def opens_paragraph(u: Unit, blocks: list[Block]) -> bool:
    """The unit is the first sentence of a block of prose: nothing in the block comes before it. A definition does
    not count: it opens with its term by design, and the judge `term-explained` reads what leads to it."""
    return u.kind == "sentence" and u.pos == 0 and blocks[u.block].kind != "definition"


def label(u: Unit, blocks: list[Block]) -> str:
    """Where a unit is, without line numbers: stable when lines above it move, for judge inputs."""
    return f"element {blocks[u.block].element or 'with no marker'}, {u.kind} {u.pos + 1}"


def where(u: Unit, blocks: list[Block]) -> str:
    b = blocks[u.block]
    el = b.element or "no marker"
    return f"TEXT.md line {b.line_no} ({el}, {u.kind} {u.pos + 1})"


# ---------------------------------------------------------------- terms

def term_pattern(term: str) -> re.Pattern:
    flags = 0 if (term.isupper() and len(term) > 1) else re.I
    return re.compile(r"(?<![\w-])" + re.escape(term) + r"(?:s|es)?(?![\w-])", flags)


def first_uses(doc: Doc) -> dict[str, Unit]:
    """{explain term: the unit of its first use in the body}, headings and figures not counted."""
    units = body_units(doc.text.blocks)
    out = {}
    for term, mark in doc.terms.items():
        if mark != "explain":
            continue
        pat = term_pattern(term)
        for u in units:
            if pat.search(plain(u.text)):
                out[term] = u
                break
    return out


_EXPLAINS = re.compile(r";\s*explains\s*:\s*(.+?)\s*$", re.I)


def plan_explains(row) -> list[str]:
    """The `explain` terms an element names at the end of its third field: `…; explains: A, B`."""
    m = _EXPLAINS.search(row.get("says"))
    return [t.strip().strip("`") for t in m.group(1).split(",") if t.strip()] if m else []


_ENTITY = re.compile(r"&#?\w+;")
_CODE = re.compile(r"`[^`]*`")


# enumerations that are led in: the sentence right before says what follows and why
ENUMERATION_KINDS = ("list", "tiles", "table", "yes-no", "steps")


def block_name(b: Block) -> str:
    """What a block is called in a message to the writer."""
    return {"yes-no": "yes/no block", "pull-quote": "pull quote", "faq": "FAQ"}.get(
        b.kind, b.kind if b.kind in ("table", "tiles", "callout", "steps", "stat", "definition") else "list")


UV_SPACY = ["uv", "run", "--quiet", "--no-project", "--python", "3.11", "--with", "spacy==3.8.2", "--with", "click",
            "--with", "en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/"
                      "en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"]


def flagged(doc: Doc, pattern: re.Pattern) -> list[tuple[Unit, str]]:
    out = []
    for u in body_units(doc.text.blocks):
        for s in (split_sentences(u.text) if u.kind != "sentence" else [u.text]):
            if pattern.search(s):
                out.append((u, s))
    return out


def plan_headings(doc: Doc, level: int) -> list[tuple[str, str]]:
    return [(f"{PLAN_FILE} {r.id}", r.get("heading")) for r in doc.plans.get(level, [])]


def _tol(doc: Doc, out: list[Failure]) -> float | None:
    return _num(doc, "length_tolerance_pct", "length", out)


def _miss(got: float, want: float, pct: float) -> bool:
    return abs(got - want) > max(1.0, want * pct / 100.0)


def leaves(doc: Doc) -> dict[str, object]:
    """Ids an element may hang on: every level-2 row, and every level-1 row with no level-2 children."""
    l2 = doc.plans.get(2, [])
    parents2 = {r.get("parent") for r in l2}
    out = {r.id: r for r in l2}
    for r in doc.plans.get(1, []):
        if r.id not in parents2:
            out[r.id] = r
    return out


def tables(doc: Doc) -> list[tuple[int, Block]]:
    """[(block index, block)] for every table of the text with an element marker."""
    return [(i, b) for i, b in enumerate(doc.text.blocks) if b.kind == "table" and b.element]


def body_rows(b: Block) -> list[list[str]]:
    """A table's rows under its header."""
    return b.rows[1:]


def group_row(row: list[str]) -> bool:
    """A mini header row inside a table (a label in its first cell, every other cell empty): not a data row."""
    return bool(row) and bool(plain(row[0])) and not any(plain(c) for c in row[1:])


OFF_BY_DEFAULT = ("no-document-talk", "no-announcing")


def gates_on(doc: Doc) -> set[str]:
    """The off-by-default gates a document switches on: GATES.md `gates_on: a; b` (`;`, `,` or spaces)."""
    v = doc.config.get("gates_on", "")
    return {t.strip().strip("`\"«»") for t in re.split(r"[;,\s]+", v) if t.strip().strip("`\"«»")}


_OFF_ENTRY = re.compile(r"^([A-Za-z0-9-]+)\s*(?:\((.*)\))?$")


def gates_off(doc: Doc) -> dict[str, str]:
    """The gates a document switches off because they argue with its brief: GATES.md
    `gates_off: plan-wall (the brief rules out lists, tables and pictures); cliche (…)`, each gate by its name in
    gates/library.md with the reason in brackets -> {gate: reason}; a reason left out is ''."""
    out = {}
    for part in re.split(r";(?![^()]*\))", doc.config.get("gates_off", "")):  # a `;` inside the brackets stays
        part = part.strip().strip("`\"«»")
        if not part:
            continue
        m = _OFF_ENTRY.match(part)
        name, reason = (m.group(1), (m.group(2) or "").strip()) if m else (part, "")
        out[name] = reason
    return out


def library_gates() -> list[str]:
    """Every gate name of gates/library.md (the first cell of each table row)."""
    text = (LIB.parent / "library.md").read_text(encoding="utf-8")
    return re.findall(r"^\|\s*([a-z0-9-]+)\s*\|", text, re.M)


# the gate names script failures carry where they differ from the gate's name in gates/library.md
_LIBRARY_NAME = {"plain-text-wall": "plan-wall", "leftover-marker": "leftover-markers",
                 "plan-element-missing": "plan-elements-written", "term-first-use": "term-explained"}


def library_name(gate: str, stage: str = "") -> str:
    """The gate's name in gates/library.md; a `length` failure is plan-length on the plan, text-length on the text."""
    if gate == "length":
        return "plan-length" if stage == "plan" else "text-length"
    return _LIBRARY_NAME.get(gate, gate)


def drop_off(doc: Doc, items: list, stage: str = "") -> list:
    """Script failures or judge requests without the gates GATES.md `gates_off` switches off: such a gate reports
    nothing and starts no judge. Format and config failures always stay."""
    off = gates_off(doc)
    if not off:
        return items
    return [x for x in items if x.gate in ("format", "config") or library_name(x.gate, stage) not in off]


def gate_is_on(doc: Doc, gate: str) -> bool:
    if gate in gates_off(doc):
        return False
    return gate not in OFF_BY_DEFAULT or gate in gates_on(doc)


def flagged_paragraphs(doc: Doc, gate: str, pattern: re.Pattern) -> list[tuple[int, list[str]]]:
    """[(block index, flagged sentences)] of paragraphs, callouts, list items, tiles and yes/no items, for one judge
    per block; [] when off."""
    if not gate_is_on(doc, gate):
        return []
    out = []
    for i, b in enumerate(doc.text.blocks):
        if not b.element or b.kind not in PROSE_KINDS + ITEM_KINDS + ("tiles", "faq"):
            continue
        sents = b.sentences if b.kind in PROSE_KINDS + ("faq",) else [s for it in b.items for s in split_sentences(it)]
        hits = [s for s in sents if pattern.search(s)]
        if hits:
            out.append((i, hits))
    return out


def element_kind(doc: Doc, element: str) -> str:
    r = doc.plan_row(element)
    return r.get("kind").lower() if r is not None else ""


def summary_elements(doc: Doc) -> list[str]:
    """Plan elements of kind `summary` that have text, once every other element of the plan has text (a summary is
    judged against the whole of what it sums up)."""
    have = {b.element for b in doc.text.blocks if b.element}
    rows = doc.plans.get(3, [])
    summ = [r.id for r in rows if "summary" in r.get("kind").lower()]
    if not summ or any(r.id not in have for r in rows if r.id not in summ):
        return []
    return [s for s in summ if s in have]



def _raw_text_lines(doc: Doc, blank_code: bool = True) -> list[tuple[int, str]]:
    """(line number, line) of TEXT.md outside fenced code, element marker lines left out. With `blank_code`, inline
    code spans are blanked (their text is no marker and no link)."""
    from docs import _MARKER
    try:
        raw = (doc.folder / TEXT_FILE).read_text(encoding="utf-8")
    except OSError:
        return []
    out, fenced = [], False
    for n, line in enumerate(raw.splitlines(), 1):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            continue
        if fenced or _MARKER.match(line):
            continue
        out.append((n, _CODE.sub(lambda m: " " * len(m.group(0)), line) if blank_code else line))
    return out
