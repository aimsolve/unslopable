"""example-own-line (both): finds example markers in paragraphs of two or more sentences; one judge per such
paragraph decides whether a full-sentence example should stand on its own line."""
from __future__ import annotations

import re

from docs import Doc, PROSE_KINDS


EXAMPLE = re.compile(r"(?:\b(?:for example|for instance|as an example|to illustrate|by way of example|example:)|"
                     r"\be\.g\.|\b(?:imagine|suppose|picture) (?:a|an|that|you)\b|\bsay(?:,| that) (?:a|an|you)\b)",
                     re.I)


def example_hits(doc: Doc) -> list[tuple[int, list[str]]]:
    """[(block index, sentences with an example marker)] for paragraphs of two or more sentences: an example there
    may be a full sentence buried in the paragraph, or a short inline clause, which stays; the judge decides."""
    out = []
    for i, b in enumerate(doc.text.blocks):
        if b.kind not in PROSE_KINDS or not b.element or len(b.sentences) < 2:
            continue
        hits = [s for s in b.sentences if EXAMPLE.search(s)]
        if hits:
            out.append((i, hits))
    return out
