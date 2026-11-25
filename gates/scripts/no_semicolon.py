"""no-semicolon (script): no semicolons in the text."""
from __future__ import annotations

from docs import Doc
from common import Failure, _CODE, _ENTITY, _cut, body_units, where


def gate_semicolons(doc: Doc) -> list[Failure]:
    out = []
    for u in body_units(doc.text.blocks):
        t = _CODE.sub("", _ENTITY.sub("", u.text))
        if ";" in t:
            out.append(Failure("no-semicolon", where(u, doc.text.blocks), _cut(u.text), "has a semicolon"))
    return out
