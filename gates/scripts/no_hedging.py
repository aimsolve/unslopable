"""no-hedging (both): finds sentences that hedge the document's own authority («not an exhaustive review»); its
judge decides each."""
from __future__ import annotations

import re

from docs import Doc
from common import Unit, flagged


HEDGES = re.compile(
    r"\b(?:not (?:an? |intended (?:to be |as )an? )?(?:exhaustive|complete|comprehensive|definitive)|non-exhaustive|"
    r"does not (?:claim|aim|attempt|purport)|do(?:es)? not cover (?:all|every)|may not cover|cannot cover|"
    r"to the best of (?:our|my) knowledge|as far as we (?:know|can tell)|high-level (?:overview|view|look)|"
    r"(?:indicative|illustrative) only|should not be (?:relied|taken|treated|considered)|not a substitute for|"
    r"not (?:legal|security|professional) advice|beyond the scope|outside the scope|limited (?:review|scope|"
    r"assessment)|we (?:do not|cannot|can't) (?:guarantee|claim|promise)|no guarantee|at the time of writing|"
    r"may (?:be|become) (?:incomplete|outdated|inaccurate)|subject to change|preliminary|in our (?:limited )?"
    r"(?:view|opinion|experience))\b", re.I)


def hedge_hits(doc: Doc) -> list[tuple[Unit, str]]:
    return flagged(doc, HEDGES)
