"""slop-words (both): finds the words and phrases of the slop lists in gates/data/slop/; one judge per paragraph, list
or table with hits decides whether each is slop in its place."""
from __future__ import annotations

import json
import re

from docs import TEXT_KINDS, Doc, plain
from common import LIB, _CODE


SLOP_DIR = LIB.parent / "data" / "slop"
_SLOP: tuple[dict[str, list[str]], re.Pattern] | None = None


def slop_list() -> tuple[dict[str, list[str]], re.Pattern]:
    """{entry (lower case): the lists it is in} and one whole-word pattern for them all. The four lists of
    gates/data/slop/ merged whole (nothing cut)."""
    global _SLOP
    if _SLOP is None:
        import csv
        src: dict[str, list[str]] = {}

        def add(entry: str, name: str) -> None:
            e = entry.strip(" ,").lower().replace("’", "'")
            if e and name not in src.setdefault(e, []):
                src[e].append(name)

        with open(SLOP_DIR / "kobak_excess_words.csv", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                add(row["word"], "Kobak")
        for fname, name in (("antislop_slop_words.json", "Antislop words"),
                            ("antislop_slop_phrases.json", "Antislop phrases"),
                            ("antislop_hand_list.json", "Antislop hand list")):
            for entry, _ in json.loads((SLOP_DIR / fname).read_text(encoding="utf-8")):
                add(entry, name)
        alts = "|".join(re.escape(e) for e in sorted(src, key=len, reverse=True))
        _SLOP = src, re.compile(r"(?<![\w'-])(?:" + alts + r")(?![\w'-])", re.I)
    return _SLOP


def slop_hits(doc: Doc) -> list[tuple[int, list[tuple[str, list[str]]]]]:
    """No slop words, script part: every paragraph, list, tiles or table with a word or phrase
    of the lists — [(block index, [(the words as written, the lists they are in)])], each distinct entry once per block.
    Fails nothing by itself: one judge per block decides each hit (`gate-slop-words`)."""
    src, pat = slop_list()
    out = []
    for i, b in enumerate(doc.text.blocks):
        if b.kind not in TEXT_KINDS or not b.element:
            continue
        seen: dict[str, str] = {}
        for m in pat.finditer(_CODE.sub("", plain(b.text)).replace("’", "'")):
            seen.setdefault(m.group(0).lower(), m.group(0))
        if seen:
            out.append((i, [(w, src[k]) for k, w in seen.items()]))
    return out
