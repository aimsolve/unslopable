---
name: viewer
description: >-
  Opens the document viewer: a local page with a document's timeline — every version of every file of the document
  with what changed, every complaint of a gate judge (with its text and prompt) and every pass, in time order,
  filterable by file, element or gate. Live while the document is being made. Use when the author wants to see what
  happened to a document, its gates or judges ("покажи документ", "что сказали гейты", "open the viewer", "show the
  timeline").
argument-hint: "[document folder]"
---

# Document viewer

The viewer is `viewer/serve.py` of this plugin, two folders up from this skill's base directory: below, `S` stands
for `python3 <this skill's base directory>/../../viewer/serve.py` (write the whole path).

1. Start the server so it outlives this chat (Bash, as it stands, one command):
   `mkdir -p ~/.cache/unslopable && nohup S > ~/.cache/unslopable/viewer.log 2>&1 &`
   If a viewer already runs, this one stops at once and the running one is used (one running older code of the
   plugin is replaced).
2. Then open the page: `S --open [<document folder>]` (it waits a few seconds for the viewer; it never serves
   itself). Pass the folder when the author named one (the argument of this skill, or a folder named in the
   conversation); otherwise pass none and the author picks the document on the page, from every document the
   plugin has seen.
3. Answer with the URL the command printed, one line. If it says the port is taken by another program, run both
   commands again with `--port 8766` after `S`.

The page reads the document folder every 3 seconds, so a document being made shows its new versions and verdicts
without a reload. It changes no file of the document.
