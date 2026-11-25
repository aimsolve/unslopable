#!/usr/bin/env python3
"""PreToolUse hook: no recommended option, no preference order.

The author clicks a recommended or first option without reading it, which defeats the question
(2026-11-13). So before AskUserQuestion and the app's next-step box (mcp__ccd_turn__wrap_up)
reach him, this hook:
  - removes "(Recommended)" and similar markers, English and Russian, from option labels and
    descriptions (and from the next-step buttons' labels);
  - shuffles each question's options and the next-step buttons.

The tool input is replaced through hookSpecificOutput.updatedInput, without a permission
decision (see main()). Anything unexpected -> no output, the call goes on as it was.
"""
import json
import random
import re
import sys
import time
from pathlib import Path

LOG = Path.home() / ".claude" / "hooks" / "option_shuffle.log"

WORDS = (r"recommended|recommend|suggested|preferred|my pick|best choice|best option|default|"
         r"рекомендуем\w*|рекомендую|рекомендуется|рекомендован\w*|рекомендац\w*|советую|"
         r"мой выбор|лучший вариант|предпочтительн\w*|по умолчанию|"
         # Ukrainian, Belarusian
         r"рекомендовано|рекомендуємо|раджу|за замовчуванням|мій вибір|найкращий варіант|"
         r"рэкамендую|рэкамендуем|рэкамендавана|раю|па змаўчанні|мой выбар|"
         # Polish
         r"polecan\w*|polecam|zalecan\w*|rekomendowan\w*|rekomenduj\w*|domyśln\w*|mój wybór|najlepsz\w* opcj\w*|"
         # German
         r"empfohlen\w*|empfehle|empfehlung|voreingestellt|meine wahl|beste wahl|"
         # Spanish, Portuguese, Italian, French
         r"recomendad\w*|recomiendo|recomendo|por defecto|predeterminad\w*|mi elección|mejor opción|minha escolha|"
         r"consigliat\w*|raccomandat\w*|predefinit\w*|la mia scelta|"
         r"recommandé\w*|conseillé\w*|par défaut|mon choix|meilleur choix")
# "(Recommended)", "[рекомендую]", "(recommended, fastest)"
BRACKETED = re.compile(r"\s*[\(\[\{]\s*(?:" + WORDS + r")\b[^\)\]\}]{0,40}[\)\]\}]", re.I)
# "Recommended: X", "Рекомендую — X", "Recommended. X"
PREFIX = re.compile(r"^\s*(?:" + WORDS + r")\s*[:\-–—.!]\s*", re.I)
# "X — recommended", "X, рекомендуется", "X recommended"
SUFFIX = re.compile(r"\s*[,:\-–—]?\s*(?:this is\s+)?(?:the\s+)?(?:" + WORDS + r")(?:\s+option)?\s*[.!]?\s*$",
                    re.I)
STARS = re.compile(r"^\s*(?:⭐|🌟|★|✅|👍|👉)+\s*|\s*(?:⭐|🌟|★|✅|👍|👈)+\s*$")


def clean(text):
    if not isinstance(text, str):
        return text
    out = text
    for _ in range(3):  # markers can stack: "⭐ Recommended: X (default)"
        prev = out
        out = BRACKETED.sub("", out)
        out = STARS.sub("", out)
        out = PREFIX.sub("", out)
        out = SUFFIX.sub("", out)
        if out == prev:
            break
    out = out.strip()
    return out if out else text.strip()  # never blank a label that was only a marker


def fix_ask(inp):
    changed = False
    for q in inp.get("questions") or []:
        opts = q.get("options")
        if not isinstance(opts, list):
            continue
        for o in opts:
            for key in ("label", "description"):
                if key in o:
                    new = clean(o[key])
                    if new != o[key]:
                        o[key], changed = new, True
        if len(opts) > 1:
            random.shuffle(opts)
            changed = True
    return changed


def fix_wrap(inp):
    acts = inp.get("actions")
    if not isinstance(acts, list) or not acts:
        return False
    changed = False
    for a in acts:
        if isinstance(a, dict) and "label" in a:
            new = clean(a["label"])
            if new != a["label"]:
                a["label"], changed = new, True
    if len(acts) > 1:
        random.shuffle(acts)
        changed = True
    return changed


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except OSError:
        pass


def main():
    data = json.load(sys.stdin)
    tool, inp = data.get("tool_name", ""), data.get("tool_input") or {}
    before = json.dumps(inp, ensure_ascii=False)
    if tool == "AskUserQuestion":
        changed = fix_ask(inp)
    elif tool.endswith("ccd_turn__wrap_up"):
        changed = fix_wrap(inp)
    else:
        return
    if not changed:
        return
    log(f"{tool} session={data.get('session_id')} before={before[:600]} after={json.dumps(inp, ensure_ascii=False)[:600]}")
    # No permissionDecision: with "allow" Claude Code runs AskUserQuestion without showing it and
    # returns "The user did not answer the questions" (tested 2026-11-13 on 2.1.321). Without a
    # decision the updated input goes through the normal permission flow to the app's permission prompt.
    out = {"hookEventName": "PreToolUse", "updatedInput": inp}
    print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block a question because of this hook
        log(f"hook error: {e!r}")
    sys.exit(0)
