"""Tests of project gate libraries: a project keeps its own gates at `<project>/.unslopable/gates/`, in the layout of
the plugin's `gates/` folder (library.md, scripts/, judges/, ideas/, lib/, data/), and the gate hook runs them on every
document of the project as it runs the plugin's own gates.

Everything is driven from the outside: the hook `hooks/gate_run.py` fed a recorded PostToolUse Write, the gate
runner's script `hooks/collect_judges.py` (next / record / report) and the viewer's reader `viewer/timeline.py`.

The documents are copies of the fixture `tests/fixtures/doc` with a Polish brief (the English-only spaCy gates do not
run), put into a temp project as `<project>/articles/doc`. CLAUDE_PROJECT_DIR is removed from every hook run except in
the test of that fallback, so the developer's own environment never leaks a library in.

  SKIP_SPACY=1 python3 -m unittest tests.test_project_gates -v      (system Python 3.9, as the hooks run)

The cases, by what the project's author sees:
  1. EndToEnd        a script gate fails as `[<name>]`; a judge gate's CHECK lines reach one `unslopable:gate-project`
                     judge through the runner, its verdict is reported, shown by a later hook run and in the timeline;
                     an idea (`per document`) runs nothing
  2. SharedCode      a script imports a module from `<library>/lib/` and reads `<library>/data/` via
                     UNSLOPABLE_PROJECT_GATES
  3. Defaults        `off` waits for `gates_on`, `manuals` for `manual: yes`, `gates_off` silences a project gate
  4. FindingTheLibrary  the nearest library up from the document wins; CLAUDE_PROJECT_DIR is the fallback
  5. FigureGates     a `figures/*.svg` script runs on an SVG write, with the folder and the figure file
  6. LibraryProblems a broken library fails as `config`, naming library.md
  7. NoLibrary       a project without a library gets exactly the hook output it got before (a regression guard)
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

try:
    from tests.test_gates import (COLLECT, FIXTURE, HOOK, ROOT, fake_transcript, png_bytes, polish_brief, recorded,
                                  svg, with_gates_on)
except ImportError:
    from test_gates import (COLLECT, FIXTURE, HOOK, ROOT, fake_transcript, png_bytes, polish_brief,  # noqa: F401
                            recorded, svg, with_gates_on)

sys.path.insert(0, str(ROOT / "viewer"))

FIXTURE_TEXT = (FIXTURE / "TEXT.md").read_text(encoding="utf-8")
FIXTURE_GATES = (FIXTURE / "GATES.md").read_text(encoding="utf-8")

# the marker of the end-to-end script gate: one added word in element S1.e1
PLAIN_TAP = "A family opens a tap and wants"
KITCHEN_TAP = "A family opens a kitchen tap and wants"
assert PLAIN_TAP in FIXTURE_TEXT and "kitchen" not in FIXTURE_TEXT
KITCHEN_TEXT = FIXTURE_TEXT.replace(PLAIN_TAP, KITCHEN_TAP)

HEADER = "| Gate | What it checks | Default | Script | Judge | Idea |\n|---|---|---|---|---|---|\n"
PROJECT_AGENT = "unslopable:gate-project"


# ================================================================ helpers

def base_env(**extra: str) -> dict:
    """The environment of a hook or runner run: no CLAUDE_PROJECT_DIR unless the test gives one."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env.update(extra)
    return env


def hook(path: Path, env: dict | None = None) -> str:
    """The gate hook on a Write of `path`: its context for the chat ("" when it says nothing)."""
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(recorded(path)), capture_output=True, text=True,
                       timeout=200, env=env or base_env())
    assert r.returncode == 0, r.stderr
    if not r.stdout.strip():
        return ""
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    return out["hookSpecificOutput"]["additionalContext"]


def run_collect(cmd: str, *args, env: dict | None = None) -> str:
    """The gate runner's script, as the runner calls it; its output stripped."""
    r = subprocess.run([sys.executable, str(COLLECT), cmd] + [str(a) for a in args], capture_output=True, text=True,
                       timeout=120, env=env or base_env())
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


JUDGE_BLOCK = re.compile(r'subagent_type "([^"]+)"[^\n]*\n\s+judge_id: (\S+)\n\s+input: (\S+)')


