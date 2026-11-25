"""term-marked (script): an explain term is in italics or bold at its first use."""
from __future__ import annotations

import re

from docs import Doc
from common import Failure, _cut, first_uses, term_pattern, where


_EMPH_SPAN = re.compile(r"(\*\*|__)(?=\S).+?(?<=\S)\1|(?<![*\w])\*(?=[^\s*]).+?(?<=[^\s*])\*(?![*\w])|"
                        r"(?<![_\w])_(?=[^\s_]).+?(?<=[^\s_])_(?![_\w])")


def gate_term_marked(doc: Doc) -> list[Failure]:
    """An `explain` term is in italics or bold at its first use in the document."""
    out = []
    for term, u in first_uses(doc).items():
        raw = doc.text.blocks[u.block].text  # unit texts are plain; the markup is in the block's raw text
        m = term_pattern(term).search(raw)
        if m is None:
            continue  # the markup splits the term; the plain text found it, so it is marked in some way
        before, after = raw[:m.start()], raw[m.end():]
        if re.search(r"(\*{1,2}|_{1,2})$", before) and re.match(r"(\*{1,2}|_{1,2})", after):
            continue
        if any(a <= m.start() and m.end() <= b for a, b in (e.span() for e in _EMPH_SPAN.finditer(raw))):
            continue  # inside a longer bold or italic phrase («**the pump holds the water**»)
        out.append(Failure("term-marked", where(u, doc.text.blocks), _cut(u.text),
                           f"the first use of «{term}» (an `explain` term) is not marked: write it in italics "
                           f"(*{m.group(0)}*) or bold here"))
    return out
