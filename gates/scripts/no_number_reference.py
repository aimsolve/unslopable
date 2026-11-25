"""no-number-reference (both): finds references by number or position («see § 3.2», «table 4», «as said above»);
its judge decides each."""
from __future__ import annotations

import re

from docs import Doc
from common import Unit, flagged


NUMBER_REFS = re.compile(
    r"(?:§\s*\d|\b(?:section|sections|chapter|part|table|figure|fig\.|appendix|annex|step|item|point|paragraph)"
    r"\s+(?:\d+(?:\.\d+)*|[A-Z]\b|[IVX]+\b)|\b(?:see|as|was|were|is|are)\s+(?:(?:said|noted|mentioned|shown|"
    r"described|discussed|explained|stated|listed|outlined)\s+)?(?:above|below|earlier|previously|later)\b|"
    r"\b(?:the|see the)\s+(?:above|below|previous|preceding|following|next)\s+(?:section|table|figure|list|"
    r"paragraph|chapter|part)\b|\bthe (?:former|latter)\b)", re.I)


def number_reference_hits(doc: Doc) -> list[tuple[Unit, str]]:
    return flagged(doc, NUMBER_REFS)
