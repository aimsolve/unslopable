# unslopable

A Claude Code plugin for making readable documents with a pipeline of model agents.

## What is here

| Folder | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest |
| `skills/director/` | Runs the stages in order; the entry point for a new document |
| `skills/brief/` | The first stage: interviews the author and writes `BRIEF.md` |
| `skills/research/` | The research stage: the lead agent's skill and `research.py`, the fact base's tool (fetch, add, merge, gaps, finish); the checks are in `gates/lib/facts.py` |
| `agents/brief-critic.md` | Reads each brief answer and returns follow-up questions where it is vague or incomplete |
| `agents/gate-runner.md` | The one agent between a writing stage and its judges: starts every due judge, records the verdicts, answers with one line and a report file |
| `agents/image-generator.md` | Makes one `generated_image` element of the plan: writes the prompt, generates the picture with `images/generate_image.py`, looks at it and redoes it until it shows what the plan says |
| `images/generate_image.py` | The one call of the image model (Google's Gemini): key from `GEMINI_API_KEY`, else `GOOGLE_API_KEY`; model from `UNSLOPABLE_IMAGE_MODEL`, `gemini-nano-banana-2.1` when unset |
| `agents/plan-approver.md` | Stands in for the author at a plan level's approval, judged only against the brief |
| `agents/research-reader.md` | Reads one saved page for the research and puts its facts into the fact base, each with a verbatim quote code checks |
| `hooks/` | `option_shuffle.py` (no recommended options, shuffled), `brief_followup.py` (runs the brief critic after every answer; registered by the brief skill), `gate_run.py` (runs the gates when a plan level or the text is written), `collect_judges.py` (the gate runner's tool: hands out each round of due judges, records their verdicts, writes the report) |
| `gates/library.md` | The list of gates: one row per gate, what it checks, its default, links to its files |
| `gates/scripts/` | One script per gate, named after it (two gates that share one parse share its script): fails places, or finds them for the gate's judge |
| `gates/judges/` | One judge per judge gate (`gate-<gate>.md`): reads one input file, answers PASSED or NOT PASSED with the places; listed in the manifest's `agents`. Two of them are generic: `gate-custom` judges a document's own gates, `gate-project` the gates of a project's library |
| `gates/ideas/` | One text per idea gate: the gates stage writes a document's own script from it |
| `gates/lib/` | Shared code: the document reader (`docs.py`), the script runner (`run_scripts.py`), the judges' inputs (`judge_gates.py`), a project's own gate library (`project_gates.py`), figure files (`figure_files.py`, `figure_gates.py`), the spaCy parsers (`*_en.py`), every version of every file of a document, for its timeline (`history.py`), the tools `weekday.py`, `image_margin.py`, `image_similarity.py` |
| `gates/data/slop/` | The slop word lists the slop-words gate reads |
| `viewer/` | The document viewer, the plugin's UI: `serve.py` (a local server on 127.0.0.1), `timeline.py` (reads a document folder into its timeline) and `page.html`; opened by `skills/viewer/` (`/unslopable:viewer [folder]`) |
| `tests/` | `python3 -m unittest discover -s tests` (`SKIP_SPACY=1` skips the spaCy tests) |

## Stages

```
brief       skill   interview of the author -> BRIEF.md, the document's constitution        (built)
gates       ?       proposes checks from the brief; the author accepts or rejects each
research    session finds the material for the brief's goals, with sources: a lead agent and one reader per page
                    fill a fact base checked by code, which builds the dossier FACTS.md            (built)
references  session finds published documents similar to this one and takes what helps the planner: structure,
                    style, ways of presenting, examples of layout. Runs only if the author wants it
plan        skill   three levels: sections -> subsections -> every element (paragraph, table, diagram), one line
                    each; the author approves each level before the next. Each paragraph gets a size in lines,
                    which the author can feel, and the planner works it out with the author. Runs in a new
                    session the director starts                                               (built)
writer      session one writer session goes through the plan element by element on its own, never in one pass;
                    for tables and diagrams it loads the skills for making them
```

A director skill runs the stages in this order, in the chat the author talks in: it reads where the document
stands from the files in its folder, starts the sessions and asks the author where a decision is theirs. Right after
the brief it asks whether to search for references.

Every stage is a skill. The brief and the plan ask the author, so the author talks in them: the brief runs in the
chat the author talks in; the plan runs in a new session the director starts, so it begins with a clean context.
Research, references and the writer each run as a separate session that the director starts in the Claude desktop
app; its first message invokes the stage's skill with the document's folder. A session is not a subagent, so it can
start subagents itself: this is what lets every judge gate have its own judge. Only judges are agents
(`agents/*.md`). The plugin therefore works only in the Claude desktop app, not in the terminal; that is accepted. Gates are written after the brief and again after each level of the plan; the agent that
writes them sets the tolerance, e.g. a paragraph's size in lines plus or minus some.

## Hard rules

- No Python that orchestrates the stages, no direct call of Claude from a script, no `claude -p`. Everything that
  Claude does runs inside Claude Code: skills, sessions started by the desktop app, subagents, hooks. A hook or an
  agent may run a script; a script never calls Claude back. A script may call another model, such as an image
  model.

## Gates: decided

- Material: the planner and the writer get paths to the material and work with what is there: the research folder when there was research, otherwise the author's base. For example: the project's knowledge base, the product's downloaded docs and a folder of screenshots (path only, no descriptions). The writer uses only the screenshots the plan names. With a knowledge base, a plan element's `facts:` field lists the base's files it draws on, separated by commas; this is a frame for the writer, who has the same access to the whole base as the planner and may use other files too.
- Screenshots in later documents are taken or picked by the illustrator after the plan, per plan element.
- The plan is one file, a nested list: sections, in them subsections, in them elements; each level is added to the same file. Every item keeps all its fields (heading, what it says, kind, material, size in lines). Headings in the plan are working titles; the writer may change them, and no gate compares the text's headings with the plan's. Replaces the three `PLAN-1/2/3.md` tables.
- The planner reads the gates as criteria in words (what must be true of the plan), not the scripts, thresholds or judge prompts.
- The plan starts with a clean context: the planner reads the brief from `BRIEF.md`, not from the brief interview's conversation.
- Research only when material comes from the web. When the author already has a knowledge base they trust (their own base, or scraped official documentation such as a vendor's manual), there is no researcher: the planner works with that base directly. How the two cases are told apart: the brief interview asks whether material exists; if it does, it asks where it lies and the paths go into `MATERIAL.md` next to the brief (separate from the brief); if there is none, the director starts the researcher. The director passes the paths on to the planner and the writer.
- Research takes the scheme of an article factory's research whole (`skills/research/`). A lead agent
  (the research session, on Opus) searches the web with WebSearch until every goal of the brief has been looked for
  or the budget is spent, has `research.py fetch` save each page it picks as plain text with its date (stdlib, no
  model; WebFetch only for a page the script cannot read, and such a page is marked as read through WebFetch), at
  most 10 saved pages, and hands each page to a reader (`agents/research-reader.md`, Sonnet), all at once. A reader
  puts every fact of the page that bears on the brief's goals in through `research.py add`, which checks the quote
  against the saved page, the fact's numbers and every part of a date against the quote, and gives the fact a
  number. The lead merges entities, and attributes of one entity, that are one thing (code points out the
  candidates) and lists what the brief asked for and could not be found (`research.py gap`). Choosing what fits the
  reader is the planner's; the research chooses nothing (the critic's verdict on each part of the
  scheme).
  Research only gathers the information and leaves it in the folder; the plan is the planner's: no
  notes of the lead, no overview, highlights or angles, and the dossier holds no conclusions or advice for the plan,
  only the checked facts with their sources, what was left out and why, the saved pages, and the list of what was
  not found, so the planner builds no section without facts. `research.py finish` settles
  conflicts by code: one value per attribute of an entity (a value written two ways, «1,250 EUR» and «1250 EUR», is one
  value; «35 EUR» and «35 PLN» are two), the stronger source wins (official, then aggregator and media equally, then
  review), equally strong sources that disagree leave no value, and every dropped fact is listed with its reason;
  nothing goes to the author. It writes `FACTS.md`, the dossier built from the base, which the
  planner and the writer work from (the base is `research/facts.json`, the pages `research/sources/`). Research is
  not asked to sort facts under the brief's goals, so it does not bend facts to fit them.
- The planner writes the document's term list `TERMS.md` as its first step, before plan level 1 (it no
  longer belongs to the researcher): each term marked `known`, `link` or `explain` by the brief's Reader section, with a one-sentence definition, and the
  author approves the list. The plan then sizes what explaining the terms takes. Gates on terms check the text
  against this list.
- Plan format: every element of the plan's last level has a kind (paragraph, list, table, figure, summary, …), and the text carries a marker with the element's id before every element. Gates find elements by these.
- Length is decided in the plan, never by cutting finished text: a cut document reads as cut. The final document is
  checked against the plan's sizes; a miss sends the work back to the plan. How that return runs is open.
- The gate library holds default gates; when the plugin is set up, the user is asked which defaults to switch on.
- Every judge gate has its own judge: one subagent per gate, never one judge for several gates. A hook on writing
  the checked file runs the script gates; when judges are due, it tells the stage that wrote it to start one agent,
  the gate runner, which starts one judge subagent per gate. Only the outcome goes back to that stage (the judges' inputs and answers stay out of the writer's context): `PASSED`, or `NOT PASSED` with a report file of
  every failed place. The stage reads the report and fixes its work point by point until every gate passes.
- Each level of the plan is written in one pass into the plan file; a hook on writing that file runs the gates of
  that level before the author sees it.
- The plan does not say which brief goal each item serves. The planner's prompt says the plan must cover the goals;
  the judge finds for each goal where it is covered. This keeps the planner from cutting one section per goal.

## Open questions

- The document's gates: besides general gates, an **[idea]** gate of the library gets its concrete script written for each document, and the document's own gates are thought up and written after the brief and the plan. When: general gates are there from the start; gates are written and made concrete after the brief; some may be written after the plan. Open: who writes them. Decided: nobody checks a written script, it goes straight into work as a gate.

- Who draws figures: an illustrator agent (`agents/illustrator.md`), started by the writer as soon as it reaches a diagram element; it draws `figures/<id>.svg` from the plan's list of blocks and links, the writer inserts it and goes on. Screenshots go in as they are. A `generated_image` element goes to a separate agent, the image generator (`agents/image-generator.md`), never to the illustrator: it writes the prompt from the plan's «what it shows», `style:` and optional `references:`, generates attempts in `.images/<id>/` (outside `figures/`, so no gate runs on them), looks at each and redoes it, then copies the accepted one into `figures/<id>.png` with its `<id>.prompt.md`; the `generated-image` gate checks it there. Checks on the figure file itself run when it is written (see «Figures» under «Gates: how they run»).

- Shape of the researcher's material: not a pile of text and not a table of facts handed to the writer (a model makes nothing of a fact table); a graph an agent can think over, find things in and write from. Decided: the fact base and the dossier
  built from it, see «Research takes the scheme…» above.
- The fact base: can Claude really split knowledge into atomic facts, and is a mass of facts easier for it than text? Night run: 71 facts, median 40 words, 17 with several quotes, as long as the text. The grounding gates wait for this.

- How the return to the plan runs when the finished text misses the plan's sizes.
- Sizing by the output format: before the plan, estimate how much fits where the document is rendered,
  e.g. a branded A4 PDF — how many lines of text a page holds (filled with lorem ipsum, not packed), and roughly
  how much a chart, a table or a screenshot takes. Open: a step per document or a measurement per style; who sizes
  figures and tables; whether gates count rendered lines, words converted to lines, or pages.

## Gates: how they run

`hooks/gate_run.py` is a PostToolUse hook on Write/Edit/MultiEdit and Bash. It acts only on `PLAN.md`, `TEXT.md` and
images under `figures/` (a Bash call: only those images) in a folder that has a `BRIEF.md`. On `PLAN.md` it gates every level from sections down to the deepest level written so
far; judges run only for levels not approved as they stand. It runs the script gates first; while any
fails, the chat that wrote the file gets the list and no judge runs. Once they pass, it writes one input file per
judge into the document's `.gates/inputs/` and the run into `.gates/due.json`, and tells the chat to start ONE
agent, the gate runner (`agents/gate-runner.md`); it never lists the judges to the chat. The runner
loops on `collect_judges.py`: `next` hands it a round of at most 20 due judges, it starts them all in one message,
`record` reads each judge's verdict from its transcript into `.gates/verdicts.json`. When none is due, `report`
writes `.gates/report-<file>.md` (every NOT PASSED with the judge's quotes and reasons, and any judge that gave no
verdict) and prints the runner's whole answer: `PASSED`, or `NOT PASSED — N places, details in <report file>`. Inside
a subagent the Agent tool runs its subagents in the foreground, in parallel within one message (checked 23.11), so the
runner needs no waiting; a chat that starts the runner in the background waits for its one line with
`wait_critic.py`. On NOT PASSED the chat reads the report, fixes its file point by point and writes it again; the
hook runs again, and a judge whose input did not change is not run again (with no judge due and NOT PASSED verdicts
standing, the hook writes the report itself). When every gate passes, the hook sends the highest level not yet approved to the author, or to `plan-approver`
when the author is not available.

**Figures**: checks of a figure itself run on its file, checks of a figure in the text on TEXT.md. A figure is an image anywhere under the document's `figures/`: an `.svg` is a drawn diagram, a raster with a `<name>.prompt.md` beside it a generated image, any other raster a screenshot. The hook gates a figure file when a Write or Edit writes it, and when a Bash command that names a path in the document's `figures/` changed it (only a real path counts, with `~` and `$VAR` expanded, never a prose word of the command; in a here-document's body only a word shaped like `figures/…`, so a script names its output path literally, not built from variables; screenshots are copied and images generated by shell commands; `.gates/figures.json` keeps a hash of each figure that passed its script gates, so a figure that failed is gated again by the next command that names `figures`, e.g. `ls figures`), and when its prompt file `<name>.prompt.md` is written. The report goes to whoever ran that tool call. The illustrator starts the gate runner itself, as any stage does; if it cannot start a subagent, it passes the runner block on in its answer and the writer starts it. A judge sees the image: a raster as it is, an SVG rendered to PNG in `.gates/renders/` (`rsvg-convert`, else macOS `qlmanage`, both headless).

**Every version, for the document's timeline**: the hook, before any gate runs, keeps every version of every file of
a document (`gates/lib/history.py`), whoever wrote it: the Write/Edit tool, or a script run through Bash (research.py
writes FACTS.md that way), or anything else (a file changed outside the tools is kept on the next call); on a Write
or Edit it looks at the written file's document, on a Bash call at the documents the command names, the one it runs
in and every document it has kept versions of. A file of a document is every file under its folder outside hidden folders. The
versions are in `.gates/history/` (`blobs/` named by sha1, so the same content is kept once; `index.json` with each
version's time, and for PLAN.md, TEXT.md and figures the script gate failures or the judges of that write, noted once
its gates finish), and the folder is listed in `<cache>/documents.json` (`$UNSLOPABLE_CACHE`, else
`~/.cache/unslopable`, which also holds the hook's log `gate_run.log`). The document viewer (`/unslopable:viewer`,
`viewer/`) reads only these files and the gates' state, every 3 seconds, and shows the document's timeline in time
order: each version of each file with its word diff from the version before (for TEXT.md each element it changed,
for PLAN.md each level), the script gate failures of a write, and every judge's verdict, a complaint red
with its text; a complaint stays in the timeline when a later verdict passes the place. A filter by file, by element
or plan level, or by gate gives the history of one piece. A document made before its versions were kept is rebuilt
from what is on disk: each element and plan level as its judges saw it (`.gates/inputs/`), the times and outcomes of
the hook's runs (its log) and every other file as it is now; rebuilt events are marked, and what is not on disk is
listed, never made up. Tests point `$UNSLOPABLE_CACHE` at a temp folder (`tests/isolate.py`, imported first by every
test module).

**The fact base**: a Bash call that runs `research.py fetch|save|add|remove|merge|merge-attribute|gap|finish <folder>`, or a write of `research/facts.json` or `FACTS.md` (by Write/Edit, or a Bash command that names it), in a folder that has a `BRIEF.md`, runs the research's script gates `fact-quoted` and `sources-conflict` (`research_main`); they answer only when they fail, since `add` already answers every fact.

Every gate, what it checks, whether it is on by default and its script, judge or idea: [gates/library.md](gates/library.md).

## A project's own gates

A project that installs the plugin adds its own gates in the plugin's own standard, and the plugin runs them as its
own: the gate hook runs their scripts and starts their judges, the gate runner, the report, `gates_on` / `gates_off`
in GATES.md, the gates stage and the viewer treat them like the gates of `gates/library.md`.

**Where**: the folder `.unslopable/gates/` of the project. For a document the hook takes the nearest one: in the
document folder or the nearest folder above it that has `.unslopable/gates/library.md`; when none has, the one in
`$CLAUDE_PROJECT_DIR` (the folder Claude Code runs in). Only that one library counts. A project without it runs the
plugin's gates only, as before. `python3 gates/lib/project_gates.py <document folder>` prints where the library of
a document is and its gates.

**Layout**, the same as the plugin's `gates/`:

```
.unslopable/gates/
  library.md            the table of the project's gates
  scripts/<gate>.py     script gates
  judges/gate-<gate>.md judge prompts
  ideas/<gate>.md       ideas the gates stage writes a document's own script from
  lib/                  shared code of the scripts (on their PYTHONPATH)
  data/                 data files the scripts and judges read (lists, snapshots, settings of the project)
```

**library.md**: tables with the plugin's columns, `| Gate | What it checks | Default | Script | Judge | Idea |`, one
row per gate, links relative to the library (`[script](scripts/x.py)`, `[judge](judges/gate-x.md)`,
`[idea](ideas/x.md)`); `## Plan`, `## Text` headings as in the plugin's are for the reader. Every table of
library.md is read as a table of gates, so keep other tables out of it and write no `|` inside a cell. A name is lower-case
words joined by `-`, and not a name of the plugin's gates. **Default**: `on` runs in every document; `off` only when
GATES.md switches it on with `gates_on: <gate>`; `manuals` only with `manual: yes` in GATES.md; `per document` is an
idea (link its text in Idea; the gates stage writes its script into the document's `.gates/custom/`); `not built
yet` does not run. `gates_off: <gate> (<reason>)` in GATES.md switches a project gate off like a plugin gate. What
is wrong with library.md (an unknown Default, a link to a missing file, a plugin gate's name, a judge with no
script, a script whose first line names no file) fails every gated write as `config` until it is fixed.

**A script** follows the contract of a document's own gates: the first line is a comment naming the file it checks,
`PLAN.md`, `TEXT.md`, or `figures/` or a pattern such as `figures/*.svg`; the hook runs it on every write of that
file as `python3 <script> <document folder>` (a figure: `… <document folder> <figure file>`), within 60 s. It prints
one line per failure (where, what is wrong, how to fix); a line `CHECK: <where> — <the words>` is a place for the
gate's judge; no output means passed. Exit 0 or 1; another exit code with no output is a failure of the script. A
failure reaches the writer as `[<gate>] …`, like a plugin gate's. In its environment `UNSLOPABLE_PROJECT_GATES` is the
library folder (data: `$UNSLOPABLE_PROJECT_GATES/data/…`), and its PYTHONPATH has the library's `lib/` and then the
plugin's `gates/lib/` (so `from docs import load` reads the document as the plugin's gates do). Per-document values
(a product, a query) are in the document folder: GATES.md keys, or files the project's pipeline writes there.

**A judge** is a prompt file as the plugin's `gates/judges/gate-*.md`: what fails, what passes (frontmatter, if any,
is dropped; `{folder}` becomes the document folder and `{library}` the library folder). A project cannot register a
subagent with the plugin, so the plugin's generic judge `unslopable:gate-project` (`gates/judges/gate-project.md`,
tools: Read) runs it: when the gate's script prints CHECK lines, the hook writes one judge input with the project's
prompt, the document and library folders, the checked file and the places, and the gate runner starts
`unslopable:gate-project` on it like any judge. Its verdict is recorded, reported and shown in the viewer under the
gate's name, and it is not run again while its input stays the same. A judge decides the places its script found,
so a judge gate always has a script; a gate that needs a model on a whole section prints that section as its place.

**Tests**: `tests/test_project_gates.py` builds a sample project library (a script gate, a judge gate, an idea) and
runs it through the hook, the gate runner's script and the viewer.

## Provisional (19.11 night, test run)

Chosen for the test run because nothing above settled them; each is open to change.

- **Files.** A document folder holds `BRIEF.md`, `GATES.md`, `TERMS.md`, `PLAN.md`, `TEXT.md`, `MATERIAL.md` (where the material lies), and its material as
  `FACTS.md` or files under `sources/`. The gates' state is in `.gates/`.
- **The plan** is `PLAN.md`: one markdown list, nested by indentation, one item per line. Every list item in the file
  is a plan item; anything else (a `# Plan` title, the approval lines) is not read as plan. The fields of an item are
  separated by ` · ` (a middle dot with a space on each side), which no field may contain:
  - a section or subsection: `id · **heading** · what it covers · N lines` — the heading is in bold, and that is what
    makes the item a heading item. A heading item at the top is a section; one under a section is a subsection.
    A section whose subsections are a set of equal, unrelated cases (one subsection per option, per side, per
    case, none leading to the next) carries one more field before its size: `id · **heading** · what it covers ·
    subsections: parallel · N lines`. The planner sets it only for such a section; the author sees it when
    approving. The seams between its subsections are then not gated (transition-subsections); everything else is.
  - an element: `id · kind · what it says · facts: F1, F2 · N lines` — the second field is not bold. `kind` is a name of
    the element library, `elements/library.md` (`paragraph`, `bulleted_list`, `table`, `diagram`, `steps vertical`,
    …), or a kind of the planner's own when the library has none that fits; the old names `list`, `figure` and
    `yes-no` are still read. `facts:` is the
    material (fact numbers, or the knowledge base's files, separated by commas) and may be left out. An element sits
    under a subsection, or under a section with no subsections; a section with subsections is fully divided (text
    before its first subsection gets a subsection of its own). Elements have no items under them, except a `tiles`
    element: under it, one item per tile, `id · **title** · what the tile says · graphic: what its picture shows ·
    N lines` (the tile's own title, its body as short as the tile will be, what its graphic shows, and the body's
    size, at most 2 lines). The tiles belong to the elements level: approving it approves them.
  - The id is what the text marks with `<!-- id -->`; ids are unique in the file. Headings are working titles.

  ```markdown
  # Plan

  - S1 · **When the pump runs** · when the pump starts and stops · 10 lines
    - S1.e1 · paragraph · the switch starts and stops the pump · facts: F1 · 4 lines
    - S1.e2 · diagram · the path of the water · 4 lines
  - S2 · **Settings that save the pump** · the settings worth changing · 10 lines
    - S2.1 · **Low water cutoff** · when to turn it off · 3 lines
      - S2.1.e1 · paragraph · the cutoff stops the pump on a low well · facts: F3 · 3 lines
  ```

  A `tiles` element with its tiles:

  ```markdown
      - S3.1.e2 · tiles · the ways to water a garden the reader picks from · 5 lines
        - S3.1.e2.t1 · **Hose** · reaches every bed from one tap · graphic: a coiled hose with a nozzle · 2 lines
        - S3.1.e2.t2 · **Watering can** · carries water to a few pots · graphic: a tin can pouring on a pot · 1 line
  ```
- **Levels.** Sections are level 1, subsections level 2, elements level 3. Each level is added to the same file in
  turn. A level is approved by its own line outside the list: `Approved sections by <name>, <date> <time>`, and
  likewise `Approved subsections by …`, `Approved elements by …` (each on its own line, a blank line between them).
  The approval holds while that level's items are the ones the line was written for (`.gates/approved.json`, a hash
  of the level's ids, parents and fields): a level edited after its approval needs approval again; editing one level
  leaves the approvals of the others standing. A level with no items (no section has subsections) has nothing to
  approve.
- **Sizes in lines.** `lines` is the size of the text only; headings take no lines. Every level's sizes add up to
  the level above within `length_tolerance_pct` (at least 1 line); level 1 adds up to `total_lines`. In the text a
  line is `words_per_line` words: a paragraph is ceil(words / words_per_line), a list adds its items, a table its
  rows (a row is as tall as its longest cell at words_per_line / columns words per line); figures are not measured.
- **Text.** `TEXT.md` is markdown: `##` sections, `###` subsections, and before every block the plan element it
  writes, as a line `<!-- S1.2.e3 -->`. A block with no marker, or with an id that is not an element of `PLAN.md`,
  fails. The text's headings are the writer's; judges see the text with its own headings.
  Tiles (an element whose plan kind is `tiles`) are written as a list, one item per tile, its title in bold first:
  `- **Tile title:** what the tile says`. The parser reads such a list as a tiles block (title and body per tile);
  the plan's kind, not the markdown, is what makes it tiles. A `tiles` element with no such list, or a tile without
  a bold title and a body after it, fails as a format problem.
  Each tile opens with its own graphic, the image first in the item, then the title:
  `- ![what the picture shows](figures/<tile id>.svg) **Tile title:** what the tile says`, the tiles in the plan's
  order. The illustrator draws `figures/<tile id>.svg` from the plan's `graphic:`; the alt text is its caption and
  counts for no gate of the text. A PDF builder finds a tile and its graphic on each item of a list under a `tiles`
  element marker with `^\s*[-*+]\s+!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?[^)]*\)\s*\*\*(.+?):?\*\*:?\s*(.*)$` (alt
  text, image path, title without its colon, body). The writer opens a list item with an image only in tiles.
  A plan written before 23.11 with a `tiles` element has no tiles under it and now fails the tiles gate: add its
  tiles and have the elements level approved again.
  A **callout** (plan kind `callout`: a conclusion or key point, drawn as a coloured frame) and a **yes/no block**
  (plan kind `yes_no`: what a thing does set against what it does not do, drawn as two columns — «yes» on the left
  under a green ✓, «no» on the right under a red ✗, a vertical line between them) are fenced divs, so a PDF builder
  finds them by their first and last lines, written at the start of the line (`^:::\s*(callout|yes-no)\s*$` …
  `^:::\s*$`):

  ```markdown
  <!-- S2.e4 -->
  ::: callout
  The pump suits a **clean well**, not a muddy pond.
  :::

  <!-- S2.e5 -->
  The pump moves water and does nothing else.

  ::: yes-no
  - ✓ Moves clean water from a well.
  - ✓ Runs on a timer.
  - ✗ Moves water with sand in it.
  - ✗ Heats the water.
  :::
  ```

  Inside a yes/no block every list item starts with ✓ (U+2713, left column) or ✗ (U+2717, right column), no other
  mark, in any order, at least one of each; the builder splits the items by their icon. The paragraph before the block, under the same marker, is its
  lead-in. A `callout` or `yes_no` element written without its block, a block under an element of another kind, an
  unclosed or unknown `:::` block, or a yes/no item with no icon fails as a format problem. The gates read a callout
  like a paragraph (sentence, term, slop, truncation, flow and other paragraph gates) and a yes/no block's items like
  list items. The yes/no block's lead-in paragraph is part of its element's lines.
  The other elements of the element library (`elements/library.md`) that markdown has no form for are
  fenced blocks too: `::: pull-quote` (the phrase, then a last line `— Name` when the words are a person's),
  `::: steps vertical` or `::: steps horizontal` (one numbered list, `1. **Short title:** body` per step, in the form
  the plan's kind gives), `::: stat` (one sentence opening with the number in bold), `::: faq` (pairs split by a blank
  line: `**Question?**` on its own line, the answer on the lines after it) and `::: definition` (`**Term** — what it
  means`). Forms with examples are in `skills/writer/SKILL.md`. A chart, like a diagram, is one image line the
  illustrator draws. The gates read a pull quote (without its source line), a stat and a definition as prose, steps
  as list items, a FAQ's questions and answers as sentences; steps need a lead-in like a list. Plan kinds are the
  library's names (`bulleted_list`, `yes_no`, `pull_quote`, …): a kind is read with `_` as a space, so the old
  names (`list`, `figure`, `yes-no`) still work.
- **GATES.md** holds the numbers, one `key: value` per line: `sentence_max_words`, `heading_max_words`,
  `terms_before_first_figure`, `new_terms_per_unit` (2 when absent, as the library says), `total_lines`,
  `words_per_line`, `length_tolerance_pct`, `out_of_scope_terms` (names separated by `;`), `manual` (`yes|no`: the
  screenshot gates run in manuals only); optional `plain_text_max_lines` (the longest run of plain paragraphs in the
  plan, 10 when absent), `leftover_markers` (working markers this document adds to the
  default list, separated by `;`) and `tile_words_per_line` (the words a line of a tile's body holds, 6 when
  absent: a tile is about half the text column wide, two tiles a row). A gate whose number is missing fails
  with «set it». `gates_on:` switches on gates
  that are off by default, by their names separated by `;` (now `no-document-talk`, `no-announcing`); a name there
  that is not such a gate fails as `config`. `gates_off: <gate> (<reason>); …` switches off a gate that argues with
  the brief, by its name in `gates/library.md`, the reason in brackets: it reports nothing and starts no
  judge; a name that is not a gate of the library, or one with no reason, fails as `config`. Format and config checks
  are never off. For the test run the writer session sets them from the brief.
- **TERMS.md**: two bulleted lists under `## Known` and `## Explain`, one `- term — definition` per item; a known term
  marked `(link)` after its name gets, at its first mention, its gist in half a sentence and a link to its source,
  never a bare link (bare lines glued into one paragraph in a preview; `link` means gist and link). The
  list also holds the items the document names from an outside source (codes and names of someone else's list), with
  the same marks; an `explain` term first met in a list item, tile or table cell is not counted by `term-counts`. `read_terms` still reads the old form, one `term — known|link|explain — definition` per
  line, for documents written before. The definition is for the author approving the list and a reference for the writer, not wording to copy. A term's first use is its first occurrence in the body text
  (plural `-s`/`-es` included; headings and figures not counted).
- **Judge units.** A paragraph judge runs on every prose paragraph with a marker; a section judge runs once every
  element of the section in `PLAN.md` has text. «Paragraph to paragraph» compares a paragraph with the block before it
  in the same subsection; the first paragraph of a subsection is not checked (the heading carries it).
- **Return to the plan.** When a text element misses its plan size, the hook tells the writer to change the
  element's size in `PLAN.md` (and the sizes above it if their sums change), have the changed levels approved again,
  and write the element anew; how that return
  runs is still open (see Open questions).
- **Plan approval stand-in.** `plan-approver` is started only when the author is not available; its APPROVED adds
  `Approved <level> by plan-approver for <author>, <date> <time>`, e.g. `Approved sections by plan-approver for …`.
