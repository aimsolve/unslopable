"""Reconciliation of gates/library.md with the code: every gate of the list has its files, and every file is listed.

The library is one table per part of the document, one row per gate: `| gate | what it checks | default | script |
judge | idea |`. The script, judge and idea cells hold links to `scripts/<name>.py`, `judges/gate-<gate>.md` and
`ideas/<name>.md`. The test checks
- every linked file exists, and every file of `gates/scripts/`, `gates/judges/` and `gates/ideas/` is linked;
- a script is run by code the gate hook (hooks/gate_run.py `main`) reaches: one of its functions is reached;
- a judge is named `gate-<gate>.md` after its row and created by code the hook reaches (the gate name is a string
  there);
- the default is on, off, manuals, per document or not built yet; `off` rows are the gates of `OFF_BY_DEFAULT`;
  a `per document` row has only an idea; a row with no file is `not built yet`;
- the plugin manifest lists every agent file, so the judges in `gates/judges/` load.
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import ast
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATES = ROOT / "gates"
LIBRARY = GATES / "library.md"
MODULES = [ROOT / "hooks" / "gate_run.py", *sorted((GATES / "lib").glob("*.py")),
           *sorted((GATES / "scripts").glob("*.py"))]
DEFAULTS = {"on", "off", "manuals", "per document", "not built yet"}
LINK = re.compile(r"\]\(([^)]+)\)")
ROW = re.compile(r"^\|\s*([a-z][a-z0-9-]*)\s*\|")


def library_rows(text: str | None = None) -> list[dict]:
    """Every gate row of the library's tables: line number, gate, what it checks, default, linked files."""
    rows = []
    for n, line in enumerate((text if text is not None else LIBRARY.read_text(encoding="utf-8")).split("\n"), 1):
        if not ROW.match(line) or line.startswith("| Gate "):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        cells += [""] * (6 - len(cells))
        rows.append({"line": n, "gate": cells[0], "checks": cells[1], "default": cells[2],
                     "script": LINK.findall(cells[3]), "judge": LINK.findall(cells[4]),
                     "idea": LINK.findall(cells[5]), "cells": len(cells)})
    return rows


