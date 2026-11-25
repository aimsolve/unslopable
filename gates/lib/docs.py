"""Reading a document folder: BRIEF.md, GATES.md, TERMS.md, PLAN.md (the plan, one nested list) and TEXT.md.

File formats are the provisional ones of README «Provisional (19.11 night, test run)». Everything here is pure
parsing; the gates live in gates/scripts/, their runner in run_scripts.py and the judges' inputs in judge_gates.py.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

PLAN_FILE = "PLAN.md"
TEXT_FILE = "TEXT.md"
LEVELS = {1: "sections", 2: "subsections", 3: "elements"}


# ---------------------------------------------------------------- text helpers

_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_EMPH = re.compile(r"(\*\*|__|\*|_|`)")
_COMMENT = re.compile(r"<!--.*?-->", re.S)
_TAG = re.compile(r"<[^>]+>")
# A sentence ends at . ! ? (maybe followed by a closing quote or bracket), then a space and a capital, a digit or an
# opening quote or bracket.
_SENT_END = re.compile(r"(?<=[.!?])[\"'»”)\]]*\s+(?=[\"'«“(\[]?[A-Z0-9])")
_ABBREV = re.compile(r"(?:^|\s)(?:e\.g|i\.e|etc|vs|cf|approx|incl|no|fig|Mr|Ms|Dr|St|Inc|Ltd|Co|U\.S)\.$", re.I)
_WORD = re.compile(r"[A-Za-z0-9À-ÿĀ-žА-яЁё]+(?:[-'’][A-Za-z0-9À-ÿĀ-žА-яЁё]+)*")


def plain(text: str) -> str:
    """Text without markdown emphasis, links (their words stay), HTML tags and comments; spaces collapsed."""
    t = _COMMENT.sub(" ", text or "")
    t = _IMAGE.sub(r"\1", t)
    t = _LINK.sub(r"\1", t)
    t = _TAG.sub(" ", t)
    t = _EMPH.sub("", t)
    return re.sub(r"\s+", " ", t).strip()


def words(text: str) -> list[str]:
    return _WORD.findall(plain(text))


def split_sentences(text: str) -> list[str]:
    t = plain(text)
    out, start = [], 0
    for m in _SENT_END.finditer(t):
        if _ABBREV.search(t[start:m.start() + 1].rstrip("\"'»”)]")):
            continue
        out.append(t[start:m.start() + 1].strip())
        start = m.end()
    out.append(t[start:].strip())
    return [s for s in out if s]


def lines_of(text: str, words_per_line: int) -> int:
    return max(1, math.ceil(len(words(text)) / max(1, words_per_line)))


# ---------------------------------------------------------------- markdown sections (BRIEF.md)

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def md_sections(text: str) -> dict[str, str]:
    """{heading text, lowercased, numbering stripped: body} for every heading of a markdown file."""
    out: dict[str, str] = {}
    cur, buf = None, []
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            if cur is not None:
                out[cur] = "\n".join(buf).strip()
            cur = re.sub(r"^\d+[.)]\s*", "", plain(m.group(2))).lower()
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip()
    return out


def brief_part(brief: str, key: str) -> str:
    """The body of the BRIEF.md section whose heading starts with `key` (case-insensitive); '' if none."""
    key = key.lower()
    for head, body in md_sections(brief).items():
        if head.startswith(key):
            return body
    return ""


def brief_language(brief: str) -> str:
    return brief_part(brief, "language")


# ---------------------------------------------------------------- GATES.md, TERMS.md

_KV = re.compile(r"^\s*(?:[-*]\s+)?`?([a-z_]+)`?\s*:\s*(.+?)\s*$")


def read_config(text: str) -> dict[str, str]:
    """GATES.md: one `key: value` per line (a leading '- ' is allowed); anything else is ignored."""
    out = {}
    for line in text.splitlines():
        m = _KV.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


_TERM = re.compile(r"^\s*(?:[-*]\s+)?\**(.+?)\**\s+[—–-]{1,2}\s+\**(known|link|explain)\**\b", re.I)
_TERMS_HEADING = re.compile(r"^\s*#{2,6}\s+\**(known|explain)", re.I)
_TERM_ITEM = re.compile(r"^\s*[-*]\s+(.+?)(?:\s+[—–-]{1,2}\s+.*)?$")
_LINK_MARKER = re.compile(r"\s*\(link\)\s*$", re.I)


def read_terms(text: str) -> dict[str, str]:
    """TERMS.md -> {term: known|link|explain}; definitions are not read.

    New format: a `## Known` heading and a `## Explain` heading, each over a bulleted list, one
    `- term — definition` per item; a known term marked `(link)` after its name is `link`. Old format, kept for
    documents written before: one `term — known|link|explain — definition` per line."""
    if not any(_TERMS_HEADING.match(line) for line in text.splitlines()):
        out = {}
        for line in text.splitlines():
            m = _TERM.match(line)
            if m:
                out[m.group(1).strip().strip("`")] = m.group(2).lower()
        return out
    out, section = {}, None
    for line in text.splitlines():
        h = _TERMS_HEADING.match(line)
        if h:
            section = h.group(1).lower()
            continue
        if line.lstrip().startswith("#"):
            section = None
            continue
        m = _TERM_ITEM.match(line) if section else None
        if not m:
            continue
        term = m.group(1).strip()
        link = bool(_LINK_MARKER.search(term))
        term = _LINK_MARKER.sub("", term).strip().strip("*").strip("`").strip()
        if term:
            out[term] = "link" if link and section == "known" else section
    return out


# ---------------------------------------------------------------- the plan

@dataclass
class PlanRow:
    level: int
    id: str
    cells: dict[str, str]
    line_no: int
    tiles: list["PlanRow"] = field(default_factory=list)  # a `tiles` element's tiles (level 4), in order

    def get(self, key: str) -> str:
        return self.cells.get(key, "")

    @property
    def lines(self) -> float | None:
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s+lines?", self.get("lines").strip())
        return float(m.group(1)) if m else None


_ITEM = re.compile(r"^(\s*)[-*+]\s+(.*?)\s*$")
_SEP = re.compile(r"\s+·\s+")
_BOLD = re.compile(r"^\*\*(.+?)\*\*$")
_FACTS = re.compile(r"^facts\s*:\s*(.*)$", re.I)
_GRAPHIC = re.compile(r"^graphic\s*:\s*(.*)$", re.I)
# a section whose subsections are equal, unrelated cases: the seams between its subsections are not gated
_PARALLEL = re.compile(r"subsections\s*:\s*parallel", re.I)


def _indent(s: str) -> int:
    return len(s.expandtabs(4))


def read_plan(text: str) -> tuple[dict[int, list[PlanRow]], list[str]]:
    """PLAN.md -> ({level: rows in document order}, format problems). Format: README «The plan».

    Every list item is a plan item, one line each, fields split by ` · `. A bold second field makes a heading item
    (a section at the top, a subsection under a section); any other item is an element.
    """
    plans: dict[int, list[PlanRow]] = {1: [], 2: [], 3: []}
    problems: list[str] = []
    stack: list[tuple[int, PlanRow | None]] = []   # (indent, row); None for an item that could not be read
    last_item = -1
    for n, line in enumerate(text.splitlines(), 1):
        m = _ITEM.match(line)
        if not m:
            if line.strip() and line[:1].isspace() and last_item == n - 1:
                problems.append(f"line {n}: an item goes on over two lines; each item is one line")
                last_item = n
            continue
        last_item = n
        ind = _indent(m.group(1))
        while stack and stack[-1][0] >= ind:
            stack.pop()
        parent = stack[-1][1] if stack else None
        under = bool(stack)
        fields = [f.strip() for f in _SEP.split(m.group(2))]
        rid = plain(fields[0]).strip("`")
        row = tile = None
        if not rid:
            problems.append(f"line {n}: an item without an id")
        elif len(fields) < 2 or not re.fullmatch(r"\d+(?:\.\d+)?\s+lines?", fields[-1]):
            problems.append(f"{rid} (line {n}): the last field is not a size such as `4 lines`")
        else:
            size = fields[-1]
            head = _BOLD.match(fields[1])
            if under and parent is None:
                problems.append(f"{rid} (line {n}): it is under an item that could not be read")
            elif parent is not None and parent.level == 3 and parent.get("kind").strip().lower() == "tiles":
                tile, why = _tile_row(rid, fields, parent, n)
                if tile is None:
                    problems.append(f"{rid} (line {n}): {why}")
                else:
                    parent.tiles.append(tile)
            elif parent is not None and parent.level == 4:
                problems.append(f"{rid} (line {n}): an item under the tile {parent.id}; a tile has nothing under it")
            elif head:
                parallel = len(fields) == 5 and bool(_PARALLEL.fullmatch(fields[3]))
                if len(fields) != 4 and not parallel:
                    problems.append(f"{rid} (line {n}): a section or subsection has 4 fields "
                                    "(id · **heading** · what it covers · N lines; a section whose subsections are "
                                    "equal, unrelated cases adds `subsections: parallel` before the size), this one "
                                    "has " + str(len(fields)))
                elif parent is None or parent.level == 1:
                    row = PlanRow(1 if parent is None else 2, rid,
                                  {"parent": parent.id if parent else "", "heading": head.group(1).strip(),
                                   "covers": fields[2], "lines": size}, n)
                    if parallel and parent is not None:  # the row stays, so the elements under it still read
                        problems.append(f"{rid} (line {n}): `subsections: parallel` marks a section, not a "
                                        "subsection")
                    elif parallel:
                        row.cells["subsections"] = "parallel"
                else:
                    problems.append(f"{rid} (line {n}): a heading item under {parent.id}; the plan has sections and "
                                    "subsections only, and nothing goes under an element")
            elif parent is None:
                problems.append(f"{rid} (line {n}): an element at the top of the list; elements go under a section "
                                "or a subsection (a section's heading is in bold)")
            elif parent.level == 3:
                problems.append(f"{rid} (line {n}): an item under the element {parent.id}; only a `tiles` element "
                                "has items under it, one per tile")
            elif is_generated_kind(fields[1]):
                row, why = _generated_row(rid, fields, parent, size, n)
                if why:
                    problems.append(f"{rid} (line {n}): {why}")
            elif len(fields) not in (4, 5):
                problems.append(f"{rid} (line {n}): an element has 4 or 5 fields "
                                "(id · kind · what it says · facts: … · N lines), this one has " + str(len(fields)))
            elif len(fields) == 5 and not _FACTS.match(fields[3]):
                problems.append(f"{rid} (line {n}): the fourth field of an element is its material, written "
                                "`facts: …`")
            else:
                facts = _FACTS.match(fields[3]).group(1) if len(fields) == 5 else ""
                row = PlanRow(3, rid, {"parent": parent.id, "kind": fields[1], "says": fields[2],
                                       "facts": facts.strip(), "lines": size}, n)
        if row is not None:
            plans[row.level].append(row)
        stack.append((ind, row or tile))
    seen: set[str] = set()
    for lvl in (1, 2, 3):
        for r in plans[lvl]:
            for x in [r] + r.tiles:
                if x.id in seen:
                    problems.append(f"id {x.id} appears twice")
                seen.add(x.id)
    with_subs = {r.get("parent") for r in plans[2]}
    if plans[2]:  # the mark is about subsections: checked once they are written
        for r in plans[1]:
            n_subs = sum(1 for x in plans[2] if x.get("parent") == r.id)
            if r.get("subsections") and n_subs < 2:
                problems.append(f"{r.id}: it is marked `subsections: parallel` but has {n_subs} subsections; the "
                                "mark is for a section of two or more subsections that are equal, unrelated cases")
    for r in plans[3]:
        if r.get("parent") in with_subs:
            problems.append(f"{r.id}: its section {r.get('parent')} has subsections, so the element goes under one "
                            "of them (text before the first subsection gets a subsection of its own)")
    return plans, problems


TILE_FORMAT = "id · **title** · what the tile says · graphic: what its picture shows · N lines"


def _tile_row(rid: str, fields: list[str], parent: PlanRow, n: int) -> tuple[PlanRow | None, str]:
    """One tile of a `tiles` element: `id · **title** · body · graphic: … · N lines` (README «The plan»)."""
    if len(fields) != 5:
        return None, f"a tile of {parent.id} has 5 fields ({TILE_FORMAT}), this one has {len(fields)}"
    head = _BOLD.match(fields[1])
    if not head:
        return None, f"a tile's second field is its title in bold ({TILE_FORMAT})"
    g = _GRAPHIC.match(fields[3])
    if not g:
        return None, f"a tile's fourth field says what its graphic shows, written `graphic: …` ({TILE_FORMAT})"
    return PlanRow(4, rid, {"parent": parent.id, "title": head.group(1).strip(), "body": fields[2],
                            "graphic": g.group(1).strip(), "lines": fields[4]}, n), ""


GENERATED_FORMAT = ("id · generated_image · what it shows · style: … · references: path, path (optional) · "
                    "facts: … (optional) · N lines")
_NAMED = re.compile(r"^(style|references|facts)\s*:\s*(.*)$", re.I)


def is_generated_kind(kind: str) -> bool:
    """A plan kind that is a picture made by an image model: the library's `generated_image`."""
    return canon_kind(kind) in ("generated image", "generated picture", "generated illustration")


