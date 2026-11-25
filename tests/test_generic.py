"""The plugin stays generic: no file of it carries words of one document it was tried on.

A test document once leaked its names and examples into the
gates, the judges and the tests. Examples in the plugin are abstract (a house, a pump, apples). This test fails when
a word of that document comes back. The slop word lists in gates/data/slop/ are measured corpora and are left out:
a word such as «dialogues» is legitimate there.
"""
from __future__ import annotations

try:  # first: the plugin's cache goes to a temp folder (tests/isolate.py)
    from tests import isolate  # noqa: F401
except ImportError:
    import isolate  # noqa: F401

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = ("gates/data/slop/",)
SKIP_FILES = ("tests/test_generic.py",)
WORDS = re.compile(
    r"claude[ -]tag|\bslack\b|owasp|\bASI ?\d\d\b|\bLLM ?\d\d\b|\bdialog(?:s|ue|ues)?\b|\bmodals?\b|"
    r"anthropic|\bokta\b|\bjira\b|\bmcp\b|agent proxy|personal connectors?|channel sessions?",
    re.I)


def plugin_files() -> list[Path]:
    """Tracked and untracked files of the repository, ignored ones left out."""
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [ROOT / f for f in out if not f.startswith(SKIP_DIRS) and f not in SKIP_FILES and (ROOT / f).is_file()]


def hits(text: str) -> list[tuple[int, str]]:
    return [(n, m.group(0)) for n, line in enumerate(text.splitlines(), 1) for m in WORDS.finditer(line)]


class Generic(unittest.TestCase):
    def test_no_word_of_the_test_document(self):
        found = []
        for path in plugin_files():
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # images and other binary files
            found += [f"{path.relative_to(ROOT)}:{n}: {w}" for n, w in hits(text)]
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_the_guard_catches_the_words(self):
        bad = ("Claude Tag in Slack", "OWASP item LLM01", "ASI03", "the modal closes", "a dialog box",
               "the Agent Proxy", "personal connectors", "an MCP server")
        for s in bad:
            self.assertTrue(hits(s), s)
        good = ("a house with a pump", "Claude Code runs the hook", "a modality", "dialect", "slacken",
                "apples and pears")
        self.assertEqual([s for s in good if hits(s)], [])


if __name__ == "__main__":
    unittest.main()
