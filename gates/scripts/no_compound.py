"""no-compound (both): a spaCy parse finds compound sentences in the text and in the plan's `covers` and `says`
fields; the sentences the parse is unsure of go to the judge."""
from __future__ import annotations

import json
import re
import subprocess

from docs import Doc, PLAN_FILE, brief_language, canon_kind, plain, split_sentences, words
from common import Failure, LIB, UV_SPACY, Unit, _EXPLAINS, _cut, body_units, where

# the plan kinds whose third field is a list separated by semicolons: a diagram's blocks and links, steps, FAQ questions
_LISTED = re.compile(r"\b(?:diagrams?|steps?|faq)\b")


def parse_compound(sentences: list[str]) -> list[dict | None]:
    """Runs compound_en.py under uv (spaCy needs Python 3.11; the hook runs on the system Python)."""
    r = subprocess.run(UV_SPACY + ["python", str(LIB / "compound_en.py")], input=json.dumps(sentences),
                       capture_output=True, text=True, timeout=150)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[-400:] or f"exit {r.returncode}")
    return json.loads(r.stdout)


def gate_compound(doc: Doc, notices: list[str]) -> tuple[list[Failure], list[tuple[Unit, str, dict]]]:
    """No compound sentence, script part: (errors, candidates for the judge). English only (spaCy en_core_web_sm)."""
    lang = plain(brief_language(doc.brief)).lower()
    if lang and "english" not in lang:
        notices.append(f"no-compound: the parse exists only for English, the brief says «{_cut(lang, 60)}»; "
                       "the gate did not run")
        return [], []
    pieces = []
    for u in body_units(doc.text.blocks):
        for s in (split_sentences(u.text) if u.kind != "sentence" else [u.text]):
            if len(words(s)) >= 4:
                pieces.append((u, s))
    if not pieces:
        return [], []
    try:
        res = parse_compound([s for _, s in pieces])
    except Exception as e:  # noqa: BLE001 — reported, never a silent pass
        notices.append(f"no-compound: the spaCy parse failed ({e}); the gate did not run")
        return [], []
    if len(res) != len(pieces):
        notices.append(f"no-compound: the parse gave {len(res)} answers for {len(pieces)} sentences; the gate did "
                       "not run")
        return [], []
    errors, cands = [], []
    for (u, s), r in zip(pieces, res):
        if not r:
            continue
        if r["verdict"] == "error":
            errors.append(Failure("no-compound", where(u, doc.text.blocks), _cut(s, 240),
                                  "two main clauses with different subjects ("
                                  + " / ".join(r["predicates"]) + f") joined by «{r['joiner']}»; "
                                  "split into two sentences or make one clause subordinate"))
        else:
            cands.append((u, s, r))
    return errors, cands


def gate_plan_compound(doc: Doc, levels: list[int], notices: list[str]) -> tuple[list[Failure], list[tuple[str, str, dict]]]:
    """No compound sentence in the plan: the `covers` and `says` fields of the given levels.
    Returns (errors, candidates for the judge as (where, sentence, parse))."""
    lang = plain(brief_language(doc.brief)).lower()
    if lang and "english" not in lang:
        notices.append(f"no-compound: the parse exists only for English, the brief says «{_cut(lang, 60)}»; "
                       "the gate did not run on the plan")
        return [], []
    pieces = []
    for lvl in levels:
        for r in doc.plans.get(lvl, []):
            field = r.get("covers") if lvl < 3 else _EXPLAINS.sub("", r.get("says"))
            fields = [(r.id, field)] + [(t.id, t.get("body")) for t in r.tiles]
            for rid, text in fields:
                # a diagram, steps or a FAQ lists its blocks and links, steps or questions in one field, separated by
                # semicolons (the plan skill): each part is parsed on its own
                parts = text.split(";") if lvl == 3 and rid == r.id and _LISTED.search(canon_kind(r.get("kind"))) \
                    else [text]
                for sent in (s for part in parts for s in split_sentences(plain(part))):
                    if len(words(sent)) >= 4:
                        pieces.append((f"{PLAN_FILE} {rid}", sent))
    if not pieces:
        return [], []
    try:
        res = parse_compound([x for _, x in pieces])
    except Exception as e:  # noqa: BLE001 — reported, never a silent pass
        notices.append(f"no-compound: the spaCy parse failed ({e}); the gate did not run on the plan")
        return [], []
    if len(res) != len(pieces):
        notices.append("no-compound: the parse gave a wrong number of answers; the gate did not run on the plan")
        return [], []
    errors, cands = [], []
    for (w, sent), r in zip(pieces, res):
        if not r:
            continue
        if r["verdict"] == "error":
            errors.append(Failure("no-compound", w, _cut(sent, 240),
                                  "two main clauses with different subjects (" + " / ".join(r["predicates"])
                                  + f") joined by «{r['joiner']}»; split it or make one clause subordinate"))
        else:
            cands.append((w, sent, r))
    return errors, cands
