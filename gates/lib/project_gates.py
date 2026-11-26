"""A project's own gate library: the gates a project adds to the plugin's, in the plugin's own layout.

The library is the folder `.unslopable/gates/` of the project, laid out as the plugin's `gates/`:

    library.md         the table of its gates, the columns of gates/library.md (Gate, What it checks, Default,
                       Script, Judge, Idea) and the same Default values
    scripts/<x>.py     script gates; the first line names the file checked (PLAN.md, TEXT.md, figures/…)
    judges/gate-<x>.md judge prompts, run by the plugin's generic judge `unslopable:gate-project`
    ideas/<x>.md       ideas (Default `per document`): the gates stage writes a document's own script from each
    lib/               shared code, on the scripts' PYTHONPATH
    data/              data files the scripts and judges read

It is found from the document folder: the nearest folder, that one or one above it, that holds
`.unslopable/gates/library.md`; when none does, `$CLAUDE_PROJECT_DIR/.unslopable/gates/`. Only that one library
counts. A document with no library runs the plugin's gates only.

A script gate runs as a document's own gates do (`.gates/custom/`): `python3 <script> <document folder>` (on a
figure: `… <figure file>`), one stdout line per place, no output = passed; a `CHECK:` line is a place for the gate's
judge. The project cannot register a subagent with the plugin, so its judge prompt goes into the judge's input and
the plugin's generic judge `unslopable:gate-project` follows it. A judge's places come from its script's CHECK lines,
so a judge gate has a script.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from common import _LIBRARY_NAME, Failure, gates_off, gates_on, library_gates, run_gate_script

LIBRARY_DIR = Path(".unslopable") / "gates"
DEFAULTS = ("on", "off", "manuals", "per document", "not built yet")
AGENT = "unslopable:gate-project"
PLUGIN_LIB = Path(__file__).resolve().parent
_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LINK = re.compile(r"\]\(([^)]+)\)")
_FRONTMATTER = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
# names the gate code gives its own failures: a project gate with one could not be switched off by its name
RESERVED = {"config", "format", "length", "custom"} | set(_LIBRARY_NAME)


@dataclass
class ProjectGate:
    name: str
    default: str
    script: Path | None
    judge: Path | None
    idea: Path | None


def library_dir(folder: Path) -> Path | None:
    """The project's gate library for a document folder, or None."""
    folder = Path(folder).resolve()
    for d in (folder, *folder.parents):
        if (d / LIBRARY_DIR / "library.md").is_file():
            return d / LIBRARY_DIR
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and (Path(env) / LIBRARY_DIR / "library.md").is_file():
        return Path(env).resolve() / LIBRARY_DIR
    return None


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _link(lib: Path, cell: str, problems: list[str], name: str, column: str) -> Path | None:
    m = _LINK.search(cell)
    if not m:
        if cell.strip():
            problems.append(f"gate «{name}»: its {column} cell has no link `[{column.lower()}](<path>)`")
        return None
    p = (lib / m.group(1)).resolve()
    if not p.is_file():
        problems.append(f"gate «{name}»: its {column.lower()} {m.group(1)} does not exist in {lib}")
        return None
    return p


def first_line(script: Path) -> str:
    try:
        return (script.read_text(encoding="utf-8").splitlines() or [""])[0]
    except OSError:
        return ""


def read_library(lib: Path) -> tuple[list[ProjectGate], list[str]]:
    """The gates of a project's library.md and what is wrong with it (each problem fails as `config`)."""
    try:
        text = (lib / "library.md").read_text(encoding="utf-8")
    except OSError as e:
        return [], [f"cannot be read ({e})"]
    plugin = set(library_gates())
    gates, problems, seen = [], [], set()
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if not cells or cells[0].lower() == "gate" or set("".join(cells)) <= set("-: "):
            continue  # a header or the line under it
        name = cells[0].strip("`")
        if len(cells) != 6:
            problems.append(f"the row «{name}» has {len(cells)} cells, not the 6 columns Gate | What it checks | "
                            "Default | Script | Judge | Idea")
            continue
        if not _NAME.match(name):
            problems.append(f"gate «{name}»: a gate's name is lower-case words joined by `-`, as in the plugin")
            continue
        if name in plugin or name in RESERVED:
            problems.append(f"gate «{name}» has the name of a gate of the plugin; give it another name")
            continue
        if name in seen:
            problems.append(f"gate «{name}» is in the table twice")
            continue
        seen.add(name)
        default = cells[2].strip("`").lower()
        if default not in DEFAULTS:
            problems.append(f"gate «{name}»: Default «{cells[2]}» is none of {', '.join(DEFAULTS)}")
            continue
        script = _link(lib, cells[3], problems, name, "Script")
        judge = _link(lib, cells[4], problems, name, "Judge")
        idea = _link(lib, cells[5], problems, name, "Idea")
        g = ProjectGate(name, default, script, judge, idea)
        if default == "per document":
            if not idea and not _LINK.search(cells[5]):
                problems.append(f"gate «{name}» is `per document` but has no idea: link its text in ideas/")
        elif default != "not built yet":
            if judge and not script and not _LINK.search(cells[3]):
                problems.append(f"gate «{name}» has a judge but no script: a project judge decides the places its "
                                "script prints as `CHECK:` lines")
            elif not script and not judge and not _LINK.search(cells[3] + cells[4]):
                problems.append(f"gate «{name}» has no script and no judge")
            if script and not _checks_what(first_line(script)):
                problems.append(f"gate «{name}»: the first line of {script.name} names no file it checks (PLAN.md, "
                                "TEXT.md, or figures/ or a pattern such as figures/*.svg)")
        gates.append(g)
    return gates, problems


