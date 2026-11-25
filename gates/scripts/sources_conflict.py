"""sources-conflict (script): once FACTS.md is written, the fact base holds one value per attribute of an entity —
the strongest source's; equally strong sources that disagree leave none — and every fact dropped for it is in
FACTS.md with its reason. Code settles the conflicts (`research.py finish`); nothing goes to the author. Before
FACTS.md exists the research is under way and nothing fails."""
from __future__ import annotations

from pathlib import Path

from common import Failure
from facts import BASE, DOSSIER, BaseUnreadable, FactBase, norm


def gate_sources_conflict(folder: Path) -> list[Failure]:
    folder = Path(folder)
    dossier = folder / DOSSIER
    if not dossier.exists():
        return []
    if not (folder / BASE).exists():
        return [Failure("sources-conflict", DOSSIER, "", f"{DOSSIER} exists without a fact base ({BASE}); only "
                        "`research.py finish` writes it")]
    try:
        base = FactBase(folder).load()
    except BaseUnreadable:
        return []  # fact-quoted reports it
    if base.failing():
        return []  # fact-quoted reports those facts; settling waits for a base that holds
    out = []
    for group in base.conflicts():
        f = group[0]
        out.append(Failure("sources-conflict", f"{BASE} {', '.join(g['id'] for g in group)}",
                           "; ".join(f"{g['value']} ({g['source_kind']})" for g in group),
                           f"{f.get('entity')} · {f.get('attribute') or f.get('type')} has {len(group)} different values; run "
                           "`research.py finish` again, it settles them"))
    text = norm(dossier.read_text(encoding="utf-8"))
    for f in base.data["dropped"]:
        if norm(f"{f['id']} {f['entity']}") not in text or norm(f["reason"]) not in text:
            out.append(Failure("sources-conflict", f"{DOSSIER} {f['id']}", f["value"],
                               f"dropped ({f['reason']}) but not listed in {DOSSIER} with its reason; run "
                               "`research.py finish` again"))
    if not out and dossier.read_text(encoding="utf-8") != base.dossier():
        out.append(Failure("sources-conflict", DOSSIER, "",
                           f"{DOSSIER} is not the dossier of the fact base as it stands (facts changed after it was "
                           "written, or it was edited by hand); run `research.py finish` again"))
    return out
