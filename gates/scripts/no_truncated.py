"""no-truncated (both): finds paragraph sentences with no end mark or, by a spaCy parse, no verb; one judge per
flagged paragraph decides."""
from __future__ import annotations

import json
import re
import subprocess

from docs import Doc, PROSE_KINDS, brief_language, plain
from common import LIB, UV_SPACY, _cut


_END_MARK = re.compile(r"[.!?:…][\"'»”)\]*_]*$")


def parse_verbs(sentences: list[str]) -> list[bool]:
    r = subprocess.run(UV_SPACY + ["python", str(LIB / "verbs_en.py")], input=json.dumps(sentences),
                       capture_output=True, text=True, timeout=150)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:] or f"exit {r.returncode}")
    return json.loads(r.stdout)


def gate_truncated(doc: Doc, notices: list[str]) -> dict[int, list[str]]:
    """{block index: flagged sentences} for paragraphs and callouts: a sentence with no end mark (only the last one of a paragraph
    can lack one, the split is at end marks), or with no verb by the parse. Paragraphs only: list items and table
    cells are never checked. Fails nothing by itself."""
    blocks = doc.text.blocks
    idx = [i for i, b in enumerate(blocks) if b.kind in PROSE_KINDS and b.element and b.sentences]
    out: dict[int, list[str]] = {}
    for i in idx:
        last = blocks[i].sentences[-1]
        if not _END_MARK.search(last):
            out.setdefault(i, []).append(last)
    lang = plain(brief_language(doc.brief)).lower()
    if lang and "english" not in lang:
        notices.append(f"no-truncated: the verb parse exists only for English, the brief says «{_cut(lang, 60)}»; "
                       "the verb part did not run, only the end marks were checked")
        return out
    pieces = [(i, s) for i in idx for s in blocks[i].sentences]
    if not pieces:
        return out
    try:
        res = parse_verbs([s for _, s in pieces])
    except Exception as e:  # noqa: BLE001 — reported, never a silent pass
        notices.append(f"no-truncated: the spaCy parse failed ({e}); the verb part did not run, only the end marks "
                       "were checked")
        return out
    if len(res) != len(pieces):
        notices.append("no-truncated: the parse gave a wrong number of answers; the verb part did not run, only the end "
                       "marks were checked")
        return out
    for (i, s), has_verb in zip(pieces, res):
        if not has_verb and s not in out.get(i, []):
            out.setdefault(i, []).append(s)
    return out
