#!/usr/bin/env python3
"""The gate runner's tool: hands out the judges due on one gated file, records their verdicts, writes the report.

  collect_judges.py next   <document folder> <file> [--max 20]
  collect_judges.py record <document folder> <agentId|transcript> [<agentId|transcript> …] [--timeout 120]
  collect_judges.py report <document folder> <file>

<file> is the gated file as the gate hook names it (`TEXT.md`, `PLAN.md`, `figures/x.svg`). The hook writes the
judges of each run to `.gates/due.json` (per file: every judge of the run and the ones due now), their inputs to
`.gates/inputs/` and their index to `.gates/requests.json`, then asks the writing stage to start one subagent,
`unslopable:gate-runner` (agents/gate-runner.md). The runner loops:

- `next` prints the next round of due judges (at most --max, default 20) with each one's subagent_type and prompt, or
  NONE. A judge with no verdict is served again, twice at most per run (attempts in `.gates/runner.json`).
- The runner starts them, then `record` gets each judge's transcript, from the path an Agent result gives, or from
  the agentId it gives (the transcript `<config>/projects/*/*/subagents/agent-<agentId>.jsonl`), reads the judge_id
  from the judge's prompt and the verdict from its last answer (PASSED / NOT PASSED for a gate judge, APPROVED / NOT
  APPROVED for the plan-approval judge), and records it in `.gates/verdicts.json`, where gate_run.py finds it, so a
  judge whose input did not change is not run again. It prints counts only, never an answer.
- `report` writes `.gates/report-<file>.md` (every NOT PASSED of the run with the judge's quotes and reasons, and
  the judges with no verdict) and prints one line, the runner's whole answer: `PASSED`, or
  `NOT PASSED — N places, details in <report>`.

Exit 0 always.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates" / "lib"))
import state as gstate  # noqa: E402
from wait_critic import final_text  # noqa: E402

USAGE = ("usage: collect_judges.py next <folder> <file> [--max N] | record <folder> <agentId|transcript> … "
         "[--timeout S] | report <folder> <file>")
ROUND = 20  # judges in one round of the runner
TRIES = 2  # rounds a judge with no verdict is served in one run


# ---------------------------------------------------------------- reading a judge's transcript

def judge_id(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                if d.get("type") != "user":
                    continue
                c = (d.get("message") or {}).get("content")
                if isinstance(c, list):
                    c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
                m = re.search(r"judge_id:\s*(\S+)", c or "")
                return m.group(1) if m else None
    except OSError:
        return None
    return None


def verdict(text: str) -> str:
    """The verdict word of the first lines that hold text: code fences, bold and a «Verdict:» label are skipped."""
    lines = [ln.strip().strip("*`#>_ ").strip() for ln in text.splitlines()]
    lines = [re.sub(r"^verdict\s*[:\-–—]\s*", "", ln, flags=re.I).strip("*_ ") for ln in lines if ln]
    for ln in lines[:3]:
        up = ln.upper()
        for v in ("NOT PASSED", "PASSED", "NOT APPROVED", "APPROVED"):
            if up.startswith(v):
                return v
    return "UNCLEAR"


def _config_dirs() -> list[Path]:
    dirs = [Path(os.environ["CLAUDE_CONFIG_DIR"]).expanduser()] if os.environ.get("CLAUDE_CONFIG_DIR") else []
    return dirs + [Path.home() / ".claude"]


def transcript(ref: str, near: list[Path]) -> Path | None:
    """A judge's transcript: `ref` itself when it is a file (an Agent result's output_file), else the transcript of
    the subagent whose agentId `ref` is. `near` holds folders where earlier transcripts were found; looked in first."""
    p = Path(ref).expanduser()
    if p.is_file():
        return p
    aid = ref.strip().removeprefix("agent-")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", aid):
        return None
    name = f"agent-{aid}.jsonl"
    for d in near:
        if (d / name).is_file():
            return d / name
    for base in _config_dirs():
        for pattern in ("projects/*/*/subagents/", "projects/*/*/subagents/*/"):
            hits = sorted(glob.glob(str(base / pattern / name)), key=os.path.getmtime)
            if hits:
                near.insert(0, Path(hits[-1]).parent)
                return Path(hits[-1])
    return None


# ---------------------------------------------------------------- next round

def judge_lines(state: Path, reqs: list[tuple[str, dict]]) -> str:
    return "".join(f"{k}. subagent_type \"{m['agent']}\", description \"gate {m['gate']}\", prompt (these two lines):\n"
                   f"   judge_id: {jid}\n   input: {state / 'inputs' / (jid + '.md')}\n"
                   for k, (jid, m) in enumerate(reqs, 1))


def next_round(folder: Path, name: str, most: int = ROUND) -> str:
    state = folder / ".gates"
    run = gstate.read(state / "due.json").get(name)
    if not run:
        return f"NONE (no gate run on {name} in {state / 'due.json'})"
    verdicts = gstate.read(state / "verdicts.json")
    index = gstate.read(state / "requests.json")
    tries = gstate.read(state / "runner.json")
    open_ = [j for j in run.get("due", []) if j not in verdicts and j in index and tries.get(j, 0) < TRIES]
    if not open_:
        return "NONE"
    batch = open_[:most]
    gstate.update(state / "runner.json", lambda d: d.update({j: d.get(j, 0) + 1 for j in batch}))
    more = len(open_) - len(batch)
    return (f"ROUND: {len(batch)} judges" + (f" ({more} more after these)" if more else "") +
            ". Start them all in one message:\n" + judge_lines(state, [(j, index[j]) for j in batch]))


# ---------------------------------------------------------------- record

def record(folder: Path, refs: list[str], timeout: float = 120.0) -> str:
    state = folder / ".gates"
    near: list[Path] = []
    paths = {ref: transcript(ref, near) for ref in refs}
    deadline = time.time() + timeout
    done: dict[str, str] = {}
    while True:
        for ref, p in paths.items():
            if p and ref not in done:
                t = final_text(str(p))
                if t is not None:
                    done[ref] = t
        if len(done) == sum(1 for p in paths.values() if p) or time.time() >= deadline:
            break
        time.sleep(2)
    index = gstate.read(state / "requests.json")
    verdicts, counts = {}, {}
    for ref, p in paths.items():
        jid = judge_id(str(p)) if p else None
        if p is None or ref not in done:
            key = "no transcript" if p is None else "not finished"
        else:
            text = done[ref].strip()
            v = verdict(text)
            key = v if v != "UNCLEAR" else "no verdict"
            if v != "UNCLEAR" and jid in index:
                meta = index[jid]
                verdicts[jid] = {"verdict": "PASSED" if v == "APPROVED" else
                                 ("NOT PASSED" if v == "NOT APPROVED" else v),
                                 "answer": v, "text": text, "gate": meta.get("gate"), "unit": meta.get("unit"),
                                 "time": time.strftime("%Y-%m-%d %H:%M:%S")}
            elif jid not in index:
                key = "unknown judge_id"
        counts[key] = counts.get(key, 0) + 1
    try:
        gstate.update(state / "verdicts.json", lambda d: d.update(verdicts))
    except OSError as e:
        return f"could not record the verdicts in {state / 'verdicts.json'}: {e}"
    return f"recorded {len(verdicts)} of {len(refs)}: " + ", ".join(f"{k} {n}" for k, n in sorted(counts.items()))


# ---------------------------------------------------------------- report

def report_path(folder: Path, name: str) -> Path:
    return folder / ".gates" / f"report-{re.sub(r'[^A-Za-z0-9.]+', '_', name)}.md"


def _points(text: str) -> tuple[str, int]:
    """A NOT PASSED answer without its verdict line and code fences, and the number of places it lists."""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and verdict(lines[0]) in ("NOT PASSED", "NOT APPROVED"):
        lines.pop(0)
    body = "\n".join(lines).strip()
    return body, max(1, sum(1 for ln in lines if re.match(r"\s*[-*•]\s|\s*\d+[.)]\s", ln)))


def report(folder: Path, name: str) -> str:
    """Write the report of the last gate run on `name` and return the runner's one-line answer."""
    state = folder / ".gates"
    run = gstate.read(state / "due.json").get(name) or {}
    verdicts = gstate.read(state / "verdicts.json")
    index = gstate.read(state / "requests.json")
    ids = run.get("all", [])
    failed = [j for j in ids if verdicts.get(j, {}).get("verdict") == "NOT PASSED"]
    undecided = [j for j in ids if j not in verdicts]
    path = report_path(folder, name)
    if not failed and not undecided:
        line = "PASSED"
        body = f"# Gate report · {name}\n\nPASSED: every one of the {len(ids)} judges of this run passed.\n"
    else:
        blocks, places = [], 0
        for k, j in enumerate(failed, 1):
            v = verdicts[j]
            text, n = _points(v.get("text", ""))
            places += n
            blocks.append(f"## {k}. {v.get('gate') or index.get(j, {}).get('gate', '?')} · "
                          f"{v.get('unit') or index.get(j, {}).get('unit', '')}\n\n{text}\n")
        if undecided:
            places += len(undecided)
            blocks.append(f"## No verdict ({len(undecided)})\n\nThese judges gave no verdict: nothing to fix for "
                          "them in the file. They run again on the next write of the file.\n\n" +
                          "".join(f"- {index.get(j, {}).get('gate', '?')} · {index.get(j, {}).get('unit', '')}\n"
                                  for j in undecided))
        line = f"NOT PASSED — {places} place{'' if places == 1 else 's'}, details in {path}"
        passed = len(ids) - len(failed) - len(undecided)
        body = (f"# Gate report · {name}\n\n{line.split(', details')[0]} ({len(ids)} judges: {passed} passed, "
                f"{len(failed)} not passed, {len(undecided)} with no verdict).\n\n"
                "Fix the file at each place below, point by point. Do not argue with a judge and do not edit another "
                "stage's file. Then write the file again: the gates run again, and only the judges whose input "
                "changed run again.\n\n" + "\n".join(blocks))
    try:
        path.write_text(body, encoding="utf-8")
    except OSError as e:
        return f"NOT PASSED — the report could not be written ({e})"
    return line


# ---------------------------------------------------------------- main

def _opt(argv: list[str], flag: str, default: float) -> tuple[list[str], float | None]:
    if flag not in argv:
        return argv, default
    k = argv.index(flag)
    try:
        return argv[:k] + argv[k + 2:], float(argv[k + 1])
    except (IndexError, ValueError):
        return argv, None


def main(argv: list[str]) -> int:
    cmd, args = (argv[0], argv[1:]) if argv else ("", [])
    if cmd == "next":
        args, most = _opt(args, "--max", ROUND)
        if len(args) != 2 or not most:
            print(USAGE)
            return 0
        print(next_round(Path(args[0]), args[1], int(most)))
    elif cmd == "record":
        args, timeout = _opt(args, "--timeout", 120.0)
        if len(args) < 2 or timeout is None:
            print(USAGE)
            return 0
        print(record(Path(args[0]), args[1:], timeout))
    elif cmd == "report":
        if len(args) != 2:
            print(USAGE)
            return 0
        print(report(Path(args[0]), args[1]))
    else:
        print(USAGE)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as e:  # noqa: BLE001 — the runner must see it, and the exit stays 0
        print(f"collect_judges failed: {e!r}")
        sys.exit(0)
