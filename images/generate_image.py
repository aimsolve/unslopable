#!/usr/bin/env python3
"""Make one picture with Google's Gemini image model, for the image generator agent (agents/image-generator.md).

    python3 generate_image.py --folder <document folder> --prompt-file <N.prompt.md> --out <N.png> [--aspect 16:9]

The prompt file has the sections the generated-image gate reads: `## Prompt` (what the picture shows), `## Style`
(its look) and `## References` (one path per line, relative to the document folder, or none). The references go to
the model as pictures before the text. The picture is written to `--out`, its extension changed to the format the
model returned (`.png` or `.jpg`); the script prints the path it wrote, or `ERROR: …` and exits 1.

Configuration comes from the environment, never from this file: the key from GEMINI_API_KEY, else GOOGLE_API_KEY;
the model from UNSLOPABLE_IMAGE_MODEL. The key goes in a request header, never in a URL or an error message.
Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import http.client
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-nano-banana-2.1"
KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
TIMEOUT = 240
RETRY_PAUSE = 10.0
NO_REFERENCES = ("none", "(none)", "—", "-")  # the same words the generated-image gate skips


class ImageError(RuntimeError):
    pass


def sections(text: str) -> dict[str, str]:
    """`## Name` sections of a markdown file, keys lower case."""
    out: dict[str, str] = {}
    name = None
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            name = m.group(1).strip().lower()
            out[name] = ""
        elif name is not None:
            out[name] += line + "\n"
    return {k: v.strip() for k, v in out.items()}


def read_prompt_file(path: Path) -> tuple[str, str, list[str]]:
    """(prompt, style, reference paths) of a prompt file, in the form the generated-image gate reads."""
    secs = sections(path.read_text(encoding="utf-8"))
    refs_txt = next((v for k, v in secs.items() if k.startswith("reference")), "")
    refs = []
    for line in refs_txt.splitlines():
        s = line.strip().lstrip("-*+ ").strip()
        m = re.search(r"`([^`]+)`", s)
        s = m.group(1) if m else s
        if s and s.lower() not in NO_REFERENCES:
            refs.append(s)
    return secs.get("prompt", ""), secs.get("style", ""), refs


def api_key() -> str:
    for var in KEY_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            return value
    raise ImageError(f"no key for the image model: set {' or '.join(KEY_VARS)} in the environment")


def model() -> str:
    return os.environ.get("UNSLOPABLE_IMAGE_MODEL", "").strip() or DEFAULT_MODEL


def request_body(prompt: str, style: str, refs: list[tuple[bytes, str]], aspect: str) -> dict:
    text = prompt if not style else f"{prompt}\n\nStyle: {style}"
    parts = [{"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}} for data, mime in refs]
    parts.append({"text": text})
    return {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}


def post(url: str, body: dict, key: str) -> tuple[int, bytes]:
    """One HTTP call; the only place that talks to the network (tests replace it)."""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _picture(raw: bytes) -> tuple[bytes, str] | str:
    """(image bytes, mime) from the model's answer, or why there is none."""
    try:
        data = json.loads(raw)
    except ValueError:
        return "the image model answered with no JSON"
    if not isinstance(data, dict):
        return "the image model answered with something other than a JSON object"
    cands = data.get("candidates") or []
    for cand in cands if isinstance(cands, list) else []:
        for part in ((cand or {}).get("content") or {}).get("parts") or []:
            inline = (part or {}).get("inlineData") or {}
            if inline.get("data"):
                try:
                    return base64.b64decode(inline["data"], validate=True), inline.get("mimeType") or "image/png"
                except (binascii.Error, ValueError):
                    return "the image model's picture is not valid base64"
    reason = cands[0].get("finishReason") if cands and isinstance(cands[0], dict) else None
    block = (data.get("promptFeedback") or {}).get("blockReason")
    why = ", ".join(f"{k} {v}" for k, v in (("finish reason", reason), ("block reason", block)) if v)
    return "the image model returned no picture" + (f" ({why}): change the prompt" if why else "")


def generate(prompt: str, style: str, refs: list[tuple[bytes, str]], aspect: str) -> tuple[bytes, str]:
    """(image bytes, mime) for one prompt. A network error, 429 or 5xx is tried once more after a pause; a refusal
    or another 4xx is not, since the same request would fail the same way."""
    key = api_key()
    body = request_body(prompt, style, refs, aspect)
    error = ""
    for attempt in (1, 2):
        if attempt == 2:
            time.sleep(RETRY_PAUSE)
        try:
            status, raw = post(API.format(model=model()), body, key)
        except (OSError, http.client.HTTPException, ValueError) as e:
            error = f"the request failed ({type(e).__name__})"
            continue
        if status == 200:
            got = _picture(raw)
            if isinstance(got, tuple):
                return got
            error = got
            break
        error = f"the image model answered {status}: {raw[:300].decode('utf-8', 'replace')}"
        if status != 429 and status < 500:
            break
    raise ImageError(error.replace(key, "<key>"))


def load_refs(folder: Path, refs: list[str]) -> list[tuple[bytes, str]]:
    out = []
    for ref in refs:
        p = Path(os.path.expanduser(ref))
        p = p if p.is_absolute() else folder / p
        if not p.is_file():
            raise ImageError(f"the reference {ref} does not exist (paths are relative to the document folder)")
        mime = mimetypes.guess_type(p.name)[0] or ""
        if not mime.startswith("image/"):
            raise ImageError(f"the reference {ref} is not an image")
        out.append((p.read_bytes(), mime))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--folder", required=True, type=Path, help="the document folder")
    ap.add_argument("--prompt-file", required=True, type=Path, help="the attempt's prompt file")
    ap.add_argument("--out", required=True, type=Path, help="where to write the picture")
    ap.add_argument("--aspect", default="16:9", choices=ASPECTS, help="width to height, 16:9 when not given")
    a = ap.parse_args(argv)
    folder = a.folder.expanduser().resolve()
    pf = a.prompt_file if a.prompt_file.is_absolute() else folder / a.prompt_file
    out = a.out if a.out.is_absolute() else folder / a.out
    try:
        if not pf.is_file():
            raise ImageError(f"no prompt file {pf}")
        prompt, style, refs = read_prompt_file(pf)
        if not prompt:
            raise ImageError(f"{pf.name} has no `## Prompt` section")
        data, mime = generate(prompt, style, load_refs(folder, refs), a.aspect)
        out = out.with_suffix(EXT.get(mime, out.suffix or ".png"))
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
        except OSError as e:
            raise ImageError(f"could not write {out} ({e.strerror or type(e).__name__})")
    except ImageError as e:
        print(f"ERROR: {e}")
        return 1
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
