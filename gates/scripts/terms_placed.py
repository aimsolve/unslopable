"""terms-placed (script): every explain term is named in `explains:` of exactly one plan element."""
from __future__ import annotations

from docs import Doc, PLAN_FILE
from common import Failure, plan_explains


def gate_terms_placed(doc: Doc) -> list[Failure]:
    """Plan level 3: every `explain` term of TERMS.md is named in `explains:` of exactly one element."""
    out: list[Failure] = []
    where_: dict[str, list[str]] = {}
    for r in doc.plans.get(3, []):
        for t in plan_explains(r):
            where_.setdefault(t.lower(), []).append(r.id)
    for term, mark in doc.terms.items():
        if mark != "explain":
            continue
        els = where_.get(term.lower(), [])
        if not els:
            out.append(Failure("terms-placed", PLAN_FILE, term,
                               f"no element explains «{term}» (an `explain` term of TERMS.md); add `; explains: "
                               f"{term}` to the third field of the element where the reader first meets it"))
        elif len(els) > 1:
            out.append(Failure("terms-placed", f"{PLAN_FILE} {', '.join(els)}", term,
                               f"«{term}» is explained in {len(els)} elements; keep it in one, the element where the "
                               "reader first meets it"))
    return out
