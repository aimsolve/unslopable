"""tile-graphic and tile-length (both): on the plan and the text, every tile has its own graphic file and a body of
at most 2 lines; the judge of tile-graphic looks at the picture."""
from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path

from docs import Block, Doc, PLAN_FILE, plain, tile_parts, words
from common import Failure, _cut, _num


# Tiles gate: every tile has its own graphic, drawn for it, and its body (the text under its title) is
# at most 2 lines. A tile is about half the text column wide (two tiles a row), so a line of its body holds about
# 6 words at body size; a document with another layout sets `tile_words_per_line` in GATES.md.
TILE_MAX_LINES = 2
TILE_WORDS_PER_LINE = 6
_RASTER = (".png", ".jpg", ".jpeg", ".webp", ".gif")
TILE_IMAGE_EXT = (".svg",) + _RASTER
_TOO_LONG = ("a tile's text under its title is at most 2 lines. The planner decides: shorten the tile, or move the "
             "explanation into the text next to the tiles (a paragraph element before or after them)")


def tile_budget(doc: Doc, out: list[Failure]) -> tuple[float, int] | None:
    """(words per line of a tile, words its body may have); None, with a `config` failure, for a number under 1."""
    raw = doc.config.get("tile_words_per_line")
    if raw is not None and not re.search(r"\d", raw):
        out.append(Failure("config", "GATES.md", f"tile_words_per_line: {raw}", "is not a number; set the number of "
                           "words a line of a tile's body holds"))
        return None
    wpl = _num(doc, "tile_words_per_line", "tile-length", out, default=TILE_WORDS_PER_LINE)
    if wpl < 1:
        out.append(Failure("config", "GATES.md", f"tile_words_per_line: {wpl:g}", "a line of a tile holds at least "
                           "one word; set the number of words a line of a tile's body holds"))
        return None
    return wpl, int(TILE_MAX_LINES * wpl)


def _too_long(n: int, wpl: float) -> str:
    return (f"the body is {n} words, about {math.ceil(n / wpl)} lines at {wpl:g} words a line (GATES.md "
            f"tile_words_per_line); {_TOO_LONG}")


def gate_plan_tiles(doc: Doc) -> list[Failure]:
    """On the plan's elements: a `tiles` element has its tiles under it, each with what its graphic shows
    (tile-graphic), and each tile's body is at most 2 lines by its `N lines` and by its words (tile-length). The gate
    only reports; what to do with a long tile is the planner's call."""
    out: list[Failure] = []
    budget = tile_budget(doc, out)
    wpl, budget = budget if budget else (0, 0)
    for r in doc.plans.get(3, []):
        if r.get("kind").strip().lower() != "tiles":
            continue
        if not r.tiles:
            out.append(Failure("tile-graphic", f"{PLAN_FILE} {r.id}", "",
                               "a tiles element with no tiles under it: put each tile on its own line under the "
                               "element, `id · **title** · what the tile says · graphic: what its picture shows · "
                               "N lines`, so each tile gets a graphic drawn for it"))
        for t in r.tiles:
            where = f"{PLAN_FILE} {t.id}"
            if not t.get("graphic"):
                out.append(Failure("tile-graphic", where, "", "says nothing after `graphic:`: say what this tile's "
                                   "own picture shows, so the illustrator draws it for this tile"))
            n = len(words(t.get("body")))
            if t.lines is not None and t.lines > TILE_MAX_LINES:
                out.append(Failure("tile-length", where, t.get("lines"), f"the tile is planned at {t.get('lines')}; "
                                   + _TOO_LONG))
            elif wpl and n > budget:
                out.append(Failure("tile-length", where, _cut(t.get("body")), _too_long(n, wpl)))
    return out