def round_of(folder: Path, file: str = "TEXT.md") -> list[tuple[str, str, str]]:
    """Every judge the runner hands out for `file` in one round: (subagent_type, judge_id, input path)."""
    out = run_collect("next", folder, file, "--max", "500")
    if out == "NONE":
        return []
    assert "more after these" not in out, out.splitlines()[0]
    return JUDGE_BLOCK.findall(out)


def config_lines(ctx: str) -> list[str]:
    return [ln for ln in ctx.splitlines() if "[config]" in ln]


def row(name: str, what: str, default: str, script: str = "", judge: str = "", idea: str = "") -> str:
    """One row of a library table; script/judge/idea are paths relative to the library, linked as the plugin's own
    library links them."""
    s = f"[script]({script})" if script else ""
    j = f"[judge]({judge})" if judge else ""
    i = f"[idea]({idea})" if idea else ""
    return f"| {name} | {what} | {default} | {s} | {j} | {i} |"


def library_md(tables: dict[str, list[str]]) -> str:
    out = "# Gate library\n\nThe project's own gates.\n\n"
    for heading, rows in tables.items():
        out += f"## {heading}\n\n{HEADER}" + "".join(r + "\n" for r in rows) + "\n"
    return out


def failing_script(target: str, line: str) -> str:
    """A script gate on `target` that always prints one failure line."""
    return f"# {target}: a gate of the project\nprint({line!r})\n"


class Project:
    """A temp project folder holding the fixture document at `<root>/<sub>` (with a Polish brief). Its gate libraries
    are written with library(); paths are resolved, so they match what the hook prints."""

    def __init__(self, sub: str = "articles/doc", **files: str):
        self.root = Path(tempfile.mkdtemp(prefix="project-gates-")).resolve()
        self.doc = self.root / sub
        self.doc.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(FIXTURE, self.doc, ignore=shutil.ignore_patterns(".*"))  # no state a live hook left
        self.write("BRIEF.md", polish_brief())
        for name, body in files.items():
            self.write(name, body)

    def write(self, rel: str, body) -> Path:
        p = self.doc / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body, encoding="utf-8")
        return p

    def library(self, tables: dict[str, list[str]], files: dict[str, str], under: Path | None = None) -> Path:
        """Writes `<under or root>/.unslopable/gates/` with library.md and `files` (paths relative to the library);
        returns the library folder."""
        lib = (under or self.root) / ".unslopable" / "gates"
        lib.mkdir(parents=True, exist_ok=True)
        (lib / "library.md").write_text(library_md(tables), encoding="utf-8")
        for rel, body in files.items():
            p = lib / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
        return lib

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def variants(p: Path) -> set[str]:
    """A path as the hook may print it: resolved, or with macOS's /private prefix dropped."""
    s = str(p)
    return {s, s.replace("/private/var/", "/var/", 1), os.path.realpath(s)}


# ================================================================ 1. end to end

NO_KITCHEN_PY = """
    # TEXT.md: the project names no room of the house
    import sys
    from pathlib import Path
    text = (Path(sys.argv[1]) / "TEXT.md").read_text(encoding="utf-8")
    if "kitchen" in text:
        print("S1.e1 — «kitchen»: this project names no room of the house")
    """

PUMP_CLAIMS_PY = """
    # TEXT.md: claims about how fast the pump reacts
    print("CHECK: S1.e1 — «come at once»: does the pump really react at once?")
    """

PUMP_CLAIMS_JUDGE = """
    ---
    name: gate-pump-claims
    description: FRONTMATTER-MUST-BE-STRIPPED
    ---
    Decide for each place whether the words overstate how fast the pump reacts.
    The document is in {folder}. The project's notes on pumps are in {library}/data.
    """

PUMP_PROMISES_IDEA = """
    # pump-promises: every pump model the plan names is described

    The gates stage writes this script for each document.
    """

COMPLAINT = "- «come at once» — S1.e1 — overstates how fast the pump reacts"


def sample_library(p: Project) -> Path:
    return p.library(
        {"Text": [row("no-kitchen", "The text names no room of the house.", "on", script="scripts/no_kitchen.py"),
                  row("pump-claims", "Claims about how fast the pump reacts hold.", "on",
                      script="scripts/pump_claims.py", judge="judges/gate-pump-claims.md"),
                  row("pump-promises", "Every pump model the plan names is described.", "per document",
                      idea="ideas/pump_promises.md")]},
        {"scripts/no_kitchen.py": NO_KITCHEN_PY, "scripts/pump_claims.py": PUMP_CLAIMS_PY,
         "judges/gate-pump-claims.md": PUMP_CLAIMS_JUDGE, "ideas/pump_promises.md": PUMP_PROMISES_IDEA})


