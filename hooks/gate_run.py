#!/usr/bin/env python3
"""PostToolUse hook on Write/Edit/MultiEdit and Bash: runs a document's gates when a plan level, the text or a figure
is written (a figure: an image under the document's `figures/`, written by Write/Edit or changed by a Bash command
that names a path in its `figures/`; see `figure_main` and gates/lib/figure_gates.py).

A gated file is PLAN.md or TEXT.md in a folder that has a BRIEF.md (formats: README, «Provisional (19.11 night, test
run)»). On PLAN.md it gates every level from the sections down to the deepest level written so far; judges run only
for levels not approved as they stand. The hook runs the script gates itself. When they fail, it hands the failures
to the chat that wrote the file and stops there. When they pass, it writes one input file per judge into the
document's `.gates/inputs/` (indexed in `.gates/requests.json`) and the run into `.gates/due.json`: every judge of
the run and the ones due now. It never lists the judges to the chat (their inputs and answers would fill
the writer's context). It tells the chat to start ONE subagent, the gate runner (`agents/gate-runner.md`), with the
folder, the file and `collect_judges.py`. A hook cannot start a subagent, so the chat does. The runner starts every
due judge itself, in rounds, records their verdicts and writes `.gates/report-<file>.md`; its whole answer is one
line, `PASSED` or `NOT PASSED — N places, details in <report file>`. On NOT PASSED the chat reads the report, fixes
its own file point by point and writes it again, and this hook runs again. A judge whose input did not change is not
run again: its verdict stands in `.gates/verdicts.json`. When no judge is due but some said NOT PASSED with the same
input, the hook writes the report itself and gives the chat the same line.

A plan level counts as approved while PLAN.md has its line `Approved <sections|subsections|elements> by …` and the
level's items are the ones that line was written for (`.gates/approved.json`): a level edited after its approval
needs approval again, and the other levels keep theirs. A level with no items has nothing to approve.

Anything unexpected -> a short note in the context, never a blocked write.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("UNSLOPABLE_CACHE") or Path.home() / ".cache" / "unslopable")  # tests point it elsewhere
LOG = CACHE / "gate_run.log"
COLLECT = HERE / "collect_judges.py"
WAIT = HERE / "wait_critic.py"
MAX_LIST = 40  # script failures shown at once
GATES = HERE.parent / "gates"


def gate_paths() -> None:
    """Makes the shared gate modules (gates/lib) and the gate scripts (gates/scripts) importable by name."""
    for p in (GATES / "scripts", GATES / "lib"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def log(msg: str) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def _out(ctx: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}},
                     ensure_ascii=False))


# ---------------------------------------------------------------- approval of a plan level

def _approval_line(text: str, name: str) -> str:
    for line in text.splitlines():
        if re.match(rf"Approved {name} by \S", line.strip()):
            return line.strip()
    return ""


def approval(gstate, state: Path, doc, level: int, written: str = "") -> str:
    """'yes', 'no', 'stale' (approved, then edited) or 'empty' (no items, nothing to approve) for one plan level.
    `written` is the text this tool call put into PLAN.md: a write that carries the level's approval line records
    the items it approves."""
    from docs import LEVELS, PLAN_FILE, level_text
    rows = doc.plans.get(level, [])
    if not rows:
        return "empty"
    try:
        text = (doc.folder / PLAN_FILE).read_text(encoding="utf-8")
    except OSError:
        return "no"
    line = _approval_line(text, LEVELS[level])
    if not line:
        return "no"
    h = hashlib.sha1(level_text(rows).encode("utf-8")).hexdigest()
    key = f"{PLAN_FILE} {LEVELS[level]}"
    rec = gstate.read(state / "approved.json").get(key)
    if line in written or rec is None or rec.get("line") != line:
        gstate.update(state / "approved.json", lambda d: d.__setitem__(key, {"line": line, "hash": h}))
        return "yes"
    return "yes" if rec.get("hash") == h else "stale"


def _written(tool_input: dict) -> str:
    """What an Edit/MultiEdit put in. A full Write is left out on purpose: rewriting the whole plan keeps its
    approval lines, and that must not count as a new approval; a new approval line differs from the old one."""
    parts = [tool_input.get("new_string", "")]
    parts += [e.get("new_string", "") for e in tool_input.get("edits") or [] if isinstance(e, dict)]
    return "\n".join(p for p in parts if isinstance(p, str))


# ---------------------------------------------------------------- judges

def write_inputs(gstate, state: Path, reqs, gated: Path) -> None:
    (state / "inputs").mkdir(parents=True, exist_ok=True)
    for r in reqs:
        (state / "inputs" / f"{r.id}.md").write_text(
            f"# Judge input · gate {r.gate} · {r.unit}\n\n{r.input}", encoding="utf-8")
    gstate.update(state / "requests.json", lambda d: d.update(
        {r.id: {"gate": r.gate, "unit": r.unit, "agent": r.agent, "file": str(gated)} for r in reqs}))


def write_due(gstate, state: Path, name: str, reqs, due) -> None:
    """The run on `name` for the gate runner: every judge of the run (for its report) and the ones due now. A new
    run gives each due judge its tries again (collect_judges.TRIES)."""
    gstate.update(state / "due.json", lambda d: d.__setitem__(name, {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"), "all": [r.id for r in reqs], "due": [r.id for r in due]}))
    gstate.update(state / "runner.json", lambda d: [d.pop(r.id, None) for r in due])


def runner_step(folder: Path, name: str, n: int) -> str:
    """The one agent the writing stage starts: it runs the due judges and answers with one line."""
    return (f"Judges due now: {n}.\nSTART ONE AGENT NOW, the gate runner: Agent tool, subagent_type "
            "\"unslopable:gate-runner\", description \"gate runner\", prompt exactly these three lines:\n"
            f"   folder: {folder}\n   file: {name}\n   script: {COLLECT}\n"
            "It starts every due judge and records the verdicts; nothing of the judges comes to you. Its answer is one "
            "line: `PASSED`, or `NOT PASSED — N places, details in <report file>`. If the Agent result gives an "
            f"output_file (it runs in the background), wait for it in this same turn: Bash `python3 {WAIT} "
            "<output_file> 540` (Bash timeout 600000); `TIMEOUT` means it is still working, so run the same command "
            "again. Ignore the task notification that arrives later. Change no file of the document while it runs.")


def report_step(what: str) -> str:
    return (f"On NOT PASSED, read the report file and fix {what} at each place it lists, point by point. Do not argue "
            "with a judge and do not edit another stage's file. Then write the file again: this hook runs the gates "
            "again, and only judges whose input changed run again.")


def approval_step(gstate, JudgeRequest, doc, level: int, state: Path) -> str:
    # The plan-approval judge (autonomous mode) is set aside for now: the author approves every level.
    from docs import LEVELS, PLAN_FILE
    name = LEVELS[level]
    before = "the next level is written" if level < 3 else "the text is written"
    return (f"Every gate of the plan passed. The {name} are the level waiting for approval. Show them to the author "
            f"and wait for the approval before {before}. On approval add the line `Approved {name} by <the author>, "
            f"<date> <time>` above the list in {PLAN_FILE} with an Edit (or replace the old `Approved {name} by …` "
            "line), a blank line between it and any other approval line.")


# ---------------------------------------------------------------- the document's own gates

def custom_gates(folder: Path, name: str, failure_cls, judge_cls) -> tuple[list, list]:
    """Run every `.gates/custom/*.py` whose first line names `name` (PLAN.md or TEXT.md), as the gates stage writes
    them: `python3 <script> <folder>`, one stdout line per place, no output = passed.

    A plain line is a failure. A line starting with `CHECK:` is a place for a judge: when `.gates/custom/<gate>.md`
    holds the gate's rule, every CHECK place of one run goes to one judge `gate-custom` with that rule.
    Returns (failures, judge requests)."""
    from common import run_gate_script
    fails, reqs = [], []
    for script in sorted((folder / ".gates" / "custom").glob("*.py")):
        try:
            first = script.read_text(encoding="utf-8").splitlines()[:1]
        except OSError:
            continue
        if not first or name not in first[0]:
            continue
        gate = f"custom:{script.stem}"
        lines, checks = run_gate_script(script, [str(folder)])
        fails += [failure_cls(gate, name, "", ln) for ln in lines]
        if not checks:
            continue
        rule_file = script.with_suffix(".md")
        rule = rule_file.read_text(encoding="utf-8").strip() if rule_file.exists() else ""
        if not rule:
            fails.append(failure_cls(gate, name, "", f"the script printed CHECK lines but {rule_file.name} (the "
                                     "judge's rule) is missing or empty; write it next to the script"))
            continue
        places = "".join(f"- {c}\n" for c in checks)
        reqs.append(judge_cls("custom", f"{name} · {script.stem}",
                              f"## The rule of this gate (from {rule_file})\n\n{rule}\n\n"
                              f"## The file checked (read it for the context of each place)\n\n{folder / name}\n\n"
                              f"## The places a script found\n\n{places}"))
    return fails, reqs


# ---------------------------------------------------------------- main

def main() -> None:
    data = json.load(sys.stdin)
    gate_paths()
    import history  # every version of every file of a document, for its timeline, before any gate runs
    history.track(data)
    if research_main(data):  # the research's fact base changed (its own gates)
        return
    if figure_main(data):  # a figure file was written (its own gates); a Bash call gates only figures
        return
    if data.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path", "")
    if not path:
        return
    # Imported here, inside the guard of __main__, so a broken gate module is reported, not a silent hook error.
    gate_paths()
    import state as gstate
    from docs import LEVELS, PLAN_FILE, TEXT_FILE, doc_folder, load
    from judge_gates import JudgeRequest, plan_compound_request, plan_requests, text_requests
    from common import Failure
    from run_scripts import run_plan, run_text
    from cohesion import gate_cohesion
    from no_compound import gate_plan_compound
    from no_truncated import gate_truncated
    from tense_shift import gate_tense

    found = doc_folder(os.path.realpath(os.path.expanduser(path)))
    if not found:
        return
    folder, kind = found
    import history
    kept = history.entry(folder, TEXT_FILE if kind == "text" else PLAN_FILE)  # kept by track(); the gates note on it
    doc = load(folder)
    state = folder / ".gates"
    state.mkdir(exist_ok=True)
    notices: list = []
    # every level's approval, recorded as a baseline for lines added outside this hook
    written = _written(tool_input) if kind == "plan" else ""
    approvals = {lvl: approval(gstate, state, doc, lvl, written) for lvl in LEVELS}
    if kind == "text":
        name = TEXT_FILE
        for lvl, a in approvals.items():
            if a in ("no", "stale"):
                notices.append(f"in {PLAN_FILE} the {LEVELS[lvl]} "
                               + ("are not approved yet" if a == "no" else
                                  "changed since their approval and need approval again")
                               + "; the text is written from the approved plan")
        fails, cands = run_text(doc, notices)
        from figure_steps import gate_figure_steps  # numbered marks of the figures in the text
        fails += gate_figure_steps(doc)
        from common import gates_off  # a switched-off gate does no work: its finder is not run either
        off = gates_off(doc)
        cohesion = gate_cohesion(doc, notices) if not fails and "fact-soup" not in off else {}
        truncated = gate_truncated(doc, notices) if not fails and "no-truncated" not in off else {}
        tense = gate_tense(doc, notices) if not fails and "tense-shift" not in off else {}
        stage = "the writer"
        upto = 0
    else:
        name = PLAN_FILE
        upto = max([lvl for lvl in LEVELS if doc.plans.get(lvl)] or [1])
        for lvl in range(1, upto + 1):
            a = approvals[lvl]
            if a == "stale":
                notices.append(f"the {LEVELS[lvl]} changed since their approval and need approval again once their "
                               "gates pass")
            elif a == "no" and lvl < upto:
                notices.append(f"the {LEVELS[lvl]} are not approved yet; each level is approved before the next")
        fails = run_plan(doc, upto)
        # no compound sentence: only on the levels not approved as they stand (approved ones are left as they are)
        open_levels = [lvl for lvl in range(1, upto + 1) if approvals[lvl] in ("no", "stale")]
        from common import gates_off
        more, cands = gate_plan_compound(doc, open_levels, notices) \
            if open_levels and "no-compound" not in gates_off(doc) else ([], [])
        fails += more
        stage = f"the plan down to its {LEVELS[upto]}"

    more_fails, custom_reqs = custom_gates(folder, name, Failure, JudgeRequest)
    fails += more_fails
    from project_gates import project_gates  # the gates of the project's own library (.unslopable/gates/)
    more_fails, project_reqs = project_gates(doc, name, JudgeRequest)
    fails += more_fails
    custom_reqs += project_reqs
    from common import drop_off  # the gates GATES.md `gates_off` switches off report nothing and start no judge
    fails = drop_off(doc, fails, kind)

    parts = [f"unslopable gates on {name} ({stage}). Gate results go to you because you wrote this file; fix only "
             "this file" + (" (a length miss is the exception: it goes back to the plan)" if kind == "text" else "")
             + ".\n"]
    if notices:
        parts.append("Notes: " + "; ".join(notices) + ".\n")

    if fails:
        shown = fails[:MAX_LIST]
        more = f"\n(and {len(fails) - MAX_LIST} more; they show again after the next write)" \
            if len(fails) > MAX_LIST else ""
        parts.append(f"SCRIPT GATES — NOT PASSED ({len(fails)}):\n" +
                     "".join(f"{k}. {f.line()}\n" for k, f in enumerate(shown, 1)) + more +
                     "\nFix every point in the file, then write it again; this hook runs again. The judge gates run "
                     "once the script gates pass.")
        log(f"{folder} {name}: {len(fails)} script failures")
        _status(gstate, state, name, "script failures", [f.line() for f in fails])
        history.note(folder, kept, [f.line() for f in fails], [])
        _out("\n".join(parts))
        return

    if kind == "text":
        reqs = text_requests(doc, cands, cohesion, tense, truncated=truncated)
        from figure_gates import text_requests as figure_text_requests
        reqs += figure_text_requests(doc)
    else:  # judges of the levels not approved as they stand
        reqs = [r for lvl in range(1, upto + 1) if approvals[lvl] in ("no", "stale")
                for r in plan_requests(doc, lvl)]
        reqs += plan_compound_request(cands)
    reqs += custom_reqs
    reqs = drop_off(doc, reqs, kind)
    verdicts = gstate.read(state / "verdicts.json")
    new, standing = [], []
    for r in reqs:
        v = verdicts.get(r.id)
        if v and v.get("verdict") == "PASSED":
            continue
        (standing if v and v.get("verdict") == "NOT PASSED" else new).append(r)
    if new or standing:
        write_inputs(gstate, state, new, folder / name)
        write_due(gstate, state, name, reqs, new)
    parts.append(f"Script gates passed. Judge gates: {len(reqs)} in all, "
                 f"{len(reqs) - len(new) - len(standing)} passed earlier with the same input"
                 + (f", {len(standing)} not passed with the same input" if standing else "") + ".\n")
    if new:
        parts.append(runner_step(folder, name, len(new)))
    elif standing:  # nothing to run: the report of the judges' last answers is written here
        import collect_judges
        parts.append(f"JUDGE GATES — {collect_judges.report(folder, name)} (the input of these judges did not "
                     "change since they said so).")
    if standing or new:
        parts.append(report_step("the file"))
        _status(gstate, state, name, "judges pending" if new else "judge failures",
                [f"{r.gate} {r.unit}" for r in standing + new])
    else:
        skipped = [n for n in notices if "did not run" in n]
        every = "Every gate that ran passed (see the notes: not every gate ran)" if skipped else "Every gate passed"
        waiting = [lvl for lvl in range(1, upto + 1) if approvals[lvl] in ("no", "stale")]
        if kind == "text":
            unwritten = [n for n in notices if "not written yet" in n]  # plan_elements_written.NOT_WRITTEN_YET
            parts.append(f"{every} on the text written so far." + (
                f" The text is NOT done: {unwritten[0].split(';')[0]}; write them in the plan's order." if unwritten
                else ""))
        elif not waiting:
            parts.append(f"{every}; the plan is approved down to its {LEVELS[upto]}.")
        else:
            parts.append((f"{every}. " if skipped else "") +
                         approval_step(gstate, JudgeRequest, doc, waiting[0], state))
        status = "passed" if not skipped else "passed, some gates did not run"
        if kind == "text" and any("not written yet" in n for n in notices):
            status += ", text not complete"
        _status(gstate, state, name, status, skipped)
    history.note(folder, kept, [], [r.id for r in reqs])
    log(f"{folder} {name}: {len(new)} judges due, {len(standing)} standing")
    _out("\n".join(parts))


# ---------------------------------------------------------------- the research's fact base

RESEARCH_CHANGES = ("fetch", "save", "add", "remove", "merge", "merge-attribute", "gap", "finish")


def research_folders(data: dict) -> list[Path]:
    """The document folders whose fact base this call changed: a Bash command that runs `research.py <change>
    <folder>`, or a Write/Edit of `<folder>/research/facts.json` or `<folder>/FACTS.md`; only folders with a
    BRIEF.md."""
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    found = []
    if data.get("tool_name") == "Bash":
        cmd = tool_input.get("command") or ""
        for m in re.finditer(r"research\.py[\"']?\s+([\w-]+)\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd):
            if m.group(1) in RESEARCH_CHANGES:
                found.append(os.path.expandvars(os.path.expanduser(m.group(2).strip("\"'"))))
        # a command that writes the base or the dossier some other way (python, sed, a redirection)
        if re.search(r">|\b(?:tee|sed|python3?|jq|mv|cp|perl|rm)\b", cmd):
            for m in re.finditer(r"([^\s\"'<>|;&]*?)/?(?:research/facts\.json|FACTS\.md)\b", cmd):
                found.append(os.path.expandvars(os.path.expanduser(m.group(1) or ".")))
        found = [os.path.join(cwd, f) for f in found]
    elif data.get("tool_name") in ("Write", "Edit", "MultiEdit") and tool_input.get("file_path"):
        p = Path(os.path.expanduser(tool_input["file_path"]))
        if p.name == "facts.json" and p.parent.name == "research":
            found.append(str(p.parent.parent))
        elif p.name == "FACTS.md":
            found.append(str(p.parent))
    out = []
    for f in found:
        folder = Path(os.path.realpath(f))
        if (folder / "BRIEF.md").exists() and folder not in out:
            out.append(folder)
    return out


def research_main(data: dict) -> bool:
    """The gates of the fact base (fact-quoted, sources-conflict) on every change of it. Silent when they pass: the
    readers add facts many times and `add` already answers each one. True when this call is handled here."""
    folders = research_folders(data)
    if not folders:
        return False
    gate_paths()
    from fact_quoted import gate_fact_quoted
    from sources_conflict import gate_sources_conflict
    reports = []
    for folder in folders:
        # not through GATES.md `gates_off`: a document cannot let an unchecked fact into its base
        fails = gate_fact_quoted(folder) + gate_sources_conflict(folder)
        if fails:
            reports.append(f"unslopable gates on the fact base of {folder} — SCRIPT GATES NOT PASSED ({len(fails)}):\n"
                           + "".join(f"{k}. {f.line()}\n" for k, f in enumerate(fails[:MAX_LIST], 1))
                           + "Fix every point with `research.py`: a fact that fails fact-quoted did not come in "
                           "through `research.py add`; take it out with `research.py remove <folder> <id> --reason "
                           "<why>` and add it again through `add`. This hook runs again.")
            log(f"{folder} fact base: {len(fails)} script failures")
    if reports:
        _out("\n\n".join(reports))
    return True


# ---------------------------------------------------------------- figure files

SUBAGENT_NOTE = ("If you cannot start a subagent, do not start the gate runner below: fix what you can, then end "
                 "your answer with the whole «START ONE AGENT NOW» block as it stands, so the session that started "
                 "you starts it and sends you back the report file on NOT PASSED.")


def figure_main(data: dict) -> bool:
    """The gates of figure files: a Write/Edit of an image under a document's `figures/`, or a Bash command that
    names a path in a document's `figures/` and changed figure files there. True when this call is handled here
    (every Bash call is)."""
    tool = data.get("tool_name")
    tool_input = data.get("tool_input") or {}
    if tool == "Bash":
        if "figures" not in (tool_input.get("command") or ""):
            return True
    elif tool not in ("Write", "Edit", "MultiEdit") or not tool_input.get("file_path"):
        return False
    gate_paths()
    import figure_files
    import state as gstate
    if tool == "Bash":
        targets = [(folder, figure_files.changed(folder, gstate))
                   for folder in figure_files.bash_folders(tool_input["command"], data.get("cwd") or "")]
    else:
        written = os.path.realpath(os.path.expanduser(tool_input["file_path"]))
        found = figure_files.figure_file(written) or figure_files.image_of_prompt(written)
        if not found:
            return False
        targets = [(found[0], [found[1]])]
    reports = []
    for folder, rels in targets:
        if not rels:
            continue
        text, failed = figure_report(gstate, folder, rels)
        reports.append(text)
        for rel in rels:  # seen only once its script gates passed (a failed raster is gated again later)
            figure_files.settle(folder, rel, rel not in failed, gstate)
    if reports:
        _out("\n\n".join(reports))
    return True


def figure_report(gstate, folder: Path, rels: list) -> tuple[str, set]:
    """The gates' report on these figures, and the figures whose script gates failed."""
    from docs import load
    from figure_gates import custom_figure_gates, run_figure
    from judge_gates import JudgeRequest
    from project_gates import project_gates
    from common import drop_off
    import history
    doc = load(folder)
    state = folder / ".gates"
    state.mkdir(exist_ok=True)
    notices: list = []
    fails, reqs, file_of, failed, kept = [], [], {}, set(), []
    for rel in rels:
        n = history.entry(folder, rel)  # kept by track(); the gates note their outcome on it
        f1, r1 = run_figure(doc, rel, notices)
        f1, r1 = drop_off(doc, f1), drop_off(doc, r1)
        f2, r2 = custom_figure_gates(folder, rel)
        f3, r3 = project_gates(doc, rel, JudgeRequest)  # the project's own library (.unslopable/gates/)
        f2, r2 = f2 + f3, r2 + r3
        if f1 or f2:
            failed.add(rel)
        fails += f1 + f2
        reqs += r1 + r2
        file_of.update({r.id: folder / rel for r in r1 + r2})
        kept.append((n, [f.line() for f in f1 + f2], [r.id for r in r1 + r2]))
    fails = list({f.line(): f for f in fails}.values())  # a broken project library is reported once, not per figure
    for n, lines, ids in kept:  # judges run only once every figure of the call passed its script gates
        history.note(folder, n, lines, [] if fails else ids)
    names = ", ".join(rels)
    this = "this file" if len(rels) == 1 else "these files"
    parts = [f"unslopable gates on the figure{'s' if len(rels) > 1 else ''} {names} (in {folder}). Gate results go "
             f"to you because you wrote {this}; fix only {this}. {SUBAGENT_NOTE}\n"]
    if notices:
        parts.append("Notes: " + "; ".join(notices) + ".\n")
    if fails:
        parts.append(f"SCRIPT GATES — NOT PASSED ({len(fails)}):\n" +
                     "".join(f"{k}. {f.line()}\n" for k, f in enumerate(fails[:MAX_LIST], 1)) +
                     "\nFix every point, then write the file again; this hook runs again. An image a shell command "
                     "made (a screenshot, a generated image) whose fix is in another file: once that file is fixed, "
                     "run `ls figures` (or write the image's prompt file), and its gates run again. The judge gates "
                     "run once the script gates pass.")
        _status(gstate, state, names, "script failures", [f.line() for f in fails])
        log(f"{folder} {names}: {len(fails)} script failures")
        return "\n".join(parts), failed
    verdicts = gstate.read(state / "verdicts.json")
    new = [r for r in reqs if not verdicts.get(r.id)]
    standing = [r for r in reqs if verdicts.get(r.id, {}).get("verdict") == "NOT PASSED"]
    for r in new:  # each request records the figure it is about
        write_inputs(gstate, state, [r], file_of[r.id])
    if new or standing:
        write_due(gstate, state, names, reqs, new)
    parts.append(f"Script gates passed. Judge gates: {len(reqs)} in all, "
                 f"{len(reqs) - len(new) - len(standing)} passed earlier with the same input"
                 + (f", {len(standing)} not passed with the same input" if standing else "") + ".\n")
    if new:
        parts.append(runner_step(folder, names, len(new)))
    elif standing:
        import collect_judges
        parts.append(f"JUDGE GATES — {collect_judges.report(folder, names)} (the input of these judges did not "
                     "change since they said so).")
    if standing or new:
        parts.append(report_step(f"the figure{'s' if len(rels) > 1 else ''}"))
        _status(gstate, state, names, "judges pending" if new else "judge failures",
                [f"{r.gate} {r.unit}" for r in new + standing])
    else:
        parts.append(f"Every gate passed on the figure {names}.")
        _status(gstate, state, names, "passed", [])
    log(f"{folder} {names}: {len(new)} judges asked, {len(standing)} standing")
    return "\n".join(parts), failed


def _status(gstate, state: Path, name: str, status: str, items: list) -> None:
    try:
        gstate.update(state / "last_run.json", lambda d: (d.clear(), d.update(
            {"file": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "status": status, "items": items})))
    except OSError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break a write because of this hook, but say it did not run
        log(f"hook error: {e!r}")
        _out(f"unslopable gates: the gate hook failed ({e!r}); the gates did not run on this write. Log: {LOG}")
    sys.exit(0)
