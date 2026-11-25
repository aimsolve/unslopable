"""out-of-scope (both): finds the names of GATES.md `out_of_scope_terms` in the plan and the text; the judge reads
the rest of what BRIEF.md puts out of scope."""
from __future__ import annotations

import re

from docs import Doc, plain
from common import Failure, _cut


def oos_terms(doc: Doc) -> list[str]:
    v = doc.config.get("out_of_scope_terms", "")
    return [t.strip().strip("`\"«»") for t in re.split(r";", v) if t.strip()]


def gate_oos_search(doc: Doc, pieces: list[tuple[str, str]]) -> list[Failure]:
    out = []
    for term in oos_terms(doc):
        pat = re.compile(r"(?<![\w-])" + re.escape(term) + r"(?![\w-])", re.I)
        for wh, text in pieces:
            if pat.search(plain(text)):
                out.append(Failure("out-of-scope", wh, _cut(text),
                                   f"names «{term}», which BRIEF.md puts out of scope (GATES.md out_of_scope_terms)"))
    return out