def gate_text_tiles(doc: Doc) -> list[Failure]:
    """On TEXT.md: each tile's body is at most 2 lines by its words (tile-length), and each tile opens with its own
    graphic, `- ![what it shows](figures/<tile id>.svg) **Title:** body` (tile-graphic). The tiles are written in the
    plan's order, so the k-th tile of the text is the k-th tile of its plan element, and its graphic is that tile's
    file: in the document's `figures/`, named for that tile, no copy of another tile's file, drawn or generated, not
    a screenshot. Whether the picture is really drawn for the tile is the judge's, on the file."""
    out: list[Failure] = []
    budget = tile_budget(doc, out)
    rows = {r.id: r for r in doc.plans.get(3, [])}
    figs = Path(os.path.realpath(Path(doc.folder) / "figures"))
    by_sha: dict[str, str] = {}
    count: dict[str, int] = {}   # tiles of each element seen so far: an element may hold more than one list
    last: dict[str, Block] = {}
    for b in doc.text.blocks:
        if b.kind != "tiles":
            continue
        plan_tiles = rows[b.element].tiles if b.element in rows else []
        last[b.element] = b
        for i, it in enumerate(b.items):
            k = count[b.element] = count.get(b.element, 0) + 1
            tid = f", {plan_tiles[k - 1].id}" if k <= len(plan_tiles) else ""
            where = f"TEXT.md line {b.line_no} ({b.element}, tile {k}{tid})"
            _, body = tile_parts(it)
            n = len(words(body))
            if budget and n > budget[1]:
                out.append(Failure("tile-length", where, _cut(body), _too_long(n, budget[0]) + "; tell the author "
                                   "which tile misses, the change goes into PLAN.md"))
            if k > len(plan_tiles):
                out.append(Failure("tile-graphic", where, _cut(it, 80),
                                   f"the plan gives {b.element} {len(plan_tiles)} tiles, and this is tile {k}: write "
                                   "the plan's tiles, in its order"))
                continue
            tile = plan_tiles[k - 1]
            want = f"figures/{tile.id}.svg"
            _, img = b.graphics[i] if i < len(b.graphics) else ("", "")
            if not img:
                out.append(Failure("tile-graphic", where, _cut(it, 80),
                                   f"a tile with no graphic: start the illustrator for tile {tile.id}, then open the "
                                   f"item with its file, `- ![what it shows]({want}) **Title:** body`"))
                continue
            p = Path(os.path.realpath(Path(doc.folder) / os.path.expanduser(img)))
            if re.match(r"[a-z]+://", img) or figs not in p.parents or not p.is_file():
                out.append(Failure("tile-graphic", where, img, "the graphic is not a file in the document's "
                                   f"`figures/`; start the illustrator for tile {tile.id}, its file is {want}"))
                continue
            if p.stem != tile.id:
                out.append(Failure("tile-graphic", where, img, f"this is tile {k} of {b.element}, the plan's "
                                   f"{tile.id} «{plain(tile.get('title'))}», and the graphic is not named for it, "
                                   f"so it is not drawn for this tile; its graphic is {want}"))
                continue
            if p.suffix.lower() not in TILE_IMAGE_EXT:
                out.append(Failure("tile-graphic", where, img, "not an image: a tile's graphic is an `.svg` the "
                                   "illustrator draws (or a generated raster with its prompt file)"))
                continue
            if p.suffix.lower() in _RASTER and not p.with_suffix(".prompt.md").exists():
                out.append(Failure("tile-graphic", where, img, "a screenshot (a raster with no prompt file beside "
                                   f"it), not a graphic drawn for the tile; start the illustrator for tile {tile.id}"))
                continue
            sha = hashlib.sha1(p.read_bytes()).hexdigest()
            if sha in by_sha:
                out.append(Failure("tile-graphic", where, img, f"a copy of the graphic of {by_sha[sha]}; every tile "
                                   "has a graphic drawn for it"))
            by_sha.setdefault(sha, where)
    for el, b in last.items():
        for tile in (rows[el].tiles if el in rows else [])[count.get(el, 0):]:
            out.append(Failure("tile-graphic", f"TEXT.md line {b.line_no} ({el})", tile.id,
                               f"the plan's tile {tile.id} «{plain(tile.get('title'))}» is not in the text; write "
                               "every tile of the plan, in its order, each with its graphic"))
    return out
