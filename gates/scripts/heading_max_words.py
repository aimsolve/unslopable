"""heading-max-words (script): a heading has at most `heading_max_words` words (GATES.md). On plan levels 1 and 2
and on TEXT.md."""
from __future__ import annotations

from docs import Doc, plain, words
from common import Failure, _num


def gate_heading_max_words(doc: Doc, items: list[tuple[str, str]]) -> list[Failure]:
    """`items`: (where, heading)."""
    out: list[Failure] = []
    n = _num(doc, "heading_max_words", "heading-max-words", out)
    if n is None:
        return out
    for wh, h in items:
        t = plain(h)
        if len(words(t)) > n:
            out.append(Failure("heading-max-words", wh, t, f"{len(words(t))} words, at most {int(n)}"))
    return out
