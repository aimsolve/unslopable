"""figure-steps (both): the numbered marks of a drawn figure run 1..N with no gap; the judge matches them to the
steps of the text once the figure's section is complete."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from docs import Doc
from common import Failure
from figure_files import step_number, svg_root, svg_texts, text_figures


def steps(root: ET.Element) -> list[int]:
    return [n for n in (step_number(t) for t in svg_texts(root)) if n is not None]


def gate_figure_steps(doc: Doc) -> list[Failure]:
    """figure-steps, script part: the numbered marks of a drawn figure run 1..N with no gap."""
    out = []
    for i, rel, _ in text_figures(doc):
        if not rel.lower().endswith(".svg"):
            continue
        root, _ = svg_root(doc.folder / rel)
        nums = sorted(set(steps(root))) if root is not None else []
        if nums and nums[0] == 1 and nums != list(range(1, nums[-1] + 1)):
            missing = sorted(set(range(1, nums[-1] + 1)) - set(nums))
            out.append(Failure("figure-steps", f"TEXT.md line {doc.text.blocks[i].line_no} ({rel})", "",
                               f"its numbered marks are {', '.join(map(str, nums))}: "
                               f"{', '.join(map(str, missing))} missing; numbers run 1..N, one per step of the text "
                               "(the figure is redrawn: start the illustrator again)"))
    return out