class EndToEnd(unittest.TestCase):
    """A sample library with a script gate, a judge gate and an idea, through the hook, the runner and the viewer."""

    def setUp(self):
        self.p = Project()
        self.lib = sample_library(self.p)

    def tearDown(self):
        self.p.close()

    def test_script_failure_then_one_project_judge_through_the_runner_report_hook_and_timeline(self):
        doc = self.p.doc
        # the marker word: the project's script gate fails, tagged with its name, among the script gates
        text = self.p.write("TEXT.md", KITCHEN_TEXT)
        ctx = hook(text)
        self.assertIn("SCRIPT GATES — NOT PASSED", ctx)
        self.assertIn("[no-kitchen]", ctx)
        self.assertIn("«kitchen»: this project names no room of the house", ctx)
        self.assertEqual(config_lines(ctx), [])  # the sample library is valid
        self.assertNotIn("pump-promises", ctx)  # an idea runs nothing from the hook

        # the marker removed: the script gates pass, the runner hands out exactly one project judge
        self.p.write("TEXT.md", FIXTURE_TEXT)
        ctx = hook(text)
        self.assertIn("Script gates passed", ctx)
        self.assertNotIn("[no-kitchen]", ctx)
        judges = round_of(doc)
        project = [(j, i) for a, j, i in judges if a == PROJECT_AGENT]
        self.assertEqual(len(project), 1, f"project judges in the round: {[a for a, _, _ in judges]}")
        pid, pinput = project[0]
        inp = Path(pinput).read_text(encoding="utf-8")
        self.assertIn("Decide for each place whether the words overstate how fast the pump reacts.", inp)
        self.assertNotIn("{folder}", inp)
        self.assertNotIn("{library}", inp)
        self.assertTrue(any(f"The document is in {v}." in inp for v in variants(doc)), inp)
        self.assertTrue(any(f"notes on pumps are in {v}/data" in inp for v in variants(self.lib)), inp)
        self.assertNotIn("FRONTMATTER-MUST-BE-STRIPPED", inp)
        self.assertIn("does the pump really react at once?", inp)  # the CHECK place
        self.assertIn("TEXT.md", inp)  # the checked file

        # the judges answer: the project judge NOT PASSED, every other PASSED; the runner records them all
        conf = self.p.root / "conf"
        sub = conf / "projects" / "-a-project" / "session-1" / "subagents"
        sub.mkdir(parents=True)
        env = base_env(CLAUDE_CONFIG_DIR=str(conf))
        for k, (_agent, jid, ipath) in enumerate(judges):
            answer = f"NOT PASSED\n{COMPLAINT}" if jid == pid else "PASSED"
            fake_transcript(sub / f"agent-j{k}.jsonl", f"judge_id: {jid}\ninput: {ipath}", answer)
        out = run_collect("record", doc, *[f"j{k}" for k in range(len(judges))], env=env)
        self.assertEqual(out, f"recorded {len(judges)} of {len(judges)}: NOT PASSED 1, PASSED {len(judges) - 1}")

        # the report names the project judge's place
        line = run_collect("report", doc, "TEXT.md")
        self.assertTrue(line.startswith("NOT PASSED — 1 place"), line)
        rep = Path(re.search(r"details in (\S+)", line).group(1)).read_text(encoding="utf-8")
        self.assertIn("overstates how fast the pump reacts", rep)

        # a later write of the same text: no judge is due, the hook says the judge gates did not pass
        ctx = hook(text)
        self.assertNotIn("START ONE AGENT", ctx)
        self.assertIn("JUDGE GATES — NOT PASSED", ctx)

        # the viewer shows the verdict under the project gate's name
        import timeline
        tl = timeline.read_timeline(doc)
        v = [e for e in tl["events"] if e["kind"] == "verdict" and e["judge"] == pid]
        self.assertEqual(len(v), 1, [e["judge"] for e in tl["events"] if e["kind"] == "verdict"][:5])
        self.assertEqual(v[0]["gate"], "pump-claims")
        self.assertEqual(v[0]["verdict"], "NOT PASSED")


# ================================================================ 2. shared code and data of the library