def _generated_row(rid: str, fields: list[str], parent: PlanRow, size: str, n: int) -> tuple[PlanRow | None, str]:
    """A `generated_image` element: `id · generated_image · what it shows · style: … · references: … · N lines`
    (README «The plan»); `references:` and `facts:` may be left out, `style:` may not."""
    cells = {"parent": parent.id, "kind": fields[1], "says": fields[2] if len(fields) > 2 else "", "lines": size,
             "facts": "", "style": "", "references": ""}
    for f in fields[3:-1]:
        m = _NAMED.match(f)
        if not m:
            return None, f"a generated image's fields after what it shows are named `style:`, `references:` or " \
                         f"`facts:` ({GENERATED_FORMAT}); «{f}» is not"
        name = m.group(1).lower()
        if cells[name]:
            return None, f"a generated image names `{name}:` twice ({GENERATED_FORMAT})"
        cells[name] = m.group(2).strip()
    if len(fields) < 4 or not cells["says"]:
        return None, f"a generated image has at least 5 fields ({GENERATED_FORMAT})"
    if not cells["style"]:
        return None, f"a generated image says its style in a field `style: …` ({GENERATED_FORMAT})"
    return PlanRow(3, rid, cells, n), ""


def plan_references(r: PlanRow) -> list[str]:
    """The reference pictures a generated image's plan element names, paths relative to the document folder."""
    return [s.strip().strip("`") for s in r.get("references").split(",") if s.strip()]


