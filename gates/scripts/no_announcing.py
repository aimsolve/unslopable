"""no-announcing (both, off by default): finds sentences that announce later contents («below we look at…»);
one judge per paragraph or list with such sentences."""
from __future__ import annotations

import re

from docs import Doc
from common import flagged_paragraphs


ANNOUNCING = re.compile(
    r"\b(?:(?:below|further on|later on),? (?:we|I|you)\b|(?:see|shown|listed|described|explained|discussed|covered|"
    r"detailed|outlined|given) (?:below|later|further on)\b|in (?:the )?(?:next|following|coming|later|last|final) "
    r"(?:section|chapter|part|pages?|paragraphs?)\b|the (?:next|following|later|remaining) (?:sections?|chapters?|"
    r"parts?|pages?)\b|(?:more|details?) (?:in|on) (?:section|chapter|part|appendix|§)|(?:we|I) (?:will|'ll|shall) "
    r"(?:look|return|come back|turn|get|discuss|cover|explain|see|show|describe)\b|(?:is|are|will be) (?:discussed|"
    r"covered|explained|described|shown|addressed|detailed|treated) (?:later|below|further)\b|as we will see\b|"
    r"more on (?:this|that|it) later\b|(?:we|I) come (?:back )?to (?:this|that|it) later\b)", re.I)


def announcing_hits(doc: Doc) -> list[tuple[int, list[str]]]:
    return flagged_paragraphs(doc, "no-announcing", ANNOUNCING)