BANNED_PY = """
    # TEXT.md: no word of the project's banned list
    import os
    import sys
    from pathlib import Path

    import banned_words  # <library>/lib/banned_words.py

    lib = Path(os.environ["UNSLOPABLE_PROJECT_GATES"])
    words = (lib / "data" / "banned.txt").read_text(encoding="utf-8").split()
    text = (Path(sys.argv[1]) / "TEXT.md").read_text(encoding="utf-8")
    for w in banned_words.found(text, words):
        print(banned_words.line(w))
    """

BANNED_LIB = """
    def found(text, words):
        return [w for w in words if w in text]


    def line(word):
        return "«" + word + "» — on the project's banned list (said by the shared lib)"
    """


class SharedCode(unittest.TestCase):
    def test_a_script_imports_from_lib_and_reads_data_through_the_library_variable(self):
        p = Project()
        try:
            p.library({"Text": [row("banned-words", "No word of the project's banned list.", "on",
                                    script="scripts/banned_words_gate.py")]},
                      {"scripts/banned_words_gate.py": BANNED_PY, "lib/banned_words.py": BANNED_LIB,
                       "data/banned.txt": "kitchen\nbasement\n"})
            text = p.write("TEXT.md", KITCHEN_TEXT)
            ctx = hook(text)
            self.assertIn("[banned-words]", ctx)
            self.assertIn("«kitchen» — on the project's banned list (said by the shared lib)", ctx)
            self.assertNotIn("Traceback", ctx)
            p.write("TEXT.md", FIXTURE_TEXT)
            ctx = hook(text)
            self.assertNotIn("[banned-words]", ctx)
            self.assertIn("Script gates passed", ctx)
        finally:
            p.close()


# ================================================================ 3. defaults and GATES.md switches

def defaults_library(p: Project) -> Path:
    return p.library(
        {"Text": [row("always-x", "Runs in every document.", "on", script="scripts/always_x.py"),
                  row("opt-x", "Runs when GATES.md switches it on.", "off", script="scripts/opt_x.py"),
                  row("man-x", "Runs in manuals.", "manuals", script="scripts/man_x.py"),
                  row("judge-x", "A judge of the project.", "on", script="scripts/judge_x.py",
                      judge="judges/gate-judge-x.md"),
                  row("later-x", "Waits for code.", "not built yet")]},
        {"scripts/always_x.py": failing_script("TEXT.md", "always-x ran"),
         "scripts/opt_x.py": failing_script("TEXT.md", "opt-x ran"),
         "scripts/man_x.py": failing_script("TEXT.md", "man-x ran"),
         "scripts/judge_x.py": "# TEXT.md: a place for the judge\nprint('CHECK: S1.e3 — is the valve a part?')\n",
         "judges/gate-judge-x.md": "Decide whether each place names a part of the pump. Folder: {folder}.\n"})


class Defaults(unittest.TestCase):
    def setUp(self):
        self.p = Project()
        defaults_library(self.p)
        self.text = self.p.doc / "TEXT.md"

    def tearDown(self):
        self.p.close()

    def gates_md(self, extra: str) -> None:
        self.p.write("GATES.md", FIXTURE_GATES.rstrip("\n") + "\n" + extra + "\n")

    def test_on_runs_and_off_and_manuals_wait(self):
        ctx = hook(self.text)
        self.assertIn("[always-x]", ctx)
        self.assertNotIn("[opt-x]", ctx)
        self.assertNotIn("[man-x]", ctx)
        self.assertNotIn("[later-x]", ctx)
        self.assertEqual(config_lines(ctx), [])

    def test_gates_on_switches_an_off_project_gate_on_with_no_config_failure(self):
        self.p.write("GATES.md", with_gates_on("no-document-talk; opt-x"))
        ctx = hook(self.text)
        self.assertIn("[opt-x]", ctx)
        self.assertIn("opt-x ran", ctx)
        self.assertEqual(config_lines(ctx), [])

    def test_manual_yes_runs_a_manuals_gate(self):
        self.gates_md("manual: yes")
        ctx = hook(self.text)
        self.assertIn("[man-x]", ctx)
        self.assertIn("man-x ran", ctx)
        self.assertNotIn("[opt-x]", ctx)
        self.assertEqual(config_lines(ctx), [])

    def test_gates_off_silences_a_project_script_gate_and_a_project_judge(self):
        # control: always-x off, judge-x on: the script gates pass and the project judge is handed out
        self.gates_md("gates_off: always-x (the project allows it in this document)")
        ctx = hook(self.text)
        self.assertNotIn("[always-x]", ctx)
        self.assertEqual(config_lines(ctx), [])
        self.assertIn("Script gates passed", ctx)
        self.assertIn(PROJECT_AGENT, [a for a, _, _ in round_of(self.p.doc)])
        # both off: no failure, no project judge, no config failure
        self.gates_md("gates_off: always-x (the project allows it here); judge-x (the brief names no parts)")
        ctx = hook(self.text)
        self.assertNotIn("[always-x]", ctx)
        self.assertEqual(config_lines(ctx), [])
        self.assertIn("Script gates passed", ctx)
        self.assertNotIn(PROJECT_AGENT, [a for a, _, _ in round_of(self.p.doc)])


