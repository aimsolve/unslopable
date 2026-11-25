"""no-repetition (both): finds runs of 6 identical words in two sections, or between a FAQ or callout and the body;
one judge per complete section also looks for the same point in other words."""
from __future__ import annotations

from docs import Doc, canon_kind, words
from common import element_kind


REPEAT_RUN = 6
_SHARED_KINDS = ("faq", "callout")  # a FAQ or a callout repeating the body counts even inside one section


def repeat_hits(doc: Doc) -> list[tuple[str, str, str]]:
    """[(later element, earlier element, the repeated words)]: runs of REPEAT_RUN+ identical words (case and markup
    ignored) in two elements of different sections, or where one of the two is a FAQ or a callout. Elements of kind
    `summary` are left out: a summary repeats by design and has its own gate. So is a pull quote: it may set a phrase
    of the text large, by design."""
    els: dict[str, list[str]] = {}
    for b in doc.text.blocks:
        k = canon_kind(element_kind(doc, b.element)) if b.element else ""
        if b.element and b.kind not in ("figure", "pull-quote") and "summary" not in k and "pull-quote" not in k:
            els.setdefault(b.element, []).extend(w.lower() for w in words(b.text))
    seen: dict[tuple[str, ...], str] = {}  # word run -> first element it is in
    out = []
    for el, ws in els.items():
        n = REPEAT_RUN
        covered: dict[int, str] = {}
        for i in range(len(ws) - n + 1):
            key = tuple(ws[i:i + n])
            first = seen.get(key)
            if first is None:
                continue
            if first != el and (doc.section_of(first) != doc.section_of(el)
                                or any(k in element_kind(doc, x) for x in (first, el) for k in _SHARED_KINDS)):
                for j in range(i, i + n):
                    covered.setdefault(j, first)
        run: list[int] = []
        for j in sorted(covered) + [None]:
            if run and (j is None or j != run[-1] + 1 or covered[j] != covered[run[0]]):
                out.append((el, covered[run[0]], " ".join(ws[run[0]:run[-1] + 1])))
                run = []
            if j is not None:
                run.append(j)
        for i in range(len(ws) - n + 1):
            seen.setdefault(tuple(ws[i:i + n]), el)
    return out
