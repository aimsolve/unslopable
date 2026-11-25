"""heading-no-colon-dash (script): a heading has no colon or dash. On plan levels 1 and 2 and on TEXT.md."""
from __future__ import annotations

import re

from docs import plain
from common import Failure


def gate_heading_no_colon_dash(items: list[tuple[str, str]]) -> list[Failure]:
    """`items`: (where, heading)."""
    out: list[Failure] = []
    for wh, h in items:
        t = plain(h)
        if re.search(r":|—|–|\s-\s|^-\s|\s-$", t):
            out.append(Failure("heading-no-colon-dash", wh, t, "a heading has a colon or a dash"))
    return out
