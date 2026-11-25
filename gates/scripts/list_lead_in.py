"""list-lead-in (both): a list, tiles, a table or a yes/no block has a paragraph right before it; the judge decides
whether that paragraph says what follows and why."""
from __future__ import annotations

from docs import Doc
from common import ENUMERATION_KINDS, Failure, block_name


def list_lead_ins(doc: Doc) -> list[tuple[int, int | None]]:
    """Every list, tiles, table or yes/no block of the text with the paragraph right before it: [(block index,
    paragraph index or None)]. None when no paragraph stands right before it — a heading, a figure, a callout,
    another enumeration, or nothing."""
    blocks, heads = doc.text.blocks, doc.text.headings
    out = []
    for i, b in enumerate(blocks):
        if b.kind not in ENUMERATION_KINDS or not b.element:
            continue
        prev = i - 1 if i > 0 else None
        if prev is not None:
            between = any(blocks[prev].line_no < ln < b.line_no for _, _, ln in heads)
            if between or blocks[prev].kind != "paragraph":
                prev = None
        out.append((i, prev))
    return out


def gate_list_lead_in(doc: Doc) -> list[Failure]:
    """An enumeration (a list, tiles, a table or a yes/no block) is led in: a paragraph stands right
    before it. Whether that paragraph announces what follows and why is the judge's part (`gate-list-lead-in`)."""
    out = []
    for i, prev in list_lead_ins(doc):
        if prev is None:
            b = doc.text.blocks[i]
            what = block_name(b)
            out.append(Failure("list-lead-in", f"TEXT.md line {b.line_no} ({b.element}, {what})", "",
                               f"the {what} starts with no lead-in: write a sentence right before it that says what "
                               "follows and why — the last sentence of the paragraph before, or a short paragraph "
                               f"under the same element marker, above the {what}"))
    return out
