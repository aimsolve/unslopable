"""term-explained (both), script part: an explain term's first use is not the first sentence of a section or
paragraph; the judge checks it is explained and led in."""
from __future__ import annotations

from docs import Doc
from common import Failure, _cut, first_uses, opens_paragraph, where


def gate_term_first_sentence(doc: Doc) -> list[Failure]:
    """Term explained, script part: an `explain` term first used in the first sentence of a paragraph has no lead-in."""
    out = []
    for term, u in first_uses(doc).items():
        if opens_paragraph(u, doc.text.blocks):
            out.append(Failure("term-first-use", where(u, doc.text.blocks), _cut(u.text),
                               f"the first use of «{term}» (an `explain` term) is the first sentence of a paragraph, "
                               "so nothing before it explains it or leads the reader to it"))
    return out
