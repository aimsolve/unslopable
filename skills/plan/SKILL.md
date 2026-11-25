---
name: plan
description: >-
  The plan stage of a document, started by the director after the brief (and research, if any): reads BRIEF.md and
  the material the brief points to, and writes the plan, one file `PLAN.md` as a nested list, in three levels —
  sections, subsections under them, then every element with its kind, what it says, its material and its size in
  lines. Each level is added to the same file, passes its gates and is approved by the author before the next is
  written. Never writes the document's text.
---

# Plan

You write the plan of one document. You never write the document's text.

## Read first
- `BRIEF.md`: the document's constitution. Every decision answers to it.
- The material: the folders and web addresses `MATERIAL.md` names (or, when there was research, `FACTS.md` — the dossier: every fact with its number, what was left out and what was not found — and `research/` with each fact's quote and the saved pages) — the author's base and any folder of screenshots or images. Online material you read at its URL. Read what the plan needs, not all. A screenshot goes into the plan as a `screenshot` element
  naming its file; the writer uses no image the plan does not name. Where the element says how to crop the
  screenshot, the crop keeps an even margin of background around the content on every side and cuts no content
  at an edge: «the panel with an even band of the window around it», never «cropped to the panel's border». A
  shot whose content is whole but flush with an edge needs no new crop: the writer pads it with its background.
- `GATES.md`, if it exists.
- `elements/library.md` of the plugin (two folders above this skill's base directory): the elements a document is
  built from, each with what it is for, when to use it and a schematic `elements/<kind>.svg`. Read the whole list
  before level 3 and open the schematic of any element you are not sure of.
- `REFERENCES.md` and the files in `references/`, if they exist: published documents similar to this one. Take from
  them what helps the plan — structure, ways of presenting, length and density, layout — never their facts.

## First: the terms
Before level 1, write `TERMS.md`: the terms the document will use, in two bulleted lists under two headings, so
the author reads it as two lists in a Markdown preview (bare lines glue into one paragraph there).

- `## Known`: the terms the reader knows; the text uses them as they are. A known term marked `(link)` right after
  its name is one the reader needs only the gist of: where the reader first meets it, the text gives its gist in half
  a sentence and a link to its source, whose address ends its item. A bare link is not enough.
- `## Explain`: the terms the text explains before or where the reader first meets them.

One term per item, `- term — definition`. Which list a term goes in is decided by the brief's Reader section. Every
term has a definition in one sentence, from the material, so the author sees what they approve. The writer reads the
definitions as a reference and may explain a term in other words when the material calls for it.

The list also holds the items the document names from an outside source, when the material or the plan relies on
them: the codes or names of someone else's list, a grade from a standard, a model from a maker's catalogue. A reader
who meets such a name in a table, a list or tiles does not know what stands behind it. Each one goes in like a term: under
`## Explain`, or under `## Known` with or without `(link)`.

Show the list to the author and have it approved. When a later level of the plan adds an element that names such
items and they are not in the list yet, add them and have the additions approved before the level goes to the
author. Plan the sizes with the list: an `explain` term needs room where it is first met.

```markdown
# Terms

## Known

- pump — the machine that moves water from the well to the tank
- pressure gauge (link) — shows the pressure in the pipe — https://example.org/pressure-gauge
- apple grade A1 (link) — the top grade of a fruit standard, for sale whole — https://example.org/apple-grades

## Explain

- dry run — the pump turning with no water in it, which burns its seal
- check valve — a valve that lets water flow one way only
- apple grade B2 — small or bruised apples, pressed for juice
```

## One file, three levels
The plan is `PLAN.md`: one markdown list, nested by indentation (two spaces per level), one item per line. Fields
are separated by ` · ` (a middle dot with a space on each side); no field may contain it. Every list item in the
file is a plan item.

```markdown
# Plan

- S1 · **Water from the well** · how the pump fills the tank · 10 lines
  - S1.e1 · paragraph · the pump lifts water only while the well holds enough · facts: F1 · 4 lines
  - S1.e2 · diagram · the well, the pump and the tank; the pump draws water from the well; the pump sends it to the tank · 4 lines
  - S1.e3 · callout · a timer protects the pump better than a bigger motor · 2 lines
- S2 · **The first start** · what the owner does before the first run · 6 lines
  - S2.1 · **Priming** · filling the pump before it runs · 6 lines
    - S2.1.e1 · steps vertical · open the cap; fill the pump body with water; close the cap; switch the pump on · facts: F3 · 6 lines
```

1. Sections, the top items: `id · **heading** · what it covers · N lines`. The heading is in bold.
2. Subsections, under a section: the same fields. A section with subsections is fully divided: text before its
   first subsection gets a subsection of its own. A section may have none.
   The text is gated for its seams: the end of each subsection must lead to the next subsection's heading. A
   section whose subsections are a set of equal, unrelated cases — one subsection per option, per side or per case,
   none of which leads to the next, such as one subsection for each of four ways to water a garden — is marked with
   a field before its size: `S3 · **Ways to water a garden** · the four ways side by side · subsections: parallel ·
   12 lines`. The seams between its subsections are then not gated. Use the mark only for such a set; subsections
   that build on each other, or a story told in steps, never get it. Set it on the section when you write the
   sections, if you already know; if the subsections show it, set it then, and the sections need approval again.
3. Elements, under a subsection or under a section with no subsections: `id · kind · what it says · facts: … ·
   N lines`. `kind` is the element's name in the element library (`paragraph`, `bulleted_list`, `table`, `steps`,
   `chart`, …); `steps` carries its form, `steps vertical` or `steps horizontal`, which you pick for the place. An
   element the library does not have may be used when the content calls for it: name its kind in a word or two and
   say in the third field what the reader sees. What it says: one line, what the element tells the reader.
   `facts:` is the material: the fact numbers when there was research; when you work from a
   knowledge base, the base's files the element draws on, separated by commas. They show the writer where to start;
   the writer may read other files too. Leave `facts:` out when there is none.
   A `diagram` (drawn for the document; a screenshot goes in as it is): its third field says what is on it
   instead of what it should convey — every block and every link between blocks, with what each link means, in the
   shape «A, B and C; A sends X to B; B reads Y from C». Not where the blocks stand or what their labels say.
   A `chart`: its third field says what is measured, over what (time or categories) and as bars or a line, e.g.
   «apples picked per month, March to October, bars»; its `facts:` hold the numbers. A `stat`: the number and what
   it means, the number from `facts:`. `steps`: the steps in order, separated by semicolons, each a short action. A
   `faq`: the questions, separated by semicolons. A `definition`: the term; it is the element whose `; explains:`
   names that term. A `pull_quote`: the phrase, and whose words they are when they are a person's.
   A `generated_image` (a picture an image model makes for the document): `id · generated_image · what it shows ·
   style: … · references: path, path · N lines`. What it shows: the scene or the object, what is in it and from
   where it is seen, e.g. «the garden in its first summer, seen from the gate». `style:` is the look, in a few
   words, matching the brief's brand: «soft watercolour, muted greens». `references:` is optional: pictures of the
   material (paths in the document folder) the image follows for a real object's look or for a style, never to
   copy. No numbers, labels or text the reader must read are put on a generated image: those are a `chart`, a
   `diagram` or text.
   A `tiles` element has its tiles under it, one item per tile, one level deeper: `id · **title** · what the tile
   says · graphic: what its picture shows · N lines`. The title names the option; the body is the tile's text as
   short as the tile will be; `graphic:` says what this tile's own picture shows, drawn for it (an illustration or
   an icon, never a stock icon or a screenshot), so the pictures tell the tiles apart: for tiles on ways to water a
   garden, «a coiled hose with a spray nozzle», «a tin can pouring on a pot». `N lines` is the body's size, at most
   2 lines: a line of a tile holds `tile_words_per_line` words (GATES.md, 6 when absent).
   Where an element explains terms, its third field ends with `; explains: A, B`: the `explain` terms of `TERMS.md`
   this element explains. Every `explain` term is explained in exactly one element, the one where the reader first
   meets it. Nothing above it in the plan uses the term, the descriptions of
   sections and subsections included (headings may).
   An element that names items from an outside source (a table of apple grades, a list of pump models) says, in its
   third field, how the reader gets each item: the items it explains itself are in its `; explains:`, an item
   explained earlier is named with the id of the element that explains it, and an item that goes with its gist and
   a link is named with `link`; `; explains:` stays last. Example: `S2.e3 · table · the grades of apples a farm
   sells; A1, A2: link; B2: explained in S1.e4; explains: C1 · 6 lines`. Every such item is in `TERMS.md`.

