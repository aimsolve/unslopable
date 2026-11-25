"""announced-count (both): finds paragraphs with a number before a word, a count the text may announce; one judge
per paragraph decides whether exactly that many things follow."""
from __future__ import annotations

import re

from docs import Doc, PROSE_KINDS


NUMBER_WORDS = ("two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                "seventeen eighteen nineteen twenty dozen")
_COUNT = re.compile(r"(?<![\w.-])(?:top\s+)?(\d{1,3}|" + "|".join(NUMBER_WORDS.split()) + r")(?![\w.%-])\s+(?!%)"
                    r"(?!(?:minutes?|hours?|days?|weeks?|months?|years?|seconds?|percent|per|times|lines?|pages?|"
                    r"words?|pt|px|mb|gb|kb)\b)[A-Za-z]", re.I)


def count_hits(doc: Doc) -> list[tuple[int, list[str]]]:
    """Paragraphs with a number before a word — a count that may be announced:
    [(block index, the sentences with such a number)]. Years and measures are left out; the judge decides the rest."""
    out = []
    for i, b in enumerate(doc.text.blocks):
        if b.kind not in PROSE_KINDS or not b.element:
            continue
        hits = [s for s in b.sentences if _COUNT.search(s)]
        if hits:
            out.append((i, hits))
    return out
