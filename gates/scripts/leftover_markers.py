"""leftover-markers (script): no working marker is left in TEXT.md (TODO, TBD, FIXME and the ones GATES.md adds)."""
from __future__ import annotations

import re

from docs import Doc
from common import Failure, _cut, _raw_text_lines


# Working markers a finished text must not keep. A document adds its own in GATES.md:
# `leftover_markers: <marker>; <marker>` (they extend this list, never replace it).
LEFTOVER_MARKERS = ("TODO", "TBD", "FIXME", "XXX", "???", "[уточнить]", "[проверить]", "[TK]",
                    "[citation needed]", "lorem ipsum")
# XXX is also a Roman numeral: «the XXX Olympiad», «XXX съезд», «XXX century» are not markers
_ROMAN_AFTER = r"(?!\s+(?:[A-ZА-ЯЁа-яё]|centur))"


def leftover_markers(doc: Doc) -> list[str]:
    extra = [t.strip().strip("`\"«»") for t in doc.config.get("leftover_markers", "").split(";")]
    return list(dict.fromkeys(list(LEFTOVER_MARKERS) + [t for t in extra if t]))


def _marker_pattern(m: str) -> re.Pattern:
    """An all-caps word (TODO) matches as a whole word, case kept, so «todo» in running text is not a marker;
    anything else matches as written, any case."""
    if re.fullmatch(r"[A-Z]{2,}", m):
        roman = _ROMAN_AFTER if re.fullmatch(r"[IVXLCDM]+", m) else ""
        return re.compile(r"(?<![\w-])" + re.escape(m) + r"(?![\w-])" + roman)
    return re.compile(re.escape(m), re.I)


def gate_leftover_markers(doc: Doc) -> list[Failure]:
    pats = [(m, _marker_pattern(m)) for m in leftover_markers(doc)]
    out = []
    for n, line in _raw_text_lines(doc):
        for m, pat in pats:
            if pat.search(line):
                out.append(Failure("leftover-marker", f"TEXT.md line {n}", _cut(line),
                                   f"a working marker «{m}» is left in the text; write the place out or ask the "
                                   "author for what is missing"))
    return out