# ================================================================ 4. which library a document gets

def one_gate_library(p: Project, name: str, under: Path) -> Path:
    return p.library({"Text": [row(name, f"The {name} library is the one in use.", "on",
                                   script=f"scripts/{name.replace('-', '_')}.py")]},
                     {f"scripts/{name.replace('-', '_')}.py": failing_script("TEXT.md", f"{name} library ran")},
                     under=under)


class FindingTheLibrary(unittest.TestCase):
    def test_the_nearest_library_up_from_the_document_wins(self):
        p = Project()  # the document at <root>/articles/doc
        try:
            one_gate_library(p, "outer-x", p.root)
            one_gate_library(p, "inner-x", p.root / "articles")
            ctx = hook(p.doc / "TEXT.md")
            self.assertIn("[inner-x]", ctx)
            self.assertNotIn("[outer-x]", ctx)
        finally:
            p.close()

    def test_claude_project_dir_is_the_fallback_and_a_nearer_library_beats_it(self):
        p = Project(sub="doc")  # no library anywhere above the document
        other = Project(sub="unused")  # a second project: only its library is used
        try:
            one_gate_library(other, "env-x", other.root)
            text = p.doc / "TEXT.md"
            self.assertNotIn("[env-x]", hook(text))
            ctx = hook(text, base_env(CLAUDE_PROJECT_DIR=str(other.root)))
            self.assertIn("[env-x]", ctx)
            self.assertIn("env-x library ran", ctx)
            # a library up from the document wins over CLAUDE_PROJECT_DIR
            one_gate_library(p, "near-x", p.root)
            ctx = hook(text, base_env(CLAUDE_PROJECT_DIR=str(other.root)))
            self.assertIn("[near-x]", ctx)
            self.assertNotIn("[env-x]", ctx)
        finally:
            p.close()
            other.close()


# ================================================================ 5. a figure script gate

FIG_X_PY = """
    # figures/*.svg: labels in a drawn figure are large enough
    import sys
    from pathlib import Path
    folder_ok = (Path(sys.argv[1]) / "BRIEF.md").exists()
    print(Path(sys.argv[2]).name + " — a label at 6 px" + (" (folder ok)" if folder_ok else " (no folder)"))
    """


class FigureGates(unittest.TestCase):
    def test_a_figure_script_runs_on_an_svg_write_only(self):
        p = Project()
        try:
            p.library({"Text": [row("text-x", "A text gate of the project.", "on", script="scripts/text_x.py")],
                       "Figures": [row("fig-x", "Labels in a figure are large enough.", "on",
                                       script="scripts/fig_x.py")]},
                      {"scripts/text_x.py": failing_script("TEXT.md", "text-x ran"), "scripts/fig_x.py": FIG_X_PY})
            fig = p.write("figures/S1.e2.svg", svg("pressure switch"))
            ctx = hook(fig)
            self.assertIn("[fig-x]", ctx)
            self.assertIn("S1.e2.svg — a label at 6 px (folder ok)", ctx)
            self.assertNotIn("[text-x]", ctx)
            # a PNG is not `figures/*.svg`; TEXT.md is not a figure
            self.assertNotIn("[fig-x]", hook(p.write("figures/shot.png", png_bytes())))
            ctx = hook(p.doc / "TEXT.md")
            self.assertIn("[text-x]", ctx)
            self.assertNotIn("[fig-x]", ctx)
        finally:
            p.close()


    def test_a_figure_script_hands_its_check_places_to_the_project_judge(self):
        p = Project()
        try:
            p.library({"Figures": [row("fig-judged", "Labels in a figure are large enough.", "on",
                                       script="scripts/fig_judged.py", judge="judges/gate-fig-judged.md")]},
                      {"scripts/fig_judged.py": "# figures/*.svg: labels are large enough\n"
                                                "print('CHECK: the legend — may be too small')\n",
                       "judges/gate-fig-judged.md": "Fail a label too small to read as printed.\n"})
            fig = p.write("figures/S1.e2.svg", svg("pressure switch"))
            ctx = hook(fig)
            self.assertNotIn("SCRIPT GATES — NOT PASSED", ctx)
            judges = [j for j in round_of(p.doc, "figures/S1.e2.svg") if j[1].startswith("fig-judged-")]
            self.assertEqual([j[0] for j in judges], ["unslopable:gate-project"])
            inp = Path(judges[0][2]).read_text(encoding="utf-8")
            self.assertIn("Fail a label too small", inp)
            self.assertIn("may be too small", inp)
            self.assertIn("S1.e2", inp)
        finally:
            p.close()


