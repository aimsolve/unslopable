"""plan-length (script): the `lines` of the plan add up to the brief's length, per section and for the document."""
from __future__ import annotations

from docs import Doc, PLAN_FILE
from common import Failure, _miss, _num, _tol, leaves


def gate_plan_length(doc: Doc, level: int) -> list[Failure]:
    out: list[Failure] = []
    pct = _tol(doc, out)
    if pct is None:
        return out
    if level == 1:
        total = _num(doc, "total_lines", "length", out)
        if total is not None:
            s = sum(r.lines or 0 for r in doc.plans.get(1, []))
            if _miss(s, total, pct):
                out.append(Failure("length", f"{PLAN_FILE}, all sections", f"{s:g} lines",
                                   f"the sections add up to {s:g} lines; the document is {total:g} lines "
                                   f"(GATES.md total_lines) ± {pct:g}%"))
        return out
    if level == 2:
        ids1 = {r.id: r for r in doc.plans.get(1, [])}
        sums: dict[str, float] = {}
        for r in doc.plans.get(2, []):
            p = r.get("parent")
            sums[p] = sums.get(p, 0) + (r.lines or 0)
        for p, s in sums.items():
            want = ids1[p].lines or 0
            if _miss(s, want, pct):
                out.append(Failure("length", f"{PLAN_FILE}, subsections of {p}", f"{s:g} lines",
                                   f"they add up to {s:g} lines; {p} is {want:g} lines ± {pct:g}%"))
        return out
    lv = leaves(doc)
    sums = {p: 0.0 for p in lv}  # a part with no elements adds up to 0 and fails
    for r in doc.plans.get(3, []):
        p = r.get("parent")
        if p in lv:  # an element under a divided section is a format problem of the file
            sums[p] = sums.get(p, 0) + (r.lines or 0)
    for p, s in sums.items():
        want = lv[p].lines or 0
        if s == 0 and want > 0:
            out.append(Failure("length", f"{PLAN_FILE}, elements of {p}", "0 lines",
                               f"{p} has no elements; it is {want:g} lines in the level above"))
        elif _miss(s, want, pct):
            out.append(Failure("length", f"{PLAN_FILE}, elements of {p}", f"{s:g} lines",
                               f"they add up to {s:g} lines; {p} is {want:g} lines ± {pct:g}%"))
    return out
