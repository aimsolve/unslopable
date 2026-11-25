"""term-order (both): finds plan items before an explain term's explaining element that use the term's word; the
judge decides whether each is the term."""
from __future__ import annotations

from docs import Doc, plain
from common import _EXPLAINS, plan_explains, term_pattern


def term_order_candidates(doc: Doc) -> list[tuple[str, str, str, str]]:
    """Plan: every item above a term's explaining element whose fields (all but headings) have the term's word
    (the descriptions of sections and subsections count too).
    [(term, explaining element, earlier item, its text)]. The word may be an ordinary word there, so a judge decides
    each one."""
    rows = doc.plans.get(3, [])
    explained_in: dict[str, list] = {}
    for r in rows:
        for t in plan_explains(r):
            explained_in.setdefault(t.lower(), []).append(r)
    items = sorted((x for lvl in (1, 2, 3) for r in doc.plans.get(lvl, []) for x in [r] + r.tiles),
                   key=lambda r: r.line_no)
    out = []
    for term, mark in doc.terms.items():
        els = explained_in.get(term.lower(), [])
        if mark != "explain" or len(els) != 1:
            continue  # missing or doubled: terms-placed fails it
        pat = term_pattern(term)
        for r in items:
            if r.line_no >= els[0].line_no:
                break
            if r.level < 3:
                text = plain(r.get("covers"))
            elif r.level == 4:
                text = " · ".join(plain(r.get(k)) for k in ("title", "body", "graphic"))
            else:
                text = " · ".join(x for x in (r.get("kind"), plain(_EXPLAINS.sub("", r.get("says"))),
                                              r.get("facts") and "facts: " + r.get("facts")) if x)
            if pat.search(text):
                out.append((term, els[0].id, r.id, text))
    return out
