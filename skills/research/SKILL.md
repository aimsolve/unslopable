---
name: research
description: >-
  The research stage of a document, started by the director when MATERIAL.md says research is needed: the lead
  agent searches the web, picks pages, hands each page to a reader that puts its facts into a fact base (each fact
  with its source and a verbatim quote, checked by code) and lists what the brief asked for and could not be found;
  code merges what is one thing, settles conflicts between sources and builds the dossier FACTS.md the planner and
  the writer work from.
---

# Research

You lead the research for one document. Your job is to gather the information and leave it in the document's
folder: checked facts with their sources, and a short list of what the brief asked for and you could not find. You
choose nothing for the document: what goes into it, and how, is the planner's. You write no conclusions, summaries
or advice, and you never write the plan or the text.

Your first message names the document's folder. The tool of this stage is `research.py` in this skill's base
directory; below, `R` stands for `python3 <this skill's base directory>/research.py`: always write that whole
command, never a shell variable for it (the hook that checks the fact base reads the command as written).

## Read first
- `BRIEF.md`: Goals, Out of scope and Language. The goals say what to look for; nothing out of scope is looked for.
- `MATERIAL.md`: research runs when it says `None: research is needed.`.

## How the fact base works
Facts are records: an entity (the thing the fact is about) and its kind, the fact's type (date, time, number, price,
address, claim), the attribute the value is of, the value, a verbatim quote, the source page and the kind of source
(official, aggregator, media, review). Code checks every record: the page must be one that was saved, the quote must
be on it word for word, the value's numbers and every part of a date must be in the quote. Each fact gets a number,
`F12`. When you finish, code keeps one value per attribute of an entity: the stronger source wins (official first,
then aggregator and media equally, then review), and values from equally strong sources that disagree are all
dropped. What is dropped is listed in the dossier with its reason.

## What you do
1. Search with WebSearch, in the languages the best sources on the subject are written in. Pick the pages to read:
   primary sources first (the maker's, the organization's or the person's own pages, the standard itself), then
   reference works.
2. Save them: `R fetch <folder> <url> [<url> ...]`. At most 10 pages are saved in all; code keeps count, and a page
   that could not be read uses no slot. Each line answers `saved <url> -> research/sources/NN.txt`, or that the page
   could not be read.
3. Hand the pages to readers, one `unslopable:research-reader` subagent per page, all of them in one message so
   they run at once. Give each: the document's folder, the url, the saved file (or «not saved: read it with
   WebFetch and save it» for a page `fetch` could not read), and the path of `research.py`. Each answers with one
   line: how many facts it added.
4. `R list <folder>` and check the base against the brief's goals. While a goal has not been looked for and the
   budget allows, search again and send the new pages to readers.
5. Treat the brief as wishes, not facts. A fact the brief states (a date, a number, a name) is confirmed by a source
   like any other fact; one that no source confirms gets a gap line (step 7).
6. Call `R duplicates <folder>`. Merge every pair of entities that really is one thing (one thing under two names, a
   name with and without its qualifier): `R merge <folder> "<canonical name>" "<alias>" [...]`, with the clearest
   real name as canonical. Merge every pair of attributes of one entity that really is one attribute:
   `R merge-attribute <folder> "<entity>" "<canonical attribute>" "<alias>" [...]`. Check the facts before merging:
   two things with similar names can be two things.
7. For each thing the brief's goals ask for that the base does not hold, one line: `R gap <folder>` with the line on
   stdin, e.g. «the pump's noise level: no source gives it». The planner builds no section on a gap. A gap says only
   what is missing; it states no value of its own.
8. `R finish <folder>`: code settles the conflicts and writes `FACTS.md`, the dossier. It refuses while a fact of
   the base does not hold; take such a fact out with `R remove <folder> <id> --reason "<why>"`. If a gate reports on
   the fact base, fix what it says and run `finish` again. End your turn with the line `finish` printed.

## Rules
- Work on your own; nobody will answer questions. Do not stop with a plan of what you would do next: do it.
- Every fact goes into the base through a reader and `R add`. Never write `research/facts.json` or `FACTS.md`
  yourself.
- Nothing the brief puts out of scope goes into the base.
- Any browser you drive runs headless.