def _checks_what(first: str) -> bool:
    return "PLAN.md" in first or "TEXT.md" in first or bool(re.search(r"(?<![\w/])figures\b", first))


def load(folder: Path) -> tuple[Path | None, list[ProjectGate], list[str]]:
    lib = library_dir(folder)
    if lib is None:
        return None, [], []
    gates, problems = read_library(lib)
    return lib, gates, problems


def names(folder: Path) -> dict[str, str]:
    """{gate: its Default} of the document's project library; {} with none."""
    return {g.name: g.default for g in load(folder)[1]}


def running(doc, gates: list[ProjectGate]) -> list[ProjectGate]:
    """The gates the hook runs for this document: `on`; `off` switched on by GATES.md `gates_on`; `manuals` with
    `manual: yes`; none that `gates_off` switches off. `per document` and `not built yet` never run from here."""
    off, on = gates_off(doc), gates_on(doc)
    manual = doc.config.get("manual", "").strip().lower() == "yes"
    return [g for g in gates if g.script and g.name not in off and (
        g.default == "on" or (g.default == "off" and g.name in on) or (g.default == "manuals" and manual))]


def _env(lib: Path) -> dict:
    env = dict(os.environ)
    env["UNSLOPABLE_PROJECT_GATES"] = str(lib)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(lib / "lib"), str(PLUGIN_LIB), env.get("PYTHONPATH", ""))
                                        if p)
    return env


def judge_prompt(judge: Path, folder: Path, lib: Path) -> str:
    text = _FRONTMATTER.sub("", judge.read_text(encoding="utf-8"), count=1).strip()
    return text.replace("{folder}", str(folder)).replace("{library}", str(lib))


def project_gates(doc, target: str, judge_cls) -> tuple[list[Failure], list]:
    """Run the project's gates on one gated file of the document: `target` is PLAN.md, TEXT.md or a figure's path
    under the document folder (`figures/…`). Returns (failures, judge requests); a problem of the library itself is
    a `config` failure on every gated file, so it is fixed before anything else."""
    folder = doc.folder
    lib, gates, problems = load(folder)
    if lib is None:
        return [], []
    fails = [Failure("config", str(lib / "library.md"), "", p) for p in problems]
    figure = target not in ("PLAN.md", "TEXT.md")
    if figure:
        from figure_gates import _targets
    env = _env(lib)
    reqs = []
    for g in running(doc, gates):
        first = first_line(g.script)
        if not (_targets(first, target) if figure else target in first):
            continue
        args = [str(folder)] + ([str(folder / target)] if figure else [])
        lines, checks = run_gate_script(g.script, args, env)
        fails += [Failure(g.name, target, "", ln) for ln in lines]
        if not checks:
            continue
        if not g.judge:
            fails.append(Failure(g.name, target, "", f"the script printed CHECK lines but the gate has no judge in "
                                 f"{lib / 'library.md'}; link its prompt in judges/"))
            continue
        if figure:
            from figure_files import _image_part, render
            checked = _image_part(folder, target, render(folder, target), "The file checked")
        else:
            checked = f"## The file checked (read it for the context of each place)\n\n{folder / target}\n"
        reqs.append(judge_cls(g.name, f"{target} · {g.name}",
                              f"## The judge's prompt of this gate (from {g.judge})\n\n"
                              f"{judge_prompt(g.judge, folder, lib)}\n\n"
                              f"## Where things are\n\n- the document folder: {folder}\n"
                              f"- the project's gate library: {lib}\n\n{checked}\n"
                              "## The places a script found\n\n" + "".join(f"- {c}\n" for c in checks),
                              agent_type=AGENT))
    return fails, reqs


if __name__ == "__main__":  # where a document's project library is, and its gates: for the gates stage
    import sys
    lib, gates, problems = load(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    if lib is None:
        print("no project gate library")
    else:
        print(f"project gate library: {lib}")
        for g in gates:
            print(f"- {g.name}: {g.default}")
        for p in problems:
            print(f"PROBLEM: {p}")
