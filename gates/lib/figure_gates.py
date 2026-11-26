"""The gates of figure files and of figures in the text: `run_figure` runs a figure file's scripts and builds its
judges (figure-marks, screenshot-margin, screenshot-cropped in manuals, tile-graphic, generated-image);
`custom_figure_gates` runs a document's own gates on figure files; `text_requests` builds the judges of
figure-labels and figure-steps on TEXT.md. A judge sees the image itself: a raster as it is, an SVG rendered to PNG."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from docs import Doc, brief_part, plain
from judge_gates import JudgeRequest, complete, section_text, sections
from common import Failure, run_gate_script
from figure_files import FIG_DIR, IMAGE_EXT, _around, _image_part, _plan_says, _sha, _text_md, _tile_line, caption, is_manual, kind, plan_tile, prompt_file, render, svg_marks, svg_root, text_before, text_figures
from figure_labels import _norm, label_in, labels
from figure_steps import steps
from generated_image import _ref_path, gate_generated_script, prompt_parts, similarity
from screenshot_margin import gate_screenshot_margin


def run_figure(doc: Doc, rel: str, notices: list[str]) -> tuple[list[Failure], list[JudgeRequest]]:
    """The gates of one figure file: script failures, then the judges (asked for only when the scripts pass)."""
    folder, k = doc.folder, kind(doc.folder, rel)
    fails: list[Failure] = []
    if k == "diagram":
        root, err = svg_root(folder / rel)
        if root is None:
            return [Failure("format", rel, "", f"the SVG does not parse ({err}); write it as valid SVG")], []
    else:
        fails += gate_generated_script(doc, rel)
    if k == "screenshot" and is_manual(doc) is None:
        fails.append(Failure("config", "GATES.md", "", "has no `manual: yes|no`, so the screenshot gates (cropped, "
                             "margin) cannot run. Whoever writes the document's gates sets it from BRIEF.md's Format, yes when the "
                             "document is a manual (in this run: you); then run `ls figures` and the figure's gates "
                             "run again"))
    if fails:
        return fails, []
    img = render(folder, rel)
    if img is None:
        notices.append(f"{rel} could not be rendered to PNG (no rsvg-convert or qlmanage); its judges read the SVG")
    image = _image_part(folder, rel, img)
    says = f"## What the plan says the figure shows\n\n{_plan_says(doc, rel)}\n"
    if plan_tile(doc, rel):
        says += ("\nThis figure is a tile's graphic: a small illustration of one thing. A colour that only depicts "
                 "the thing (a green hose, a red apple) is part of the drawing, not a mark.\n")
    marks = f"\n## Marks a script found in the SVG\n\n{svg_marks(folder / rel)}\n" if k == "diagram" else ""
    text = _text_md(doc) or "(no text written yet)"
    reqs = [JudgeRequest("figure-marks", rel, f"{image}\n{says}\n## Its caption\n\n{caption(doc, rel)}\n{marks}\n"
                                              f"{_around(doc, rel)}\n"
                                              f"## The text of the document so far (TEXT.md)\n\n{text}\n")]
    if k == "screenshot":
        reqs += gate_screenshot_margin(doc, rel, notices)
    found = plan_tile(doc, rel)
    if found:
        el, tile = found
        others = ""
        for t in el.tiles:
            if t is tile:
                continue
            drawn = next((f"{FIG_DIR}/{t.id}{e}" for e in sorted(IMAGE_EXT)
                          if (folder / FIG_DIR / f"{t.id}{e}").is_file()), "")
            seen = render(folder, drawn) if drawn else None
            others += f"- {_tile_line(t)}\n  " + (f"its graphic, drawn already (read this image): "
                                                    f"{seen or folder / drawn}\n" if drawn else
                                                    "its graphic: not drawn yet\n")
        others = others or "(none)\n"
        reqs.append(JudgeRequest("tile-graphic", rel,
                                 f"{_image_part(folder, rel, img, 'The graphic')}\n"
                                 f"## The tile it is for (from PLAN.md)\n\n{_tile_line(tile)}\n\n"
                                 f"## The other tiles of the same element ({el.id}: {plain(el.get('says'))})\n\n"
                                 f"{others}"))
    if k == "screenshot" and is_manual(doc):
        reqs.append(JudgeRequest("screenshot-cropped", rel, f"{_image_part(folder, rel, img, 'The screenshot')}\n"
                                                            f"{says}"))
    if k == "generated":
        prompt, style, refs = prompt_parts(folder, rel)
        paths = [_ref_path(folder, r) for r in refs]
        sim = similarity(folder / rel, paths, notices)
        ref_lines = "".join(
            f"- {p} (sha1 {_sha(p)[:12]}) — similarity to the generated image, measured by a script: "
            + (f"{sim[str(p)]:.2f}" if str(p) in sim else "not measured") + "\n" for p in paths) or \
            "(none: the image was made without a reference)\n"
        brand = brief_part(doc.brief, "language").strip() or "(BRIEF.md has no Language, brand, author section)"
        reqs.append(JudgeRequest("generated-image", rel,
                                 f"{_image_part(folder, rel, img, 'The generated image')}\n{says}\n"
                                 f"## Its prompt (from {prompt_file(folder, rel).name})\n\n{prompt}\n\n"
                                 f"## Its style (from the prompt file)\n\n{style or '(not given)'}\n\n"
                                 f"## The document's language and brand (from BRIEF.md)\n\n{brand}\n\n"
                                 "## Its references (read each image; similarity 1 = the same picture, two unrelated "
                                 f"pictures score about 0.5)\n\n{ref_lines}"))
    return fails, reqs


def _targets(first_line: str, rel: str) -> bool:
    """A document's own gate whose first line names `figures/…` (and not PLAN.md or TEXT.md) checks figure files
    that match: `figures/` alone matches every figure, `figures/*.svg` the drawn ones, and so on."""
    if "PLAN.md" in first_line or "TEXT.md" in first_line:
        return False
    for tok in re.findall(r"(?<![\w/])figures(?:/[^\s,;:)]*)?", first_line):
        tok = tok.rstrip(".")
        if tok in ("figures", "figures/") or (tok.endswith("/") and rel.startswith(tok)) or \
                fnmatch.fnmatch(rel, tok):
            return True
    return False


def custom_figure_gates(folder: Path, rel: str) -> tuple[list[Failure], list[JudgeRequest]]:
    """The document's own gates on a figure file: `.gates/custom/<gate>.py` whose first line names `figures/…`, run
    as `python3 <script> <folder> <figure file>`; one stdout line per place, no output = passed. A `CHECK:` line goes
    to judge gate-custom with the rule from `<gate>.md` and the image to read."""
    fails, reqs = [], []
    for script in sorted((folder / ".gates" / "custom").glob("*.py")):
        try:
            first = (script.read_text(encoding="utf-8").splitlines() or [""])[0]
        except OSError:
            continue
        if not _targets(first, rel):
            continue
        gate = f"custom:{script.stem}"
        lines, checks = run_gate_script(script, [str(folder), str(folder / rel)])
        fails += [Failure(gate, rel, "", ln) for ln in lines]
        if not checks:
            continue
        rule_file = script.with_suffix(".md")
        rule = rule_file.read_text(encoding="utf-8").strip() if rule_file.exists() else ""
        if not rule:
            fails.append(Failure(gate, rel, "", f"the script printed CHECK lines but {rule_file.name} (the judge's "
                                 "rule) is missing or empty; write it next to the script"))
            continue
        places = "".join(f"- {c}\n" for c in checks)
        reqs.append(JudgeRequest("custom", f"{rel} · {script.stem}",
                                 f"## The rule of this gate (from {rule_file})\n\n{rule}\n\n"
                                 f"{_image_part(folder, rel, render(folder, rel), 'The file checked')}\n"
                                 f"## The places a script found\n\n{places}"))
    return fails, reqs


def text_requests(doc: Doc) -> list[JudgeRequest]:
    """figure-steps and figure-labels, judge parts: one judge per figure and gate."""
    out = []
    secs = sections(doc)
    sec_of = {i: (sid, idx) for sid, idx in secs for i in idx}
    for i, rel, _ in text_figures(doc):
        b = doc.text.blocks[i]
        unit = f"figure {rel} (TEXT.md line {b.line_no})"
        img = render(doc.folder, rel)
        image = _image_part(doc.folder, rel, img)
        before = text_before(doc, i)
        root = svg_root(doc.folder / rel)[0] if rel.lower().endswith(".svg") else None
        if rel.lower().endswith(".svg") and root is None:
            continue  # its own file gate fails it
        # every label appears in the text before the figure
        if root is not None:
            norm = _norm(before)
            missing = [lb for lb in labels(root) if not label_in(lb, norm)]
            if missing:
                out.append(JudgeRequest("figure-labels", unit,
                                        f"{image}\n## Labels a script did not find word for word in the text before "
                                        "the figure\n\n" + "".join(f"- «{m}»\n" for m in missing) +
                                        f"\n## The text before the figure\n\n{before or '(none)'}\n"))
        else:
            out.append(JudgeRequest("figure-labels", unit,
                                    f"{image}\n## Labels\n\nA raster image: no script reads its labels. Find the "
                                    "labels someone put on it (callouts, names of parts, words on arrows); the text "
                                    "of an application a screenshot shows is not a label.\n\n"
                                    f"## The text before the figure\n\n{before or '(none)'}\n"))
        # numbered arrows match the steps of the text: once the figure's section is complete
        sid, idx = sec_of.get(i, ("", []))
        if not sid or not complete(doc, sid):
            continue
        if root is not None:
            nums = sorted(set(steps(root)))
            if not nums:
                continue
            found = f"## Numbered marks a script read on the figure\n\n{', '.join(map(str, nums))}\n"
        else:
            found = ("## Numbered marks\n\nA raster image: no script reads its numbers. Look for numbered arrows or "
                     "marks on it; when it has none, the gate passes.\n")
        out.append(JudgeRequest("figure-steps", unit, f"{image}\n{found}\n## The section the figure is in "
                                                      f"(TEXT.md)\n\n{section_text(doc, sid, idx)}"))
    return out