def _tile_item(t: PlanRow) -> str:
    return " · ".join([t.id, f"**{t.get('title')}**", t.get("body"), f"graphic: {t.get('graphic')}", t.get("lines")])


def _item(r: PlanRow, under: bool) -> str:
    if r.level < 3:
        fields = [f"**{r.get('heading')}**", r.get("covers")] + \
            ([f"subsections: {r.get('subsections')}"] if r.get("subsections") else [])
    else:
        fields = [r.get("kind"), r.get("says")] + [f"{k}: {r.get(k)}" for k in ("style", "references", "facts")
                                                   if r.get(k)]
    rid = f"{r.id} (under {r.get('parent')})" if under and r.get("parent") else r.id
    return " · ".join([rid] + fields + [r.get("lines")])


def level_text(rows: list[PlanRow]) -> str:
    """One level's items, one line each with the parent's id: what that level's approval and judges are about."""
    return "".join(f"- {_item(r, True)}\n" + "".join(f"  - {_tile_item(t)}\n" for t in r.tiles) for r in rows)


def plan_text(plans: dict[int, list[PlanRow]], upto: int) -> str:
    """The plan's levels 1..upto as the nested list, rebuilt from the items (no approval lines)."""
    kids: dict[str, list[PlanRow]] = {}
    for lvl in range(2, upto + 1):
        for r in plans.get(lvl, []):
            kids.setdefault(r.get("parent"), []).append(r)
    out: list[str] = []

    def put(r: PlanRow, depth: int) -> None:
        out.append("  " * depth + "- " + _item(r, False))
        out.extend("  " * (depth + 1) + "- " + _tile_item(t) for t in r.tiles)
        for k in kids.get(r.id, []):
            put(k, depth + 1)
    for r in plans.get(1, []):
        put(r, 0)
    return "\n".join(out) + ("\n" if out else "")


