#!/usr/bin/env python3
"""PostToolUse hook on AskUserQuestion, registered by the brief skill when it is invoked.

After every answer the author gives during the brief, it tells the chat to run the `brief-critic`
subagent on that question and answer, wait for it in the same turn, and ask the author the
follow-up questions it returns before going on. A hook cannot start a subagent itself, so it only
adds that instruction as context.

It stays silent when this chat has not written a BRIEF.md yet (the question was not part of a
brief), or when the last BRIEF.md it wrote is already approved (first line «Approved by …»).
Anything unexpected -> no output.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = Path(os.environ.get("UNSLOPABLE_CACHE") or Path.home() / ".cache" / "unslopable") / "brief_followup.log"
CUT = 3000


def log(msg):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def brief_path(transcript):
    """The last BRIEF.md this chat wrote or edited, from its transcript."""
    found = None
    if not transcript or not os.path.exists(transcript):
        return None
    with open(transcript, encoding="utf-8", errors="replace") as f:
        for line in f:
            if "BRIEF.md" not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            for b in (d.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    p = (b.get("input") or {}).get("file_path", "")
                    if p.endswith("BRIEF.md"):
                        found = p
    return found


def approved(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.readline().startswith("Approved by")
    except OSError:
        return False


def qa(tool_input, tool_response):
    """The questions asked and the author's answers, as plain text."""
    lines = []
    for q in (tool_input or {}).get("questions") or []:
        lines.append(f"Q: {q.get('question', '')}")
        for o in q.get("options") or []:
            lines.append(f"  option: {o.get('label', '')} - {o.get('description', '')}")
    answers = (tool_response or {}).get("answers") if isinstance(tool_response, dict) else None
    if isinstance(answers, dict) and answers:
        for q, a in answers.items():
            lines.append(f"ANSWER to «{q}»: {a}")
    else:
        lines.append("ANSWER (raw): " + json.dumps(tool_response, ensure_ascii=False))
    text = "\n".join(lines)
    return text if len(text) <= CUT else text[:CUT] + " […]"


def main():
    data = json.load(sys.stdin)
    if data.get("tool_name") != "AskUserQuestion":
        return
    path = brief_path(data.get("transcript_path", ""))
    if not path:
        log("no BRIEF.md in this chat, silent")
        return
    if approved(path):
        log(f"{path} approved, silent")
        return
    exchange = qa(data.get("tool_input"), data.get("tool_response"))
    log(f"{path} critic asked")
    ctx = (
        "Brief follow-up check (unslopable hook). The author just answered a brief question. "
        "Before you write anything else or ask the next question, run the subagent "
        "`unslopable:brief-critic` (Agent tool, subagent_type \"unslopable:brief-critic\") with "
        "exactly the brief below and nothing of your own.\n"
        f"<brief>\nbrief_file: {path}\n{exchange}\n</brief>\n"
        "The Agent tool runs it in the background, so wait for it in this same turn: right after "
        f"the Agent call, run Bash `python3 {HERE / 'wait_critic.py'} <output_file>` (the "
        "output_file path from the Agent result; Bash timeout 180000). It prints only the critic's "
        "answer. Ignore the task notification that arrives later. First write the answer into "
        "BRIEF.md as usual. Then ask the author every FOLLOWUP the critic returns, one per "
        "AskUserQuestion call, with its options as given, and update BRIEF.md after each answer. "
        "Only when the critic answers NONE, go on to the next part of the brief. If the subagent "
        "fails or the script prints TIMEOUT, say so in one line and go on.")
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": ctx}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never break the interview because of this hook
        log(f"hook error: {e!r}")
    sys.exit(0)
