"""screenshot-margin (both): measures the band of background along each edge of a screenshot; a side thinner than
the least, or no measure, goes to the judge."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from docs import Doc
from judge_gates import JudgeRequest
from figure_files import LIB, UV_PILLOW, _image_part, _sha


MARGIN_MIN_PX = 8        # the least margin, in image pixels (4 screen points on a 2x screenshot)
MARGIN_MIN_SHARE = 0.02  # … or this share of the image's shorter side, when that is more
MARGIN_VERSION = "v3"    # part of the cache key: change it whenever image_margin.py measures differently


def margin_min(width: int, height: int) -> int:
    """The least band of background a screenshot keeps on every side: 2% of its shorter side, at least 8 px."""
    return max(MARGIN_MIN_PX, round(MARGIN_MIN_SHARE * min(width, height)))


def measure_margin(folder: Path, rel: str, notices: list[str]) -> dict | None:
    """The background bands at the four edges of a raster, by image_margin.py under uv (Pillow); cached per content
    in `.gates/margins.json`. None when it could not be measured."""
    image = folder / rel
    cache_file = folder / ".gates" / "margins.json"
    key = f"{MARGIN_VERSION}:{_sha(image)}"
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8")).get(key)
    except (OSError, ValueError, AttributeError):
        cached = None
    if _margin_shape(cached):
        return cached
    try:
        r = subprocess.run(UV_PILLOW + [str(LIB / "image_margin.py"), str(image)], capture_output=True, text=True,
                           timeout=120)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip()[-300:] or f"exit {r.returncode}")
        out = json.loads(r.stdout)
        if not _margin_shape(out):
            raise ValueError(f"unexpected output {r.stdout.strip()[:200]}")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
        notices.append(f"the margin of {rel} could not be measured ({e}); its judge looks at the edges by eye")
        return None
    try:
        old = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
        old[key] = out
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(old), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return out


def _margin_shape(m) -> bool:
    """A measurement as image_margin.py prints it: width, height, background and the four bands."""
    return isinstance(m, dict) and all(isinstance(m.get(k), int) for k in ("width", "height")) and \
        isinstance(m.get("background"), list) and isinstance(m.get("bands"), dict) and \
        all(isinstance(m["bands"].get(s), int) for s in ("top", "right", "bottom", "left"))


def gate_screenshot_margin(doc: Doc, rel: str, notices: list[str]) -> list[JudgeRequest]:
    """screenshot-margin, on every screenshot: a band of even background on every side, so no content
    touches or is cut at an edge of the image. A script measures the bands; when every side has at least
    `margin_min`, the gate passes. Otherwise (a side too thin, or nothing measured) a judge looks at the image."""
    m = measure_margin(doc.folder, rel, notices)
    if m:
        need = margin_min(m["width"], m["height"])
        if all(v >= need for v in m["bands"].values()):
            return []
        bands = ", ".join(f"{side} {m['bands'][side]} px" for side in ("top", "right", "bottom", "left"))
        found = (f"The image is {m['width']}×{m['height']} px. Its background colour, taken from its outermost "
                 f"pixels, is RGB {tuple(m['background'])}. The band of that colour along each edge: {bands}. The "
                 f"least band this gate asks for is {need} px. A band thinner than that is where a script saw "
                 "something other than background close to the edge: content, a bar of another colour, a frame or "
                 "a shadow, or noise. Look at those edges.")
    else:
        found = "No script could measure the edges: look at all four of them."
    image = _image_part(doc.folder, rel, doc.folder / rel, "The screenshot")
    return [JudgeRequest("screenshot-margin", rel, f"{image}\n## What a script measured at its edges\n\n{found}\n")]
