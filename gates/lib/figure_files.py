"""Figure files: which file under a document's `figures/` is a figure and of what kind (a drawn `.svg`, a generated
raster with a `.prompt.md` beside it, or a screenshot), which ones a Bash command changed, rendering an SVG for a
judge, reading an SVG's texts, and the document around a figure (its plan element, caption and text before it)."""
from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from docs import Doc, plain


LIB = Path(__file__).resolve().parent
FIG_DIR = "figures"
IMAGE_EXT = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}
SNAPSHOT = "figures.json"
UV_PILLOW = ["uv", "run", "--quiet", "--no-project", "--python", "3.11", "--with", "pillow==11.0.0", "python"]
BIN_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


# ---------------------------------------------------------------- which file is a figure

def figure_file(path: str) -> tuple[Path, str] | None:
    """(document folder, path relative to it) when `path` is an image under the `figures/` of a folder with
    BRIEF.md."""
    p = Path(path)
    if p.suffix.lower() not in IMAGE_EXT:
        return None
    for anc in p.parents:
        if anc.name == FIG_DIR and (anc.parent / "BRIEF.md").exists():
            return anc.parent, p.relative_to(anc.parent).as_posix()
    return None


def prompt_file(folder: Path, rel: str) -> Path:
    return (folder / rel).with_suffix(".prompt.md")


def kind(folder: Path, rel: str) -> str:
    if rel.lower().endswith(".svg"):
        return "diagram"
    return "generated" if prompt_file(folder, rel).exists() else "screenshot"