def reachable_code() -> tuple[set[tuple[str, str]], set[str]]:
    """((module, function) the hook's `main` reaches, string constants in them and in the module-level values they
    read). A function is reached when a reached function uses its name (a call or a reference): a bare name resolves
    to a function of the same module or to what that module imports under that name (`from m import f as g`);
    `mod.f` resolves through `import m as mod`. A smoke check that the code is wired, not a proof."""
    funcs: dict[tuple[str, str], list[ast.AST]] = {}
    assigns: dict[tuple[str, str], list[ast.AST]] = {}
    names: dict[str, dict[str, tuple[str, str]]] = {}   # module -> {local name: (module, name)}
    mods: dict[str, dict[str, str]] = {}                # module -> {alias: module}
    for path in MODULES:
        mod = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names[mod], mods[mod] = {}, {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.setdefault((mod, node.name), []).append(node)
            elif isinstance(node, ast.ImportFrom) and node.module:
                for al in node.names:
                    names[mod][al.asname or al.name] = (node.module, al.name)
            elif isinstance(node, ast.Import):
                for al in node.names:
                    mods[mod][al.asname or al.name] = al.name
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name) and node.value is not None:
                        assigns.setdefault((mod, t.id), []).append(node.value)

    def refs(mod: str, node: ast.AST) -> set[tuple[str, str]]:
        out = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                out.add((mod, n.id) if (mod, n.id) in funcs or (mod, n.id) in assigns
                        else names[mod].get(n.id, (mod, n.id)))
            elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in mods[mod]:
                out.add((mods[mod][n.value.id], n.attr))
        return out

    def consts_in(node: ast.AST) -> set[str]:
        return {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    seen, todo, consts, read = set(), [("gate_run", "main")], set(), set()
    while todo:
        key = todo.pop()
        if key in seen or key not in funcs:
            continue
        seen.add(key)
        for node in funcs[key]:
            consts |= consts_in(node)
            for r in refs(key[0], node):
                if r in funcs and r not in seen:
                    todo.append(r)
                elif r in assigns:
                    read.add(r)
    for r in read:
        for v in assigns[r]:
            consts |= consts_in(v)
    return seen, consts


def off_by_default() -> set[str]:
    tree = ast.parse((GATES / "lib" / "common.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "OFF_BY_DEFAULT" for t in node.targets):
            return set(ast.literal_eval(node.value))
    return set()


def check(rows: list[dict], reached: set[tuple[str, str]], consts: set[str], off: set[str]) -> list[str]:
    problems = []
    reached_mods = {m for m, _ in reached}
    for r in rows:
        where = f"gates/library.md line {r['line']} ({r['gate']})"
        if r["cells"] != 6:
            problems.append(f"{where}: {r['cells']} cells, not 6")
        if r["default"] not in DEFAULTS:
            problems.append(f"{where}: default «{r['default']}» is none of {sorted(DEFAULTS)}")
        if (r["default"] == "off") != (r["gate"] in off):
            problems.append(f"{where}: default «{r['default']}», but OFF_BY_DEFAULT "
                            + ("has" if r["gate"] in off else "does not have") + " this gate")
        files = r["script"] + r["judge"] + r["idea"]
        if r["default"] == "not built yet" and files:
            problems.append(f"{where}: not built yet, yet it links files")
        if r["default"] != "not built yet" and not files:
            problems.append(f"{where}: no script, judge or idea, and not marked «not built yet»")
        if r["default"] == "per document" and (r["script"] or r["judge"] or not r["idea"]):
            problems.append(f"{where}: a per-document gate has an idea and nothing else")
        for kind, folder in (("script", "scripts"), ("judge", "judges"), ("idea", "ideas")):
            for link in r[kind]:
                path = GATES / link
                if not link.startswith(f"{folder}/") or not path.is_file():
                    problems.append(f"{where}: {kind} link «{link}» is no file in gates/{folder}/")
                    continue
                if kind == "script" and path.stem not in reached_mods:
                    problems.append(f"{where}: no function of {link} is reached from the gate hook")
                if kind == "judge":
                    if path.name != f"gate-{r['gate']}.md":
                        problems.append(f"{where}: judge {link} is not named gate-{r['gate']}.md")
                    if r["gate"] not in consts:
                        problems.append(f"{where}: judge `{r['gate']}` is not created by code the gate hook reaches")
    return problems


class LibraryReconciliation(unittest.TestCase):
    def test_every_gate_has_its_files_and_is_run(self):
        rows = library_rows()
        self.assertGreater(len(rows), 60)
        reached, consts = reachable_code()
        problems = check(rows, reached, consts, off_by_default())
        self.assertEqual(problems, [], "\n" + "\n".join(problems))
        gates = [r["gate"] for r in rows]
        self.assertEqual(len(gates), len(set(gates)), "a gate is listed twice")
        # no gate waits since the research stage was built; change this when one does
        waiting = [r["gate"] for r in rows if r["default"] == "not built yet"]
        self.assertEqual(waiting, [])
        print("\nLibrary gates not built yet: " + ", ".join(waiting), file=sys.stderr)

    def test_every_file_of_the_gate_folders_is_listed(self):
        text = LIBRARY.read_text(encoding="utf-8")
        linked = {(GATES / link).resolve() for link in LINK.findall(text)}
        for folder, pattern in (("scripts", "*.py"), ("judges", "*.md"), ("ideas", "*.md")):
            for path in sorted((GATES / folder).glob(pattern)):
                self.assertIn(path.resolve(), linked, f"gates/{folder}/{path.name} is in no row of the library")

    def test_the_check_catches_broken_rows(self):
        reached, consts = reachable_code()
        fake = library_rows(
            "| gate-a | x | on | | | |\n"                                                    # no file
            "| no-such | x | on | | [judge](judges/gate-no-such.md) | |\n"                   # missing judge
            "| gate-b | x | on | [script](scripts/no_such.py) | | |\n"                        # missing script
            "| cliche | x | sometimes | | [judge](judges/gate-cliche.md) | |\n"              # unknown default
            "| no-announcing | x | on | [script](scripts/no_announcing.py) | | |\n"         # off gate marked on
            "| cliche | x | on | | [judge](judges/gate-purple-prose.md) | |\n")             # judge of another gate
        problems = check(fake, reached, consts, off_by_default())
        for line in range(1, 7):
            self.assertTrue([p for p in problems if f"line {line} " in p], (line, problems))

    def test_reach_is_from_the_hook(self):
        reached, _ = reachable_code()
        fns = {f for _, f in reached}
        for fn in ("run_text", "run_plan", "run_figure", "text_requests", "gate_figure_steps"):
            self.assertIn(fn, fns)

    def test_the_manifest_lists_every_agent(self):
        manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        want = sorted([f"./agents/{p.name}" for p in (ROOT / "agents").glob("*.md")] +
                      [f"./gates/judges/{p.name}" for p in (GATES / "judges").glob("*.md")])
        self.assertEqual(sorted(manifest.get("agents", [])), want)

    def test_no_script_shadows_a_module_of_its_own(self):
        """gates/lib and gates/scripts are both on the import path: two files of one name would shadow each other."""
        lib = {p.stem for p in (GATES / "lib").glob("*.py")}
        scripts = {p.stem for p in (GATES / "scripts").glob("*.py")}
        self.assertEqual(lib & scripts, set())


if __name__ == "__main__":
    unittest.main()