# ---------------------------------------------------------------- TEXT.md

@dataclass
class Block:
    kind: str            # paragraph | list | tiles | table | figure, or a fenced block (FENCED_KINDS)
    element: str         # plan element id from the marker before it, '' if none
    text: str            # raw markdown of the block
    line_no: int
    items: list[str] = field(default_factory=list)       # list items; for tiles, each tile's whole line
    rows: list[list[str]] = field(default_factory=list)  # table rows, header first
    titles: list[str] = field(default_factory=list)      # tiles: each tile's bold title ('' when it has none)
    sides: list[str] = field(default_factory=list)       # yes-no: 'yes' (✓) or 'no' (✗) per item, '' with no icon
    graphics: list[tuple[str, str]] = field(default_factory=list)  # tiles: each tile's graphic (alt, path), ('', '')
    form: str = ""       # steps: 'vertical' or 'horizontal', from `::: steps <form>`
    source: str = ""     # pull-quote: whose words, from its last line `— Name`; '' for a phrase of the text

    @property
    def sentences(self) -> list[str]:
        if self.kind == "faq":   # each question and each answer on its own: the pairs do not run into each other
            return [x for q, a in zip(self.titles, self.items) for x in split_sentences(q) + split_sentences(a)]
        return split_sentences(self.text) if self.kind in PROSE_KINDS else []


