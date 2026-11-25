"""table-flat (both): fails a list or table plainly written inside a cell; flags cells that may hide one for the
judge."""
from __future__ import annotations

import re

from docs import Doc, plain
from common import Failure, _cut, tables


# a list or table plainly written inside a cell: a line break, a bullet, HTML list markup
_NESTED = re.compile(r"<br\s*/?>|<\s*/?\s*(?:ul|ol|li|table|tr|td)\b|•|^\s*[-*+]\s+\S.*\s[-*+]\s+\S", re.I)
# a cell that may hide a list or a table: three or more parts split by commas, or `label: value` with more after it
_MAYBE_NESTED = re.compile(r"[^,]+,[^,]+,[^,]+|\w[^:]*:\s+\S.*[,/]\s*\w[^:]*:\s+\S")


def gate_table_flat(doc: Doc) -> list[Failure]:
    """Only 2-D data, script part: a cell with a line break, bullets or list markup holds a list. Cells that only may
    hide one (several comma parts, `label: value` pairs) go to the judge `gate-table-flat`."""
    out = []
    for _, b in tables(doc):
        for r, row in enumerate(b.rows, 1):
            for c, cell in enumerate(row, 1):
                m = _NESTED.search(cell)
                if m:
                    out.append(Failure("table-flat", f"TEXT.md line {b.line_no} ({b.element}, row {r}, column {c})",
                                       _cut(cell), "a list inside a table cell: make each item its own row or "
                                       "column, or move the list out of the table"))
    return out


def flat_candidates(doc: Doc) -> list[tuple[int, list[str]]]:
    """[(block index, cells that may hide a list or a table)] for the judge `gate-table-flat`."""
    out = []
    for i, b in tables(doc):
        cells = [c for row in b.rows for c in row
                 if plain(c) and not _NESTED.search(c) and _MAYBE_NESTED.search(plain(c))]
        if cells:
            out.append((i, cells))
    return out
