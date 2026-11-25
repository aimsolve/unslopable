"""tense-shift (both): a spaCy parse finds paragraphs with clauses in more than one tense; the judge decides
whether each shift follows a shift in time."""
from __future__ import annotations

import json
import subprocess

from docs import Doc, PROSE_KINDS, brief_language, plain
from common import LIB, UV_SPACY, _cut


def parse_tense(paragraphs: list[list[str]]) -> list[list[list[dict]]]:
    """Runs tense_en.py under uv: per paragraph, per sentence, the tense of each finite clause."""
    r = subprocess.run(UV_SPACY + ["python", str(LIB / "tense_en.py")], input=json.dumps(paragraphs),
                       capture_output=True, text=True, timeout=150)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:] or f"exit {r.returncode}")
    return json.loads(r.stdout)


def gate_tense(doc: Doc, notices: list[str]) -> dict[int, list[list[dict]]]:
    """Tense inconsistency, script part: {block index: the clauses' tenses per sentence} for every marked
    paragraph whose finite clauses are in more than one tense. Marks for the judge `gate-tense-shift`; fails nothing by
    itself. English only."""
    lang = plain(brief_language(doc.brief)).lower()
    if lang and "english" not in lang:
        notices.append(f"tense-shift: the parse exists only for English, the brief says «{_cut(lang, 60)}»; "
                       "the gate did not run")
        return {}
    idx = [i for i, b in enumerate(doc.text.blocks) if b.kind in PROSE_KINDS and b.element and b.sentences]
    if not idx:
        return {}
    try:
        res = parse_tense([doc.text.blocks[i].sentences for i in idx])
    except Exception as e:  # noqa: BLE001 — reported, never a silent pass
        notices.append(f"tense-shift: the spaCy parse failed ({e}); the gate did not run")
        return {}
    if len(res) != len(idx):
        notices.append("tense-shift: the parse gave a wrong number of answers; the gate did not run")
        return {}
    return {i: r for i, r in zip(idx, res) if len({c["tense"] for s in r for c in s}) > 1}
