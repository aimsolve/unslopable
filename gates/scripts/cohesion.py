"""fact-soup and inline-list (both): a spaCy parse gives each sentence's subject and the enumerations of three or more
things in a paragraph; the judges decide. Fails nothing by itself."""
from __future__ import annotations

import json
import subprocess

from docs import Doc, PROSE_KINDS, brief_language, plain
from common import LIB, UV_SPACY, _cut


def parse_cohesion(paragraphs: list[list[str]]) -> list[dict]:
    """Runs cohesion_en.py under uv: per paragraph, the subject of each sentence and the coordinations of 3+ items."""
    r = subprocess.run(UV_SPACY + ["python", str(LIB / "cohesion_en.py")], input=json.dumps(paragraphs),
                       capture_output=True, text=True, timeout=150)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:] or f"exit {r.returncode}")
    return json.loads(r.stdout)


def gate_cohesion(doc: Doc, notices: list[str]) -> dict[int, dict]:
    """Marks for the judges `fact-soup` and `inline-list`: {block index: parse} for every marked
    paragraph. English only; fails nothing by itself."""
    lang = plain(brief_language(doc.brief)).lower()
    if lang and "english" not in lang:
        notices.append(f"fact-soup, inline-list: the parse exists only for English, the brief says «{_cut(lang, 60)}»; "
                       "the gates did not run")
        return {}
    idx = [i for i, b in enumerate(doc.text.blocks) if b.kind in PROSE_KINDS and b.element and b.sentences]
    if not idx:
        return {}
    try:
        res = parse_cohesion([doc.text.blocks[i].sentences for i in idx])
    except Exception as e:  # noqa: BLE001 — reported, never a silent pass
        notices.append(f"fact-soup, inline-list: the spaCy parse failed ({e}); the gates did not run")
        return {}
    if len(res) != len(idx):
        notices.append("fact-soup, inline-list: the parse gave a wrong number of answers; the gates did not run")
        return {}
    return dict(zip(idx, res))
