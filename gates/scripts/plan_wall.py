"""plan-wall (script): on plan level 3, paragraph elements in a row add up to at most `plain_text_max_lines`."""
from __future__ import annotations

import re

from docs import Doc, PLAN_FILE, canon_kind
from common import Failure, _num


PLAIN_TEXT_MAX_LINES = 10  # GATES.md `plain_text_max_lines` changes it (set from the brief)
# the visual elements of the library (elements/library.md) break a run of plain text; a summary and a FAQ do not.
# A kind breaks a run when it has one of these words: «bulleted_list», «comparison table», «steps vertical» too
_BREAK_WORD = re.compile(r"\b(?:lists?|tiles?|tables?|figures?|callouts?|screenshots?|diagrams?|images?|charts?|"
                         r"generated|yes-no|steps?|stats?|pull-quotes?|definitions?)\b")


def wall_role(kind: str) -> str:
    """'adds' for a plain paragraph, 'breaks' for an element that ends a run of plain text, '' for any other kind."""
    k = canon_kind(kind)
    if k == "paragraph":
        return "adds"
    if _BREAK_WORD.search(k):
        return "breaks"
    return ""


def gate_plan_wall(doc: Doc) -> list[Failure]:
    """Plan level 3: no wall of plain text. The `lines` of consecutive `paragraph` elements add up; a
    visual element of the library (a list, tiles, a table, a diagram, a screenshot, a chart, a callout, a yes/no
    block, steps, a stat, a pull quote, a definition) or a heading (a new section or subsection) starts the count
    again; any other kind (a summary, a FAQ) neither adds nor starts it again. The paragraph on which the sum
    goes over the limit is allowed, a single long paragraph included; the plan breaks the run right after it, so a
    paragraph that comes when the run is already over the limit fails."""
    out: list[Failure] = []
    if "plain_text_max_lines" in doc.config and not re.search(r"\d", doc.config["plain_text_max_lines"]):
        return [Failure("config", "GATES.md", doc.config["plain_text_max_lines"],
                        "`plain_text_max_lines:` has no number, so gate plain-text-wall cannot run: write the number "
                        "of lines, or remove the line for the default 10")]
    limit = _num(doc, "plain_text_max_lines", "plain-text-wall", out, default=PLAIN_TEXT_MAX_LINES)
    run: list = []        # the paragraphs of the current run
    parent = None
    for r in doc.plans.get(3, []):
        if r.get("parent") != parent:
            parent, run = r.get("parent"), []
        role = wall_role(r.get("kind"))
        if role == "breaks":
            run = []
            continue
        if role != "adds":
            continue
        total = sum(x.lines or 0 for x in run)
        if total > limit:
            span = f"{run[0].id} to {run[-1].id}" if len(run) > 1 else run[0].id
            out.append(Failure(
                "plain-text-wall", f"{PLAN_FILE} {r.id}", f"{total:g} lines",
                f"plain paragraphs {span} already run {total:g} lines, more than {limit:g} (GATES.md "
                f"plain_text_max_lines, {PLAIN_TEXT_MAX_LINES} when absent), and {r.id} is one more paragraph: right "
                f"after {run[-1].id}, put an element of the library that breaks plain text (a list, a table, a "
                "diagram, steps, a stat, a callout, …), or start a new subsection there"))
            run = []      # one failure per place to break; the count starts again from this paragraph
        run.append(r)
    return out
