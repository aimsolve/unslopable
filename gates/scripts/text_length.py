"""text-length (script): each element's length in TEXT.md is within `length_tolerance_pct` of its `lines`."""
from __future__ import annotations

from docs import Doc, block_lines, is_figure_kind
from common import Failure, _miss, _num, _tol


def gate_text_length(doc: Doc) -> list[Failure]:
    out: list[Failure] = []
    pct = _tol(doc, out)
    wpl = _num(doc, "words_per_line", "length", out)
    if pct is None or wpl is None:
        return out
    got: dict[str, int] = {}
    for b in doc.text.blocks:
        if b.element:
            got[b.element] = got.get(b.element, 0) + block_lines(b, int(wpl))
    for el, n in got.items():
        r = doc.plan_row(el)
        if r is None or r.level != 3 or is_figure_kind(r.get("kind")):
            continue
        want = r.lines or 0
        if _miss(n, want, pct):
            out.append(Failure("length", f"TEXT.md element {el}", f"{n} lines",
                               f"the text is {n} lines, the plan gives {want:g} ± {pct:g}%. The miss goes back to "
                               "the plan, never to cutting finished text: change the element's size in PLAN.md (and "
                               "the sizes above it if their sums change), have the changed levels approved again, "
                               "then write the element anew from the plan"))
    return out
