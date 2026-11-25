"""table-duplicate-row (script): no two data rows of a table have the same label."""
from __future__ import annotations

from docs import Doc, plain
from common import Failure, body_rows, group_row, tables


def gate_table_duplicate_rows(doc: Doc) -> list[Failure]:
    """No duplicate row labels in a table: the first cells of its data rows differ. A mini header row
    inside the table (a label with every other cell empty) is not a data row."""
    out = []
    for _, b in tables(doc):
        seen: dict[str, int] = {}
        for r, row in enumerate(body_rows(b), 2):
            if not row or group_row(row):
                continue
            key = plain(row[0]).lower()
            if not key:
                continue
            if key in seen:
                out.append(Failure("table-duplicate-row", f"TEXT.md line {b.line_no} ({b.element}, row {r})",
                                   plain(row[0]), f"the row label repeats row {seen[key]} of the same table: one row "
                                   "per label; what tells the two rows apart becomes a column"))
            else:
                seen[key] = r
    return out
