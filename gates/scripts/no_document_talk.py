"""no-document-talk (both, off by default): finds sentences that talk about the document itself («this report
covers…»); one judge per paragraph or list with such sentences."""
from __future__ import annotations

import re

from docs import Doc
from common import flagged_paragraphs


DOCUMENT_TALK = re.compile(
    r"\b(?:(?:this|the present|the current|our) (?:document|report|paper|guide|article|assessment|analysis|review|"
    r"white ?paper|memo|brief|overview|post|text|section|chapter|page)s?\b|in (?:this|the present) "
    r"(?:document|report|paper|guide|article|text|section|chapter)\b|(?:here|in what follows),? (?:we|I) (?:look|"
    r"explain|describe|cover|discuss|show|present|outline|examine|review|summari[sz]e)\b|\bwe (?:will |shall |are "
    r"going to )?(?:now )?(?:cover|discuss|describe|present|explain|outline|examine|look at|walk through)\b|"
    r"\b(?:purpose|aim|goal|scope) of this\b)", re.I)


def document_talk_hits(doc: Doc) -> list[tuple[int, list[str]]]:
    return flagged_paragraphs(doc, "no-document-talk", DOCUMENT_TALK)
