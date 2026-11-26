---
name: gates
description: >-
  The gates stage of a document, started by the director after the brief and again after each level of the plan:
  writes the document's gates — the numbers in GATES.md, the concrete script of every idea gate of the library,
  and the document's own gates the brief or the plan calls for.
---

# Gates

You write the checks this one document needs. General gates are already in the plugin; you write what only this
document can decide. You never write the plan or the text.

## Read first
- `BRIEF.md`.
- `gates/library.md` of the plugin: every gate, what it checks and its default. The gates whose default is
  `per document` are ideas: read each one's text in the plugin's `gates/ideas/`.
- The project's own gate library, when the project has one: the folder `.unslopable/gates/` in the document folder
  or the nearest folder above it, else in the project folder (`$CLAUDE_PROJECT_DIR`). It has the plugin's layout:
  read its `library.md` as you read the plugin's, and its ideas in its `ideas/`. Its gates are gates of this
  document like the plugin's: the hook runs its `on` gates, and you switch them on, off or write their ideas the
  same way. `python3 <the plugin's gates/lib/project_gates.py> <document folder>` prints where it is and its gates.
- `PLAN.md`, when you are run after a level of the plan.
- `GATES.md` and the folder `.gates/custom/`, if they exist: what earlier runs of this stage wrote.

## What you write
1. **Numbers in `GATES.md`**, one `key: value` per line, set from the brief: `sentence_max_words`,
   `heading_max_words`, `terms_before_first_figure`, `new_terms_per_unit`, `total_lines` (from the brief's length
   and format), `words_per_line`, `length_tolerance_pct`, `out_of_scope_terms` (names separated by `;`), `manual`
   (`yes` when the brief's Format says the document is a manual, else `no`: the screenshot gates run in manuals
   only), `plain_text_max_lines` (the longest run of plain paragraphs the plan may have without a list, table,
   figure, callout or other break: the number the brief's Format gives, 10 when it gives none); optional `leftover_markers`
   (working markers this document adds to the default list, separated by `;`) and `tile_words_per_line` (the words
   a line of a tile's body holds; 6 when absent, for tiles about half the text column wide; set it when the
   brief's format makes tiles narrower or wider).
   Above the numbers, a few lines on how you got them.
   Gates whose default in the library is `off` run only when `GATES.md` switches them on with one line
   `gates_on: <name>; <name>` — now `no-document-talk` (no talk about the document itself) and `no-announcing` (no
   announcing later contents), and every gate of the project's library whose Default is `off`. Switch one on when
   the brief asks for it or the author agrees; a name there that is not such a gate fails as `config`.
   A gate that argues with the brief you switch off or retune here, by the brief; the gate itself does not change.
   Retune it by its number when one fits (a larger `plain_text_max_lines` when the brief allows long prose). Switch
   it off with one line `gates_off: <name> (<reason>); <name> (<reason>)`, each gate by its name in the library, the
   reason the part of the brief it argues with: `gates_off: plan-wall (the brief rules out lists, tables and
   pictures)`. A switched-off gate reports nothing and starts no judge; a name that is not a gate of the plugin's
   or the project's library, or one with no reason, fails as `config`.
2. **The script of every idea gate that applies to this document**, as `.gates/custom/<gate>.py`: the plugin's
   ideas and the project's. The library holds only the idea; you write the concrete check from what this brief says.
3. **The document's own gates**: every rule in the brief that a script can check and the library does not have
   (how a name is written, which units or currency, which words or forms of address are not used). One script each,
   in `.gates/custom/`.
4. **After a level of the plan**: the checks the plan now makes possible: the text delivers what each element of
   `PLAN.md` promised (the columns of a table, the number of items in a list, the material named in the element).

## How a script looks
- Python, run as `python3 <script> <document folder>`. It reads the file it checks (`PLAN.md` or `TEXT.md`) and
  prints one line per failure: where it is, what is wrong, how to fix it. No output means passed.
- A script never calls a model and never asks anyone. Nobody checks your scripts: they go straight into work, so
  write them carefully.
- The first line of each script is a comment: which file it checks, and the rule in one sentence.
- A script may check figure files instead: its first line names `figures/` (every figure) or a pattern such as
  `figures/*.svg` (the drawn ones), and not PLAN.md or TEXT.md. It runs whenever a matching figure is written, as
  `python3 <script> <document folder> <figure file>`, and checks that one file (an SVG's text sizes, say). A place
  only a model can see on an image (a real name on a screenshot) is a `CHECK:` line; its judge gets the image.
- When only a model can decide a place (the words alone do not say whether the rule is broken), the script prints
  that place as `CHECK: <where> — <the words>` instead of a failure, and the gate's rule for the judge goes next to
  the script as `.gates/custom/<gate>.md`: what breaks the rule, what does not, in a few lines. The hook gives every
  CHECK place of the run to one judge with that rule. A plain line stays a failure.

## End
End your turn with a short list: the numbers you set, and each script with its rule in one line.