The id is what the text marks before the element (`<!-- S1.e1 -->`); ids are unique. Headings are working titles:
the writer may change them.

Add each level to `PLAN.md` in one pass. Add the next level only after the author approved this one.

## Rules the plan holds to
- Cover every goal of the brief. Do not write which goal an item serves, and do not cut one section per goal.
- A section only where the material has something for it. One topic per section. Each fact in one place.
- The material may hold more than this document needs: the research gathers every fact that bears on the brief's
  goals and chooses nothing. Take what this reader needs for the brief's goals, by the brief's Reader and Need;
  leave the rest out. Nothing `FACTS.md` lists under «Not found» gets an element.
- Nothing the brief puts out of scope.
- No compound sentence in any field: two main clauses with different subjects joined by a comma, «and», «but», «or»,
  «so», a semicolon or a dash. Split it, or make one clause subordinate. The author has to read the plan at a glance.
- An element that enumerates three or more things is a `bulleted_list` (a `numbered_list` when the order
  matters, `steps` when the reader carries them out), never a paragraph.
- No wall of plain text. The reader skims, and a page of grey prose loses them. Before you write level 3, look
  through the element library for each section and break its plain text with the elements that fit the content.
  Add up the lines of consecutive `paragraph` elements. These start the count again: a list (bulleted or numbered),
  tiles, a table, a diagram, a screenshot, a chart, a callout, a yes/no block, steps, a stat, a pull quote, a
  definition, and a new subsection. A summary, a FAQ or another kind leaves the count as it is. Once the sum passes
  `plain_text_max_lines` of `GATES.md` (10 lines when it is not set), the next element is one of those, never
  another paragraph: with 10, two paragraphs of 6 lines are followed by a list, a diagram or a new subsection. One
  paragraph longer than the limit by itself may stand, under the same rule. Break a wall where the content allows
  it, not by force: an enumeration becomes a list, a comparison a table, a process the reader follows steps, a
  does-and-does-not a yes/no block, the number a point rests on a stat, a section's conclusion a callout. A gate
  checks this level against the rule.
