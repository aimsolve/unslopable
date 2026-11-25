"""fact-quoted (script): every fact of the research's fact base has a saved source, a quote found in that page word
for word and the value's numbers in the quote. `add` refuses such a fact; this gate catches one written into
`research/facts.json` some other way."""
from __future__ import annotations

from pathlib import Path

from common import Failure
from facts import BASE, BaseUnreadable, FactBase


def gate_fact_quoted(folder: Path) -> list[Failure]:
    try:
        base = FactBase(Path(folder)).load()
    except BaseUnreadable as e:
        return [Failure("fact-quoted", str(BASE), "", str(e))]
    out = []
    for f, why in base.failing():
        out.append(Failure("fact-quoted", f"{BASE} {f.get('id', '?') if isinstance(f, dict) else '?'} "
                           f"({f.get('entity', '') if isinstance(f, dict) else ''})",
                           str(f.get("quote", "") if isinstance(f, dict) else f)[:120],
                           f"{why}; a fact enters the base only through `research.py add`"))
    return out