def _sha(p: Path) -> str:
    try:
        return hashlib.sha1(p.read_bytes()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------- figure files changed by a Bash command

def bash_folders(command: str, cwd: str) -> list[Path]:
    """Document folders a Bash command may have changed figures in: those whose `figures/` a path the command names
    is in (`figures/x.png`, `/doc/figures/*.svg`, `ls figures`). A command that names no such real path changes
    nothing here, whatever its text says. In a here-document's body (data fed to a program, often a script that
    saves an image) only a word shaped like a path into `figures/` counts, never the bare word."""
    if FIG_DIR not in command:
        return []
    shell, bodies = _split_heredocs(command)
    try:
        toks = shlex.split(shell)
    except ValueError:
        toks = shell.split()
    toks = [SHELL_PUNCT.sub("", t.split("=")[-1]).rstrip("<>|&;()") for t in toks if FIG_DIR in t]
    toks += BODY_PATH.findall(bodies)
    env = {**os.environ, "PWD": cwd} if cwd else os.environ
    out: list[Path] = []
    for t in toks:
        folder = _figures_folder(_expand(t, env), cwd)
        if folder and folder not in out:
            out.append(folder)
    return out


HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*\\?(['\"]?)([^\s'\"<>|&;()]+)\1")
BODY_PATH = re.compile(r"[\w./~-]*" + FIG_DIR + r"/[\w./*?-]*")
SHELL_PUNCT = re.compile(r"^[\d<>|&;(]*[<>|&;(]")  # `2>`, `>>`, `&&`, `$(`… glued to the front of a path


def _expand(token: str, env) -> str:
    """`~` and `$VAR` / `${VAR}` of a shell word, `$PWD` as the shell's folder; an unknown variable stays as it is."""
    return os.path.expanduser(re.sub(r"\$\{?(\w+)\}?", lambda m: env.get(m.group(1), m.group(0)), token))


def _split_heredocs(command: str) -> tuple[str, str]:
    """(the shell lines of a command, the bodies of its here-documents). A `<<` whose end word never comes on a line
    of its own is no here-document (a shift, a quoted `<<`): then every line is a shell line."""
    shell, body, ends = [], [], []
    for line in command.split("\n"):
        if ends:
            body.append(line)
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        shell.append(line)
        ends = [m.group(2) for m in HEREDOC.finditer(line)]
    if ends:
        return command, ""
    return "\n".join(shell), "\n".join(body)


def _figures_folder(token: str, cwd: str) -> Path | None:
    """The document folder when `token` is a path inside a real `figures/` of a folder with BRIEF.md, else None.
    The `figures` must be a part of the token itself, not only of the shell's folder (a prose word run inside
    `figures/` is no path). Command text is not a path: a word too long for a file name, or one the system refuses,
    counts as none."""
    parts = Path(token).parts
    base = Path(cwd or ".")
    try:
        for i in range(len(parts) - 1, -1, -1):
            fig = base / Path(*parts[:i + 1])
            if parts[i] == FIG_DIR and fig.is_dir() and (fig.parent / "BRIEF.md").is_file():
                return Path(os.path.realpath(fig.parent))
    except (OSError, ValueError):
        return None
    return None


def _images(folder: Path) -> dict[str, str]:
    root = folder / FIG_DIR
    if not root.is_dir():
        return {}
    return {p.relative_to(folder).as_posix(): _sha(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p.suffix.lower() in IMAGE_EXT}


def changed(folder: Path, gstate) -> list[str]:
    """Figure files new or changed since they last passed their script gates (see `settle`)."""
    old = gstate.read(folder / ".gates" / SNAPSHOT)
    return [r for r, h in _images(folder).items() if old.get(r) != h]


def settle(folder: Path, rel: str, passed: bool, gstate) -> None:
    """Record a figure as seen only once its script gates passed. A figure that failed stays new, so the next shell
    command that names a path in `figures/` gates it again: a raster's fix is often in another file (GATES.md, its prompt
    file), and the same bytes copied again would not count as a change."""
    h = _sha(folder / rel)
    gstate.update(folder / ".gates" / SNAPSHOT,
                  lambda d: d.__setitem__(rel, h) if passed else d.pop(rel, None))


def image_of_prompt(path: str) -> tuple[Path, str] | None:
    """A write of `figures/<name>.prompt.md` is a write of its generated image `figures/<name>.<ext>`."""
    if not path.endswith(".prompt.md"):
        return None
    base = path[:-len(".prompt.md")]
    for ext in sorted(IMAGE_EXT - {".svg"}):
        for cand in (base + ext, base + ext.upper()):
            if os.path.isfile(cand):
                return figure_file(cand)
    return None


# ---------------------------------------------------------------- seeing the image

def _which(name: str) -> str | None:
    return shutil.which(name) or next((f"{d}/{name}" for d in BIN_DIRS if os.access(f"{d}/{name}", os.X_OK)), None)


def render(folder: Path, rel: str) -> Path | None:
    """The image a judge reads: a raster as it is; an SVG rendered to PNG (rsvg-convert, else macOS qlmanage,
    headless both) in `.gates/renders/`, one render per content. None when nothing could render it."""
    src = folder / rel
    if not rel.lower().endswith(".svg"):
        return src
    out_dir = folder / ".gates" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = rel.replace("/", "__")
    out = out_dir / f"{stem}.{_sha(src)[:10]}.png"
    if out.exists():
        return out
    for old in out_dir.glob(f"{stem}.*.png"):
        old.unlink()
    rsvg = _which("rsvg-convert")
    try:
        if rsvg:
            subprocess.run([rsvg, "-z", "2", "-b", "white", "-o", str(out), str(src)], capture_output=True,
                           timeout=60)
        elif _which("qlmanage"):
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run([_which("qlmanage"), "-t", "-s", "1600", "-o", tmp, str(src)], capture_output=True,
                               timeout=60)
                made = Path(tmp) / (src.name + ".png")
                if made.exists():
                    shutil.move(str(made), str(out))
    except (OSError, subprocess.SubprocessError):
        return None
    return out if out.exists() and out.stat().st_size else None


# ---------------------------------------------------------------- reading an SVG

def _local(tag) -> str:
    return tag.split("}")[-1] if isinstance(tag, str) else ""


def svg_root(path: Path) -> tuple[ET.Element | None, str]:
    try:
        return ET.parse(str(path)).getroot(), ""
    except (ET.ParseError, OSError) as e:
        return None, str(e)


def svg_texts(root: ET.Element) -> list[str]:
    """Every `<text>` of the drawing, its tspans joined."""
    out = []
    for el in root.iter():
        if _local(el.tag) == "text":
            t = " ".join("".join(el.itertext()).split())
            if t:
                out.append(t)
    return out


def svg_title(root: ET.Element) -> str:
    for el in root:
        if _local(el.tag) == "title":
            return " ".join("".join(el.itertext()).split())
    return ""


_COLOUR = re.compile(r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b")


def svg_marks(path: Path) -> str:
    src = path.read_text(encoding="utf-8", errors="replace")
    colours = sorted(set(c.upper() for c in _COLOUR.findall(src)))
    dashed = "yes" if "stroke-dasharray" in src else "no"
    return f"colours: {', '.join(colours) or 'none'}; dashed lines: {dashed}"


_CIRCLED = {**{chr(0x2460 + k): k + 1 for k in range(20)}, **{chr(0x2776 + k): k + 1 for k in range(10)},
            **{chr(0x278A + k): k + 1 for k in range(10)}}


def step_number(label: str) -> int | None:
    """A label that is only a step number: 1..99, or a circled digit."""
    s = label.strip().strip("().")
    if re.fullmatch(r"\d{1,2}", s) and 1 <= int(s) <= 20:
        return int(s)
    return _CIRCLED.get(s)


# ---------------------------------------------------------------- the document around a figure

def is_manual(doc: Doc) -> bool | None:
    """GATES.md `manual: yes|no`, set by the gates stage from BRIEF.md's Format (library: the screenshot gates run in
    manuals only). None when it is not set: a search of the Format's words cannot tell «a manual» from «not a
    manual»."""
    v = doc.config.get("manual", "").strip().lower()
    return True if v in ("yes", "true") else False if v in ("no", "false") else None


def plan_element(doc: Doc, rel: str):
    """The plan element that names the figure: by its id (`figures/<id>.svg`), by its file name, or as the `tiles`
    element of the tile whose graphic it is."""
    name, stem = Path(rel).name, Path(rel).stem
    for r in doc.plans.get(3, []):
        if r.id == stem or name in r.get("says") or any(t.id == stem for t in r.tiles):
            return r
    return None


def plan_tile(doc: Doc, rel: str):
    """(the `tiles` element, the tile) whose graphic the file is: `figures/<tile id>.<ext>`; None when no tile."""
    stem = Path(rel).stem
    for r in doc.plans.get(3, []):
        for t in r.tiles:
            if t.id == stem:
                return r, t
    return None


def _tile_line(t) -> str:
    return f"{t.id} «{plain(t.get('title'))}»: {plain(t.get('body'))} — graphic: {plain(t.get('graphic'))}"


def _plan_says(doc: Doc, rel: str) -> str:
    found = plan_tile(doc, rel)
    if found:
        return f"the graphic of tile {_tile_line(found[1])} (in the tiles element {found[0].id})"
    r = plan_element(doc, rel)
    return f"{r.id} ({r.get('kind')}): {plain(r.get('says'))}" if r else "(no element of PLAN.md names this file)"


_IMG = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?")


def text_figures(doc: Doc) -> list[tuple[int, str, str]]:
    """(block index, path relative to the folder, caption) for each figure TEXT.md inserts whose file exists in the
    document folder."""
    out = []
    if doc.text is None:
        return out
    base = Path(os.path.realpath(doc.folder))
    for i, b in enumerate(doc.text.blocks):
        if b.kind != "figure":
            continue
        m = _IMG.search(b.text)
        if not m or re.match(r"[a-z]+://", m.group(2)):
            continue
        p = Path(os.path.realpath(base / os.path.expanduser(m.group(2))))
        if p.is_file() and p.suffix.lower() in IMAGE_EXT and base in p.parents:
            out.append((i, p.relative_to(base).as_posix(), m.group(1).strip()))
    return out


def caption(doc: Doc, rel: str) -> str:
    for _, r, cap in text_figures(doc):
        if r == rel and cap:
            return f"{cap}\n\n(from TEXT.md)"
    for b in (doc.text.blocks if doc.text else []):
        for alt, path in b.graphics:
            if alt and os.path.normpath(path) == os.path.normpath(rel):
                return f"{alt}\n\n(the alt text of a tile's graphic in TEXT.md)"
    if rel.lower().endswith(".svg"):
        root, _ = svg_root(doc.folder / rel)
        t = svg_title(root) if root is not None else ""
        if t:
            return f"{t}\n\n(the SVG's own <title>: the figure is not in TEXT.md yet)"
    return "(none yet: the figure is not in TEXT.md yet)"


def _text_md(doc: Doc, raw: bool = False) -> str:
    try:
        t = (doc.folder / "TEXT.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return t if raw else t.strip()


_MARKER_LINE = re.compile(r"^\s*<!--.*?-->\s*$")


def text_before(doc: Doc, i: int) -> str:
    """TEXT.md above the figure's block, its headings included, without the element markers."""
    lines = _text_md(doc, raw=True).splitlines()[:doc.text.blocks[i].line_no - 1]
    return "\n".join(ln for ln in lines if not _MARKER_LINE.match(ln)).strip()


def _around(doc: Doc, rel: str) -> str:
    """What the elements of the figure's part will say, from the plan: the text after the figure may not be written
    when the figure is, and it may explain the marks."""
    r = plan_element(doc, rel)
    if r is None:
        return "## The elements of the figure's part, from the plan\n\n(no element of PLAN.md names this file)\n"
    rows = [e for e in doc.plans.get(3, []) if e.get("parent") == r.get("parent")]
    return ("## The elements of the figure's part, from the plan (the text after the figure may not be written yet)"
            "\n\n" + "".join(f"- {e.id} ({e.get('kind')}): {plain(e.get('says'))}\n" for e in rows))


def _image_part(folder: Path, rel: str, img: Path | None, title: str = "The figure") -> str:
    sha = _sha(folder / rel)[:12]
    if img is None:
        return (f"## {title}\n\n{folder / rel} (sha1 {sha})\n\nNo PNG could be rendered from this SVG: read its "
                "source and judge the drawing from it.\n")
    src = f"\n\nIts SVG source, for colours and line styles: {folder / rel}" if img != folder / rel else ""
    return f"## {title} (read this image)\n\n{img} (sha1 {sha}){src}\n"
