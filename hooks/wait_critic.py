#!/usr/bin/env python3
"""Wait for a background subagent to finish and print only its final answer.

  wait_critic.py <output_file> [timeout_s=150]

In the desktop app the Agent tool always runs a subagent in the background; its answer comes back
later as a task notification, in a turn of its own, where the app refuses to start sessions. So
the chat waits for the ambiguity critic in the same turn with this script and acts on its answer
there. <output_file> is the path the Agent tool result gives (the subagent's .jsonl transcript).
Exit 0 and the answer text; exit 1 and «TIMEOUT» if it is not done in time.
"""
import json
import os
import sys
import time


def final_text(path):
    """The text of the subagent's last turn once it has ended, else None."""
    if not os.path.exists(path):
        return None
    last = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message") or {}
            texts = [b.get("text", "") for b in msg.get("content") or []
                     if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()]
            if texts:
                last = (msg.get("stop_reason"), "\n".join(texts))
            elif any(isinstance(b, dict) and b.get("type") == "tool_use" for b in msg.get("content") or []):
                last = None  # it went on working after that text
    if last and last[0] == "end_turn":
        return last[1]
    return None


def main():
    path = sys.argv[1]
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 150
    deadline = time.time() + timeout
    while time.time() < deadline:
        text = final_text(path)
        if text is not None:
            print(text)
            return 0
        time.sleep(1)
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    sys.exit(main())
