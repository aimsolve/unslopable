"""fact-one-place (script): on plan level 3, a fact number appears in one element only; a summary may repeat it."""
from __future__ import annotations

import re

from docs import Doc, PLAN_FILE, plain
from common import Failure


_FACT = re.compile(r"\b[A-Za-z]{0,3}\d+[a-z]?\b")


def gate_fact_one_place(doc: Doc) -> list[Failure]:
    seen: dict[str, list[str]] = {}
    for r in doc.plans.get(3, []):
        if "summary" in r.get("kind").lower():
            continue
        # only fact numbers count; file names of a knowledge base (with a dot or a slash) may repeat
        ids = [t.strip() for t in plain(r.get("facts")).split(",") if t.strip() and not re.search(r"[./]", t)]
        for f in set(x for t in ids for x in _FACT.findall(t)):
            seen.setdefault(f, []).append(r.id)
    return [Failure("fact-one-place", f"{PLAN_FILE} " + ", ".join(ids), f,
                    f"fact {f} is in {len(ids)} elements; each fact is in one place (only an element whose kind is "
                    "`summary` may repeat facts)")
            for f, ids in sorted(seen.items()) if len(ids) > 1]