# blocks whose text is running prose, read sentence by sentence (README «Text»): a paragraph, a callout, a pull quote
# (its source line left out), a stat and a definition
PROSE_KINDS = ("paragraph", "callout", "pull-quote", "stat", "definition")
# blocks read item by item, like a list
ITEM_KINDS = ("list", "yes-no", "steps")
# every kind of block that carries text; a figure carries none
TEXT_KINDS = ("paragraph", "list", "tiles", "table", "callout", "yes-no", "pull-quote", "steps", "stat", "faq",
              "definition")
# a plan element whose kind has one of these words is a picture: the text holds only its image line
_FIGURE_WORD = re.compile(r"\b(?:figures?|diagrams?|screenshots?|charts?|images?|generated)\b")


def is_figure_kind(kind: str) -> bool:
    """A plan kind that is a picture in the text: figure, diagram, screenshot, chart, a generated image."""
    return bool(_FIGURE_WORD.search(canon_kind(kind)))


@dataclass
class Text:
    blocks: list[Block]
    headings: list[tuple[int, str, int]]   # (level, text, line_no)
    unmarked: list[int]                    # line numbers of blocks before any marker
    problems: list[tuple[int, str]] = field(default_factory=list)  # (line_no, what): a fenced block written wrong


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


_MARKER = re.compile(r"^\s*<!--\s*([A-Za-z0-9_.:\-]+)\s*-->\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FIGURE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")


_TILE = re.compile(r"^\*\*(.+?)\*\*\s*(.*)$")
_TILE_IMAGE = re.compile(r"^!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)\s*")
_ITEM_IMAGE = re.compile(r"^([ \t]*(?:[-*+]|\d+[.)])[ \t]+)!\[[^\]]*\]\([^)]*\)[ \t]*", re.M)


def tile_graphic(item: str) -> tuple[str, str]:
    """(alt text, path) of a tile's graphic: the image that opens its list item,
    `- ![what it shows](figures/<tile id>.svg) **Title:** body` (README «Text»); ('', '') when it opens with none."""
    m = _TILE_IMAGE.match(item.strip())
    return (m.group(1).strip(), m.group(2)) if m else ("", "")


def tile_image(item: str) -> str:
    """The path of a tile's graphic, '' when the item opens with none."""
    return tile_graphic(item)[1]

# The blocks of the element library that markdown has no form for are fenced divs (README «Text»): a line
# `::: <kind>` (`::: steps vertical`, `::: steps horizontal`), the content, a line `:::`. A PDF builder finds them by
# these lines; inside a yes/no block every list item starts with ✓ or ✗.
FENCED_KINDS = ("callout", "yes-no", "pull-quote", "steps", "stat", "faq", "definition")
STEPS_FORMS = ("vertical", "horizontal")
_FENCE_OPEN = re.compile(r"^:::\s*(\S.*?)\s*$")   # at the line's start; the kind is checked against FENCED_KINDS
_FENCE_CLOSE = re.compile(r"^:::\s*$")
YES, NO = "✓", "✗"
_SIDE = re.compile(r"^\s*(✓|✗)\ufe0f?\s*")