# ================================================================ 6. a broken library

OK_ROW = row("ok-x", "A gate that passes.", "on", script="scripts/ok_x.py")
OK_FILES = {"scripts/ok_x.py": "# TEXT.md: passes\n"}

PROBLEMS = {
    # case: (rows added to the valid library, files added, a word the config line names)
    "a plugin gate's name": ([row("cliche", "The project's own cliché list.", "on", script="scripts/cliche_local.py")],
                             {"scripts/cliche_local.py": "# TEXT.md: clichés\n"}, "cliche"),
    "a link to a missing file": ([row("ghost-x", "A gate whose script is gone.", "on", script="scripts/ghost.py")],
                                 {}, "ghost.py"),
    "an unknown default": ([row("odd-x", "A gate with a default no one knows.", "sometimes",
                                script="scripts/odd_x.py")],
                           {"scripts/odd_x.py": "# TEXT.md: odd\n"}, "sometimes"),
    "a name the gate code reserves": ([row("length", "The project's own length rule.", "on",
                                           script="scripts/length_x.py")],
                                       {"scripts/length_x.py": "# TEXT.md: length\n"}, "length"),
    "a script naming no file": ([row("blind-x", "A script that does not say what it checks.", "on",
                                     script="scripts/blind_x.py")],
                                {"scripts/blind_x.py": "# checks things\n"}, "blind_x.py"),
    "a judge with no script": ([row("lonely-x", "A judge nothing hands places to.", "on",
                                    judge="judges/gate-lonely-x.md")],
                               {"judges/gate-lonely-x.md": "Decide each place.\n"}, "lonely-x"),
}


class LibraryProblems(unittest.TestCase):
    def test_the_valid_library_has_no_config_failure(self):
        p = Project()
        try:
            p.library({"Text": [OK_ROW]}, OK_FILES)
            ctx = hook(p.doc / "TEXT.md")
            self.assertEqual(config_lines(ctx), [])
            self.assertIn("Script gates passed", ctx)
        finally:
            p.close()

    def test_each_problem_fails_as_config_naming_library_md(self):
        for case, (rows, files, word) in PROBLEMS.items():
            with self.subTest(case):
                p = Project()
                try:
                    p.library({"Text": [OK_ROW] + rows}, {**OK_FILES, **files})
                    ctx = hook(p.doc / "TEXT.md")
                    self.assertIn("NOT PASSED", ctx)
                    cfg = config_lines(ctx)
                    self.assertTrue(any("library.md" in ln and word in ln for ln in cfg),
                                    f"no [config] line naming library.md and «{word}»: {cfg}")
                finally:
                    p.close()


# ================================================================ 7. no library: nothing changes (regression guard)

class NoLibrary(unittest.TestCase):
    def test_a_project_without_a_library_gets_the_same_hook_output(self):
        bare = Project()
        other = Project()
        try:
            (other.root / ".unslopable").mkdir()
            (other.root / ".unslopable" / "notes.md").write_text("not a gate library\n", encoding="utf-8")
            outs = []
            for p in (bare, other):
                ctx = hook(p.doc / "TEXT.md")
                for v in sorted(variants(p.doc), key=len, reverse=True):
                    ctx = ctx.replace(v, "<DOC>")
                outs.append(ctx)
            self.assertEqual(outs[0], outs[1])
            self.assertIn("Script gates passed", outs[0])
            self.assertNotIn(PROJECT_AGENT, [a for a, _, _ in round_of(other.doc)])
        finally:
            bare.close()
            other.close()


if __name__ == "__main__":
    unittest.main()