- The key conclusion of a section goes into a `callout`: the one point the reader should take from the section if
  they read nothing else. Not every section needs one. A callout says what the facts above it mean for the reader,
  so its `facts:` stays empty.
- What a thing does and what it does not do, set side by side, is a `yes_no` element, not two paragraphs. Use it only
  when both sides have items; a thing with only limits is a list. Its lines include the one-sentence lead-in the
  writer puts above the block.
- A tile's body is at most 2 lines. When a tile does not fit, you decide: shorten it, or move the explanation into
  the text next to the tiles (a paragraph element before or after them) and keep the tile short. The gate only
  reports the tile.
- Headings name the topic and do not answer it: no counts, listicle nouns or advice, no colon or dash.
- Sizes in lines. Each level adds up to the level above; level 1 adds up to the brief's length. Length is set here,
  never by cutting text later. Work out element sizes with the author.

## After writing a level
- A hook runs the level's gates. When judges are due, it asks you to start one agent, the gate runner: start it as
  the hook says and wait for its one line. Never start a judge yourself. On `NOT PASSED`, read the report file the
  line names and fix the level point by point, then write it again, until the runner answers `PASSED`.
- Show the level to the author. Approval is a line above the list, one per level, a blank line between them:
  `Approved sections by <name>, <date> <time>` (then `Approved subsections by …`, `Approved elements by …`). Editing
  a level after its approval needs its approval again; a level with no items (no subsections) needs none.

## Asking the author
Through AskUserQuestion, one question per call, 2–4 options, none recommended, in no order of preference. Ask only
what the brief and the material do not settle.