def canon_kind(kind: str) -> str:
    """A plan element's kind, lower case, `_` read as a space (the library's `bulleted_list` is «bulleted list»);
    «yes/no», «yes_no», «yesno» are `yes-no`, «pull_quote», «pull quote» are `pull-quote`."""
    k = re.sub(r"[\s_]+", " ", (kind or "").strip().lower())
    k = re.sub(r"\byes[-/ ]?no\b", "yes-no", k)
    return re.sub(r"\bpull[- ]quote\b", "pull-quote", k)


def fenced_kind(kind: str) -> tuple[str, str]:
    """(fenced block kind, form) a plan kind is written as: `steps vertical` -> ('steps', 'vertical'), `callout` ->
    ('callout', ''); ('', '') when the kind is written without a fenced block."""
    k = canon_kind(kind).split()
    if not k or k[0] not in FENCED_KINDS:
        return "", ""
    return k[0], " ".join(k[1:])


def list_items(chunk: list[str]) -> list[str]:
    """The items of a markdown list, an item's continuation lines joined to it."""
    items, cur = [], []
    for c in chunk:
        if not c.strip():
            continue
        if _LIST_ITEM.match(c):
            if cur:
                items.append(" ".join(cur))
            cur = [_LIST_ITEM.sub("", c, count=1)]
        else:
            cur.append(c.strip())
    if cur:
        items.append(" ".join(cur))
    return items


def yes_no_side(item: str) -> tuple[str, str]:
    """A yes/no item `✓ text` -> ('yes', 'text'); `✗ text` -> ('no', 'text'); ('', item) with no icon first."""
    m = _SIDE.match(item)
    if not m:
        return "", item.strip()
    return ("yes" if m.group(1) == YES else "no"), item[m.end():].strip()


_NUMBERED = re.compile(r"^\d+[.)]\s+")
_BOLD_FIRST = re.compile(r"^\*\*([^*]+?)\*\*\s*(.*)$", re.S)
_SOURCE = re.compile(r"^\s*[—–]\s*(\S.*)$")
_QUESTION = re.compile(r"^\*\*(.+?\?)\*\*\s*$")


def _fenced(kind: str, element: str, inner: list[str], line_no: int, problems: list[tuple[int, str]],
            form: str = "") -> Block:
    raw = "\n".join(inner).strip("\n")
    if kind == "callout":
        return Block("callout", element, raw, line_no)
    if kind == "pull-quote":
        lines = [l for l in raw.splitlines() if l.strip()]
        src = _SOURCE.match(lines[-1]) if len(lines) > 1 else None
        text = "\n".join(lines[:-1] if src else lines)
        return Block("pull-quote", element, text, line_no, source=src.group(1).strip() if src else "")
    if kind == "stat":
        m = _BOLD_FIRST.match(raw.strip())
        if not m or not m.group(2).strip():
            problems.append((line_no, "a stat opens with its number in bold, then the rest of the sentence says what "
                                      "it means: `**40%** of the apples on one tree fall before they ripen.`"))
        return Block("stat", element, raw, line_no, titles=[m.group(1).strip()] if m else [])
    if kind == "definition":
        m = _BOLD_FIRST.match(raw.strip())
        if not m or not re.match(r"^[—–-]\s*\S", m.group(2)):
            problems.append((line_no, "a definition opens with the term in bold, then a dash and what it means: "
                                      "`**Check valve** — a valve that lets water flow one way only.`"))
        return Block("definition", element, raw, line_no, titles=[m.group(1).strip()] if m else [])
    if kind == "faq":
        questions, answers = [], []
        for pair in re.split(r"\n\s*\n", raw.strip()):
            ls = [l.strip() for l in pair.splitlines() if l.strip()]
            q = _QUESTION.match(ls[0]) if ls else None
            if not q or len(ls) < 2:
                problems.append((line_no, "a FAQ is pairs split by a blank line: the question on a line of its own in "
                                          "bold, ending with `?` (`**Can the pump run dry?**`), the answer on the "
                                          "lines right after it"))
                continue
            questions.append(q.group(1).strip())
            answers.append(" ".join(ls[1:]))
        return Block("faq", element, raw, line_no, items=answers, titles=questions)
    if kind == "steps":
        items = list_items(inner)
        if form not in STEPS_FORMS:
            problems.append((line_no, "`::: steps` names its form: `::: steps vertical` or `::: steps horizontal`, as "
                                      "the plan gives it"))
        if not items or any(l.strip() and not l[:1].isspace() and not _NUMBERED.match(l) for l in inner):
            problems.append((line_no, "steps hold one numbered list and nothing else: one item per step, "
                                      "`1. **Short title:** what the reader does`"))
        titles = []
        for k, it in enumerate(items, 1):
            title, body = tile_parts(it)
            titles.append(title)
            if not title or not body:
                problems.append((line_no, f"step {k} has no {'bold title' if not title else 'body after its title'}: "
                                          "write `1. **Short title:** what the reader does`"))
        return Block("steps", element, raw, line_no, items=items, titles=titles, form=form)
    pairs = [yes_no_side(it) for it in list_items(inner)]
    if not pairs or any(l.strip() and not _LIST_ITEM.match(l) and not l[:1].isspace() for l in inner):
        problems.append((line_no, "a yes/no block holds one list and nothing else: one item per line, each "
                                  f"starting `- {YES} ` (what it does) or `- {NO} ` (what it does not do)"))
    return Block("yes-no", element, raw, line_no, items=[t for _, t in pairs], sides=[sd for sd, _ in pairs])


