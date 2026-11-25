"""figure-labels (both): reads the labels of a drawn figure (SVG) and looks for each in the text before the figure;
the labels not found word for word go to the judge (built in figure_gates.text_requests)."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from docs import plain
from figure_files import step_number, svg_texts


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", plain(s).lower()))


def label_in(label: str, text_norm: str) -> bool:
    """The label's words, in order, in the text; a plural or singular form of a word counts."""
    ws = _norm(label).split()
    if not ws:
        return True
    pat = r"\s+".join(re.escape(w[:-1] if len(w) > 3 and w.endswith("s") else w) + r"(?:s|es)?" for w in ws)
    return re.search(rf"(?<!\w){pat}(?!\w)", text_norm) is not None


def labels(root: ET.Element) -> list[str]:
    """The drawing's labels that carry words (step numbers and bare symbols left out), once each."""
    out = []
    for t in svg_texts(root):
        if step_number(t) is None and re.search(r"[^\W\d_]", t) and t not in out:
            out.append(t)
    return out
