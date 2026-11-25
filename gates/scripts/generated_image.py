"""generated-image (both): the image's prompt file `figures/<name>.prompt.md` has a prompt and its references exist;
a similarity to each reference is measured for the judge."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from docs import Doc, md_sections
from common import Failure
from figure_files import LIB, UV_PILLOW, _sha, plan_element, prompt_file


NO_REFERENCES = ("none", "(none)", "—", "-")  # the same words images/generate_image.py skips


def prompt_parts(folder: Path, rel: str) -> tuple[str, str, list[str]]:
    """(prompt, style, reference paths) from the figure's prompt file."""
    pf = prompt_file(folder, rel)
    secs = md_sections(pf.read_text(encoding="utf-8")) if pf.exists() else {}
    refs_txt = next((v for k, v in secs.items() if k.startswith("reference")), "")
    refs = []
    for line in refs_txt.splitlines():
        s = line.strip().lstrip("-*+ ").strip()
        m = re.search(r"`([^`]+)`", s)
        s = m.group(1) if m else s
        if s and s.lower() not in NO_REFERENCES:
            refs.append(s)
    return secs.get("prompt", "").strip(), secs.get("style", "").strip(), refs


def _ref_path(folder: Path, ref: str) -> Path:
    p = Path(os.path.expanduser(ref))
    return p if p.is_absolute() else folder / p


def similarity(image: Path, refs: list[Path], notices: list[str]) -> dict[str, float]:
    """How alike the image and each reference are, 0..1 (difference hash, 1 = the same picture), by
    image_similarity.py under uv (Pillow)."""
    if not refs:
        return {}
    cache_file = image.parent
    while cache_file != cache_file.parent and not (cache_file / "BRIEF.md").exists():
        cache_file = cache_file.parent
    cache_file = cache_file / ".gates" / "similarity.json"
    key = _sha(image) + ":" + ":".join(_sha(p) for p in refs)
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError):
        cached = None
    if isinstance(cached, dict):
        return cached
    try:
        r = subprocess.run(UV_PILLOW + [str(LIB / "image_similarity.py"), str(image)] + [str(p) for p in refs],
                           capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-300:] or f"exit {r.returncode}")
        out = json.loads(r.stdout)
        try:
            old = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
            old[key] = out
            cache_file.write_text(json.dumps(old), encoding="utf-8")
        except (OSError, ValueError):
            pass
        return out
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        notices.append(f"the similarity of {image.name} to its references could not be measured ({e}); the judge "
                       "compares them by eye")
        return {}


def gate_generated_script(doc: Doc, rel: str) -> list[Failure]:
    folder, out = doc.folder, []
    pf = prompt_file(folder, rel)
    if not pf.exists():
        r = plan_element(doc, rel)
        if r is not None and re.search(r"generat", r.get("kind"), re.I) or \
                r is not None and re.search(r"\bgenerated (?:image|picture|illustration)|\bimage to generate",
                                            r.get("says"), re.I):
            out.append(Failure("generated-image", rel, "", f"plan element {r.id} makes this a generated image, but "
                               f"{pf.relative_to(folder).as_posix()} is missing: write the prompt, the style and the "
                               "references (`## Prompt`, `## Style`, `## References`) the image was made from"))
        return out
    prompt, _, refs = prompt_parts(folder, rel)
    if not prompt:
        out.append(Failure("generated-image", pf.relative_to(folder).as_posix(), "",
                           "has no `## Prompt` section with the prompt the image was made from"))
    for ref in refs:
        if not _ref_path(folder, ref).is_file():
            out.append(Failure("generated-image", pf.relative_to(folder).as_posix(), ref,
                               "names a reference image that does not exist"))
    return out