def tile_parts(item: str) -> tuple[str, str]:
    """A tile's list item `**Title:** body` -> (title, body), the graphic that opens it left out; ('', item) when the
    item does not start in bold."""
    item = _TILE_IMAGE.sub("", item.strip(), count=1)
    m = _TILE.match(item.strip())
    if not m:
        return "", item.strip()
    return m.group(1).strip().rstrip(":.").strip(), re.sub(r"^[:.—–-]\s*", "", m.group(2)).strip()


def read_text(text: str, kinds: dict[str, str] | None = None) -> Text:
    """TEXT.md -> blocks and headings. `kinds` ({plan element id: kind}) makes a list under a `tiles` element a
    tiles block: tiles are written as a list, one `- **Title:** body` item per tile (README «Text»)."""
    kinds = kinds or {}
    blocks: list[Block] = []
    headings: list[tuple[int, str, int]] = []
    unmarked: list[int] = []
    problems: list[tuple[int, str]] = []
    element = ""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        m = _MARKER.match(line)
        if m:
            element = m.group(1)
            i += 1
            continue
        h = _HEADING.match(line)
        if h:
            headings.append((len(h.group(1)), plain(h.group(2)), i + 1))
            i += 1
            continue
        if _FENCE_CLOSE.match(line):
            problems.append((i + 1, "a line `:::` with no block open: a fenced block starts with a line `::: <kind>`, "
                                    "one of " + ", ".join(f"`::: {k}`" for k in FENCED_KINDS if k != "steps")
                                    + ", `::: steps vertical`, `::: steps horizontal`"))
            i += 1
            continue
        f = _FENCE_OPEN.match(line)
        if f:
            start = i
            i += 1
            inner = []
            while i < len(lines) and not _FENCE_CLOSE.match(lines[i]) and not _MARKER.match(lines[i]) \
                    and not _HEADING.match(lines[i]) and not _FENCE_OPEN.match(lines[i]):
                inner.append(lines[i])
                i += 1
            closed = i < len(lines) and bool(_FENCE_CLOSE.match(lines[i]))
            if closed:
                i += 1
            kind, _, form = f.group(1).partition(" ")
            form = form.strip()
            if not closed:
                problems.append((start + 1, f"the block `::: {f.group(1)}` is not closed: end it with a line `:::`"))
            if kind not in FENCED_KINDS or (form and kind != "steps"):
                kind = f.group(1)
                problems.append((start + 1, f"`::: {kind}` is not a block the text knows; the fenced blocks are "
                                            + ", ".join(f"`::: {k}`" for k in FENCED_KINDS if k != "steps")
                                            + ", `::: steps vertical` and `::: steps horizontal`, written exactly so"))
                continue
            if not any(x.strip() for x in inner):
                problems.append((start + 1, f"the block `::: {kind}` is empty"))
                continue
            b = _fenced(kind, element, inner, start + 1, problems, form)
            if not element:
                unmarked.append(start + 1)
            blocks.append(b)
            continue
        start = i
        chunk = []
        while i < len(lines) and lines[i].strip() and not _MARKER.match(lines[i]) and not _HEADING.match(lines[i]) \
                and not _FENCE_OPEN.match(lines[i]) and not _FENCE_CLOSE.match(lines[i]):
            chunk.append(lines[i])
            i += 1
        raw = "\n".join(chunk)
        if all(c.strip().startswith("|") for c in chunk):
            rows = [_cells(c) for c in chunk]
            rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) for c in r if c)]
            b = Block("table", element, raw, start + 1, rows=rows)
        elif _FIGURE.match(chunk[0]) and len(chunk) == 1:
            b = Block("figure", element, raw, start + 1)
        elif _LIST_ITEM.match(chunk[0]):
            items = list_items(chunk)
            b = Block("list", element, raw, start + 1, items=items)
            if kinds.get(element, "").strip().lower() == "tiles":
                # a tile's graphic is kept apart: its alt text is no part of the tile's text for any gate
                graphics = [tile_graphic(it) for it in items]
                items = [_TILE_IMAGE.sub("", it.strip(), count=1) for it in items]
                b = Block("tiles", element, _ITEM_IMAGE.sub(r"\1", raw), start + 1, items=items,
                          titles=[tile_parts(it)[0] for it in items], graphics=graphics)
        else:
            b = Block("paragraph", element, raw, start + 1)
        if not element:
            unmarked.append(start + 1)
        blocks.append(b)
    return Text(blocks, headings, unmarked, problems)


