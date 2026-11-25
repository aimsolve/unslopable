"""sentence-max-words (script): a sentence has at most `sentence_max_words` words."""
from __future__ import annotations

from docs import Doc, split_sentences, words
from common import Failure, _cut, _num, body_units, where


def gate_sentence_words(doc: Doc) -> list[Failure]:
    out: list[Failure] = []
    n = _num(doc, "sentence_max_words", "sentence-max-words", out)
    if n is None:
        return out
    for u in body_units(doc.text.blocks):
        for s in (split_sentences(u.text) if u.kind != "sentence" else [u.text]):
            k = len(words(s))
            if k > n:
                out.append(Failure("sentence-max-words", where(u, doc.text.blocks), _cut(s),
                                   f"{k} words, at most {int(n)}"))
    return out
