#!/usr/bin/env python3
"""PreToolUse hook on Write/Edit: the document pipeline does not write to Claude Code's shared memory.

Every document has its own brief and its own rules, so a rule learned while making one document does not belong
in the memory every other chat reads. In a chat that is making a document (it has written a BRIEF.md), a write
into a `memory/` folder under ~/.claude/projects is held for the author's approval, and the reason tells the chat
to keep the rule in the document's folder instead. Other chats are left alone. Anything unexpected -> no output.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brief_followup import brief_path  # noqa: E402

PROJECTS = str(Path.home() / ".claude" / "projects") + os.sep


def main():
    data = json.load(sys.stdin)
    path = (data.get("tool_input") or {}).get("file_path", "")
    if not path:
        return
    path = os.path.realpath(os.path.expanduser(path))
    if not (path.startswith(PROJECTS) and f"{os.sep}memory{os.sep}" in path):
        return
    brief = brief_path(data.get("transcript_path", ""))
    if not brief:
        return
    folder = os.path.dirname(brief)
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": (
            "unslopable: this chat is making a document, and the pipeline does not write to the shared memory "
            "unless the author asks for it. Keep a rule for this document in its folder "
            f"({folder}) instead.")}}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
