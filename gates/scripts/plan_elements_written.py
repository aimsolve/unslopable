"""plan-elements-written (script): every plan element up to the last one written is in TEXT.md, by its id marker."""
from __future__ import annotations

from docs import Doc, PLAN_FILE
from common import Failure


NOT_WRITTEN_YET = "not written yet"


def gate_plan_elements_written(doc: Doc, notices: list[str]) -> list[Failure]:
    """Every element of the plan is in the text. The writer writes element by element in the plan's order and the
    gates run after every write, so only an element before the last one written fails: it was skipped. The elements
    after it are not written yet; a note names them until they are, and the hook does not call the text done."""
    order = [r.id for r in doc.plans.get(3, [])]
    written = {b.element for b in doc.text.blocks if b.element}
    idx = [i for i, rid in enumerate(order) if rid in written]
    if not idx:
        return []
    last = max(idx)
    out = [Failure("plan-element-missing", f"TEXT.md element {rid}", rid,
                   f"this element of {PLAN_FILE} is missing from the text, and "
                   f"{next(o for o in order[i + 1:] if o in written)}, which comes after it, is written; write it in "
                   "its place, in the plan's order")
           for i, rid in enumerate(order[:last]) if rid not in written]
    rest = order[last + 1:]
    if rest:
        notices.append(f"{len(rest)} element{'s' if len(rest) > 1 else ''} of {PLAN_FILE} {NOT_WRITTEN_YET} "
                       f"(next: {rest[0]}); the text is done only when every element is in it")
    return out