def block_lines(b: Block, words_per_line: int) -> int:
    """How many lines a block takes, counted from its words (provisional sizing, README)."""
    if b.kind in PROSE_KINDS:
        return lines_of(b.text, words_per_line)
    if b.kind in ITEM_KINDS or b.kind == "tiles":
        return sum(lines_of(it, words_per_line) for it in b.items)
    if b.kind == "faq":
        return sum(lines_of(q, words_per_line) + lines_of(a, words_per_line) for q, a in zip(b.titles, b.items))
    if b.kind == "table":
        n = 0
        for r in b.rows:
            per_cell = max(1, words_per_line // max(1, len(r)))
            n += max(1, max(math.ceil(len(words(c)) / per_cell) for c in r) if r else 1)
        return n
    return 0


# ---------------------------------------------------------------- the whole folder

@dataclass
class Doc:
    folder: Path
    brief: str
    config: dict[str, str]
    terms: dict[str, str]
    plans: dict[int, list[PlanRow]]
    plan_problems: list[str]
    text: Text | None

    def plan_row(self, rid: str) -> PlanRow | None:
        for rows in self.plans.values():
            for r in rows:
                if r.id == rid:
                    return r
        return None

    def section_of(self, rid: str) -> str:
        """The level-1 id an element or subsection belongs to ('' if the chain breaks)."""
        seen = set()
        r = self.plan_row(rid)
        while r is not None and r.level > 1 and r.id not in seen:
            seen.add(r.id)
            r = self.plan_row(r.get("parent"))
        return r.id if r is not None and r.level == 1 else ""


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def load(folder: Path) -> Doc:
    pp = folder / PLAN_FILE
    plans, problems = read_plan(_read(pp)) if pp.exists() else ({1: [], 2: [], 3: []}, [])
    tp = folder / TEXT_FILE
    return Doc(folder, _read(folder / "BRIEF.md"), read_config(_read(folder / "GATES.md")),
               read_terms(_read(folder / "TERMS.md")), plans, problems,
               read_text(_read(tp), {r.id: r.get("kind") for r in plans[3]}) if tp.exists() else None)


def doc_folder(path: str) -> tuple[Path, str] | None:
    """(document folder, 'plan'|'text') when `path` is PLAN.md or TEXT.md of a folder with BRIEF.md."""
    p = Path(path)
    kinds = {PLAN_FILE: "plan", TEXT_FILE: "text"}
    if p.name not in kinds or not (p.parent / "BRIEF.md").exists():
        return None
    return p.parent, kinds[p.name]
