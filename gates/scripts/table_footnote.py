"""table-footnote (script): no footnote marks in a table."""
from __future__ import annotations

import re

from docs import Doc
from common import Failure, _CODE, tables


# a footnote mark: a lone asterisk (not emphasis), a dagger, a superscript digit, a markdown footnote `[^1]`
_EMPHASIS = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1|(\*|_)(?=\S)(.+?)(?<=\S)\3")
# a `*` stuck to the end of a word or number (not `2 * 3`, not `\*`); ² ³ after a letter are units (m², ft³)
_FOOTNOTE = re.compile(r"(?<=[\w)\]])(?<!\\)\*(?![\w*])|[†‡]|(?<![A-Za-z])[²³]|(?<!⁻)[¹⁴⁵⁶⁷⁸⁹⁰]|\[\^[^\]]*\]")


def _no_emphasis(cell: str) -> str:
    t = _CODE.sub("", cell).replace("\\*", "")
    while True:
        u = _EMPHASIS.sub(lambda m: m.group(2) or m.group(4) or "", t)
        if u == t:
            return t
        t = u


def gate_table_footnotes(doc: Doc) -> list[Failure]:
    """No footnote marks in a table: a condition becomes a column, a row or part of the row label."""
    out = []
    for _, b in tables(doc):
        for r, row in enumerate(b.rows):
            for c, cell in enumerate(row):
                m = _FOOTNOTE.search(_no_emphasis(cell))
                if m:
                    out.append(Failure("table-footnote", f"TEXT.md line {b.line_no} ({b.element}, row {r + 1}, "
                                       f"column {c + 1})", cell.strip()[:160],
                                       f"a footnote mark «{m.group(0)}» in a table: make the condition its own "
                                       "column, its own row or part of the row label"))
    return out
