"""one-sentence-per-item (script): a list item or a table cell is one sentence."""
from __future__ import annotations

from docs import Doc, split_sentences
from common import Failure, _cut, body_units, where


def gate_one_sentence_per_item(doc: Doc) -> list[Failure]:
    out = []
    for u in body_units(doc.text.blocks):
        if u.kind in ("item", "tile", "cell"):
            k = len(split_sentences(u.text))
            if k > 1:
                what = {"item": "list item", "tile": "tile", "cell": "table cell"}[u.kind]
                out.append(Failure("one-sentence-per-item", where(u, doc.text.blocks), _cut(u.text),
                                   f"a {what} with {k} sentences"))
    return out
