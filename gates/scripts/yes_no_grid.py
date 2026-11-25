"""yes-no-grid (both): flags table columns with a yes/no header or cells that start with a yes/no word; one judge
per table."""
from __future__ import annotations

import re

from docs import Doc, plain
from common import body_rows, group_row, tables


_YES_NO = re.compile(r"^(?:yes|no|y|n|true|false|on|off|none|supported|not supported|allowed|not allowed|required|"
                     r"not required|available|not available|can|cannot|can't|✓|✗|✔|✘|×)(?=\s*(?:$|[,.;:(—–-]))", re.I)
_TICK = re.compile(r"^\s*(?:✓|✗|✔|✘|×|—|–|-)?\s*$")
_QUESTION_HEADER = re.compile(r"^(?:can|could|does|do|is|are|has|have|will|may|should)\b|\?$", re.I)


def yes_no_columns(doc: Doc) -> list[tuple[int, list[str]]]:
    """A yes/no column is a ✓/✗ grid, script part: [(block index, headers of columns that may be yes/no answers in
    words)]. A column is a candidate when its header asks a yes/no question, or some data cell starts with a yes/no
    word, while its cells are not all bare ticks. The judge `gate-yes-no-grid` decides."""
    out = []
    for i, b in tables(doc):
        if len(b.rows) < 2:
            continue
        head = b.rows[0]
        cols = []
        for c, h in enumerate(head):
            if c == 0:
                continue  # the row labels
            cells = [plain(row[c]) for row in body_rows(b) if c < len(row) and not group_row(row)]
            if not cells or all(_TICK.match(x) for x in cells):
                continue
            if _QUESTION_HEADER.search(plain(h)) or any(_YES_NO.match(x) for x in cells):
                cols.append(plain(h) or f"column {c + 1}")
        if cols:
            out.append((i, cols))
    return out
