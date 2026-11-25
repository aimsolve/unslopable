"""term-counts (script): at most `terms_before_first_figure` explain terms before the first figure and
`new_terms_per_unit` new ones per unit."""
from __future__ import annotations

from docs import Doc, is_figure_kind
from common import Failure, _num, first_uses


def gate_term_counts(doc: Doc) -> list[Failure]:
    """Terms count: at most N new `explain` terms before the first figure, at most M in one plan element.

    A term first met in a list item, a tile or a table cell is not counted: an item of an outside list
    is explained right in its own row, item or tile, and the judge `external-items` checks that it is."""
    out: list[Failure] = []
    if not any(m == "explain" for m in doc.terms.values()):
        return out
    uses = {t: u for t, u in first_uses(doc).items() if u.kind not in ("item", "tile", "cell")}
    blocks = doc.text.blocks
    fig = next((i for i, b in enumerate(blocks) if b.kind == "figure"), None)
    plan_has_figure = any(is_figure_kind(r.get("kind")) for r in doc.plans.get(3, []))
    if fig is not None or plan_has_figure:
        n = _num(doc, "terms_before_first_figure", "term-counts", out)
        if n is not None:
            before = sorted((t for t, u in uses.items() if fig is None or u.block < fig),
                            key=lambda t: (uses[t].block, uses[t].pos))
            if len(before) > n:
                out.append(Failure("term-counts", "before the first figure" if fig is not None else
                                   "before the first figure (not written yet)", ", ".join(before),
                                   f"{len(before)} new `explain` terms, at most {int(n)} allowed"))
    m = _num(doc, "new_terms_per_unit", "term-counts", out, default=2)
    per: dict[str, list[str]] = {}
    for t, u in uses.items():
        per.setdefault(u.element or f"block at line {blocks[u.block].line_no}", []).append(t)
    for el, ts in per.items():
        if len(ts) > m:
            out.append(Failure("term-counts", f"element {el}", ", ".join(ts),
                               f"{len(ts)} new `explain` terms in one element, at most {int(m)} allowed"))
    return out
