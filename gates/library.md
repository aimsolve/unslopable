# Gate library

Every gate of the plugin, one row each. The gates stage reads this list after the brief and after each level of the
plan.

- **Default**: `on` runs in every document; `off` runs only when GATES.md switches it on with
  `gates_on: <gate>; <gate>`; `manuals` runs only when GATES.md has `manual: yes`; `per document` is an idea: the
  gates stage writes its script for each document into `.gates/custom/`; `not built yet` waits for code that does
  not exist yet.
- **Script**: deterministic code in [scripts/](scripts/), one file per gate. It fails a place, or finds places for
  the gate's judge.
- **Judge**: a subagent prompt in [judges/](judges/). The judge reads one input file and answers PASSED or NOT
  PASSED with the places. A document's own gates that print `CHECK:` lines go to
  [judges/gate-custom.md](judges/gate-custom.md).
- **Idea**: a text in [ideas/](ideas/) the gates stage writes a document's own script from.

Shared code is in [lib/](lib/): the document reader, the script runner, the judges' inputs, the figure files and the
spaCy parsers. Numbers such as `sentence_max_words` are set per document in GATES.md.

## Plan

| Gate | What it checks | Default | Script | Judge | Idea |
|---|---|---|---|---|---|
| goals-covered | Every goal in BRIEF.md is covered by at least one unit of the plan level. | on | | [judge](judges/gate-goals-covered.md) | |
| out-of-scope | Nothing BRIEF.md puts out of scope appears in the plan or the text. The script finds the names of GATES.md `out_of_scope_terms`; the judge reads the rest. | on | [script](scripts/out_of_scope.py) | [judge](judges/gate-out-of-scope.md) | [idea](ideas/out_of_scope.md) |
| section-has-material | A section or subsection exists only where the document's material has something for it. | on | | [judge](judges/gate-section-has-material.md) | |
| one-topic | Each section or subsection has one topic; the end of a section may lead into the next. | on | | [judge](judges/gate-one-topic.md) | |
| fact-one-place | A fact number appears in one plan element only; a summary may repeat it. | on | [script](scripts/fact_one_place.py) | | |
| terms-placed | Every `explain` term of TERMS.md is named in `explains:` of exactly one element, where the reader first meets it. | on | [script](scripts/terms_placed.py) | | |
| term-order | No plan item before an `explain` term's explaining element uses the term; the judge decides whether each match is the term or an ordinary word. | on | [script](scripts/term_order.py) | [judge](judges/gate-term-order.md) | |
| plan-length | The `lines` of the plan add up to the length the brief gives, per section and for the whole document. | on | [script](scripts/plan_length.py) | | |
| plan-wall | Paragraph elements in a row add up to at most `plain_text_max_lines` (10 when absent) before a visual element of the [element library](../elements/library.md) (a list, tiles, a table, a diagram, a screenshot, a chart, a callout, a yes/no block, steps, a stat, a pull quote, a definition) or a heading; a summary and a FAQ neither add nor break. | on | [script](scripts/plan_wall.py) | | |
| heading-no-colon-dash | A heading has no colon or dash. | on | [script](scripts/heading_no_colon_dash.py) | | |
| heading-max-words | A heading has at most `heading_max_words` words. | on | [script](scripts/heading_max_words.py) | | |
| heading-no-listicle | The headings of a plan level have no counts, no listicle nouns and no advice. | on | | [judge](judges/gate-heading-no-listicle.md) | |
| heading-names-topic | A heading names its topic and does not answer it. | on | | [judge](judges/gate-heading-names-topic.md) | |

## Text

| Gate | What it checks | Default | Script | Judge | Idea |
|---|---|---|---|---|---|
| text-length | Each element's length in the text is within `length_tolerance_pct` of its `lines` in the plan; a miss goes back to the plan. | on | [script](scripts/text_length.py) | | |
| plan-elements-written | Every plan element up to the last one written is in the text, by its id marker. | on | [script](scripts/plan_elements_written.py) | | |
| plan-promises | The text delivers what each plan element promises: the columns of a table, the number of items in a list, the material it names. | per document | | | [idea](ideas/plan_promises.md) |
| term-explained | An `explain` term is explained at or before its first use and led in; the script fails a first use in the first sentence of a section or paragraph. | on | [script](scripts/term_first_use.py) | [judge](judges/gate-term-explained.md) | |
| term-counts | At most `terms_before_first_figure` terms before the first figure and `new_terms_per_unit` new terms per unit; list items, tiles and table cells are not counted. | on | [script](scripts/term_counts.py) | | |
| term-marked | An `explain` term is in italics or bold at its first use. | on | [script](scripts/term_marked.py) | | |
| sentence-max-words | A sentence has at most `sentence_max_words` words. | on | [script](scripts/sentence_max_words.py) | | |
| no-compound | No compound sentence: two main clauses with different subjects joined by a comma, a conjunction or a semicolon. In the text and in the `covers` and `says` fields of plan levels not yet approved; a spaCy parse finds them, the judge decides the sentences the parse is unsure of. | on | [script](scripts/no_compound.py) | [judge](judges/gate-no-compound.md) | |
| no-semicolon | No semicolons. | on | [script](scripts/no_semicolon.py) | | |
| one-sentence-per-item | A list item or a table cell is one sentence. | on | [script](scripts/one_sentence_per_item.py) | | |
| flow-sentences | Within a paragraph each sentence follows from the one before. | on | | [judge](judges/gate-flow-sentences.md) | |
| fact-soup | A paragraph of three or more sentences keeps one subject or passes from one subject to the next through the sentence before; a spaCy parse gives the subjects. | on | [script](scripts/cohesion.py) | [judge](judges/gate-fact-soup.md) | |
| inline-list | An enumeration of three or more things is a bulleted list, not running text; a spaCy parse finds the enumerations. | on | [script](scripts/cohesion.py) | [judge](judges/gate-inline-list.md) | |
| list-lead-in | A list, tiles, a table or a yes/no block is led in by a sentence that says what follows and why; the script fails one with no paragraph right before it. | on | [script](scripts/list_lead_in.py) | [judge](judges/gate-list-lead-in.md) | |
| flow-paragraphs | A paragraph follows from the block before it or from its part's topic. | on | | [judge](judges/gate-flow-paragraphs.md) | |
| flow-sections | A section follows from the section before it or from why the reader came. | on | | [judge](judges/gate-flow-sections.md) | |
| transition-elements | Inside one subsection, the start of each element picks up the end of the element right before it: it continues it, answers it, gives its example, consequence or contrast, or signals a turn; staying on the subsection's topic is not enough. Pairs are direct neighbours; a pair whose later element starts with a list, tiles, a table, a yes/no block or steps is list-lead-in's. | on | | [judge](judges/gate-transition-elements.md) | |
| transition-subsections | After the end of a subsection, the next subsection's heading reads as the next step: the end leads to it, hints at it or leaves a question it answers. Not inside a section the plan marks `subsections: parallel`. | on | | [judge](judges/gate-transition-subsections.md) | |
| transition-sections | The last sentences of a section lead to the next section's heading; the section may close its own topic. | on | | [judge](judges/gate-transition-sections.md) | |
| no-hedging | The text does not hedge its own authority («not an exhaustive review»). | on | [script](scripts/no_hedging.py) | [judge](judges/gate-no-hedging.md) | |
| no-document-talk | The text does not talk about the document itself («this report covers…»). | off | [script](scripts/no_document_talk.py) | [judge](judges/gate-no-document-talk.md) | |
| no-announcing | The text does not announce what comes later («below we look at…»). | off | [script](scripts/no_announcing.py) | [judge](judges/gate-no-announcing.md) | |
| no-number-reference | No reference by number or position («see § 3.2», «table 4», «as said above»). | on | [script](scripts/no_number_reference.py) | [judge](judges/gate-no-number-reference.md) | |
| no-repetition | A section does not repeat an earlier section, in the same or other words; a FAQ or a callout does not repeat the body. The script finds runs of 6 identical words. | on | [script](scripts/no_repetition.py) | [judge](judges/gate-no-repetition.md) | |
| example-own-line | An example that is a full sentence stands on its own marked line; a short inline clause stays inline. | on | [script](scripts/example_own_line.py) | [judge](judges/gate-example-own-line.md) | |
| slop-words | Each word or phrase of the slop lists (Antislop, Kobak) the script finds is the plain right word in its place, not slop. | on | [script](scripts/slop_words.py) | [judge](judges/gate-slop-words.md) | |
| cliche | An element of the text has no cliché. | on | | [judge](judges/gate-cliche.md) | |
| redundant-exposition | An element of the text has no unnecessary or redundant exposition. | on | | [judge](judges/gate-redundant-exposition.md) | |
| purple-prose | An element of the text has no purple prose. | on | | [judge](judges/gate-purple-prose.md) | |
| sentence-structure | An element of the text has no poorly built sentence. | on | | [judge](judges/gate-sentence-structure.md) | |
| lacks-specificity | An element of the text is specific, not general. | on | | [judge](judges/gate-lacks-specificity.md) | |
| awkward-wording | An element of the text has no awkward word choice or phrasing. | on | | [judge](judges/gate-awkward-wording.md) | |
| tense-shift | Tenses in one paragraph shift only where the time shifts; a spaCy parse finds paragraphs with clauses in more than one tense. | on | [script](scripts/tense_shift.py) | [judge](judges/gate-tense-shift.md) | |
| announced-count | A number the text gives for a set of things matches what it then lists, or the text says why only part follows. | on | [script](scripts/announced_count.py) | [judge](judges/gate-announced-count.md) | |
| date-tense | The tense of a sentence with a date agrees with today's date. | on | [script](scripts/dates.py) | [judge](judges/gate-date-tense.md) | |
| date-weekday | A weekday written next to a date is the date's real weekday; the judge checks it with the tool [lib/weekday.py](lib/weekday.py). | on | [script](scripts/dates.py) | [judge](judges/gate-date-weekday.md) | |
| no-truncated | No paragraph sentence is cut off, missing its end mark or its verb. | on | [script](scripts/no_truncated.py) | [judge](judges/gate-no-truncated.md) | |
| summary-faithful | A summary element adds nothing the text does not say and keeps every qualifier of what it sums up. | on | | [judge](judges/gate-summary-faithful.md) | |

## Tables and blocks

| Gate | What it checks | Default | Script | Judge | Idea |
|---|---|---|---|---|---|
| cell-answers-header | Every row of a table answers the header row, each cell its own column. | on | | [judge](judges/gate-cell-answers-header.md) | |
| yes-no-grid | A column whose answers are yes or no is a ✓/✗ grid, not free text. | on | [script](scripts/yes_no_grid.py) | [judge](judges/gate-yes-no-grid.md) | |
| table-footnote | No footnote marks in a table; a condition becomes a column, a row or part of a row label. | on | [script](scripts/table_footnote.py) | | |
| table-duplicate-row | No two rows of a table have the same label. | on | [script](scripts/table_duplicate_row.py) | | |
| table-flat | A table holds only two-dimensional data, with no list or table inside a cell. | on | [script](scripts/table_flat.py) | [judge](judges/gate-table-flat.md) | |
| same-kind | Items set side by side in a list, a table, tiles or a yes/no block are the same kind of thing, in the same form. | on | | [judge](judges/gate-same-kind.md) | |
| tiles-choice | Tiles are used only for options the reader chooses between. | on | | [judge](judges/gate-tiles-choice.md) | |
| no-hidden-fact | No fact is hidden in a tile's title, a table's header or a note under a table or tiles. | on | | [judge](judges/gate-no-hidden-fact.md) | |
| tile-graphic | Every tile opens with its own graphic, drawn for that tile: not a stock icon, not a screenshot, not another tile's file. | on | [script](scripts/tiles.py) | [judge](judges/gate-tile-graphic.md) | |
| tile-length | A tile's body is at most 2 lines of `tile_words_per_line` words (6 when absent), in the plan and in the text. | on | [script](scripts/tiles.py) | | |
| external-items | Every item a list, table or tiles names from an outside source (a code or a name from someone else's list or standard) is in TERMS.md, and its mark is met: explained, linked with its gist, or known. | on | | [judge](judges/gate-external-items.md) | |

## Figures, images, screenshots

| Gate | What it checks | Default | Script | Judge | Idea |
|---|---|---|---|---|---|
| figure-marks | Every mark on a figure (a colour, an icon, a dashed line) is explained in its caption or the text. | on | | [judge](judges/gate-figure-marks.md) | |
| figure-steps | The numbered marks of a figure run 1..N and match the steps of the text, in number and order. | on | [script](scripts/figure_steps.py) | [judge](judges/gate-figure-steps.md) | |
| figure-labels | Every label on a figure appears in the text before the figure. | on | [script](scripts/figure_labels.py) | [judge](judges/gate-figure-labels.md) | |
| figure-text-size | Text in a figure is between 7 pt and the body size, as printed. | per document | | | [idea](ideas/figure_text_size.md) |
| screenshot-names | A screenshot shows no real names, handles, emails or avatars. | per document | | | [idea](ideas/screenshot_names.md) |
| screenshot-cropped | A screenshot of one screen element is cropped close to its edge, a thin even band of what surrounds it kept. | manuals | | [judge](judges/gate-screenshot-cropped.md) | |
| screenshot-margin | A screenshot keeps a band of background on every side; no content touches or is cut at an edge. The script measures the bands, the judge looks where one is thinner than the least. | on | [script](scripts/screenshot_margin.py) | [judge](judges/gate-screenshot-margin.md) | |
| generated-image | A generated image has a prompt file whose references exist, is not a near-copy of a reference, matches its prompt and style and has no invented objects. | on | [script](scripts/generated_image.py) | [judge](judges/gate-generated-image.md) | |

## Final document

| Gate | What it checks | Default | Script | Judge | Idea |
|---|---|---|---|---|---|
| links | Every link resolves: an external one opens, an internal one matches a heading of the text. | on | [script](scripts/links.py) | | |
| leftover-markers | No working marker is left (TODO, TBD, FIXME, XXX, [citation needed] and the ones GATES.md `leftover_markers` adds). | on | [script](scripts/leftover_markers.py) | | |

## Research

| Gate | What it checks | Default | Script | Judge | Idea |
|---|---|---|---|---|---|
| fact-quoted | A fact enters the fact base only with an exact source and a verbatim quote that holds its numbers, found in the saved source; a fact written into the base some other way fails. | on | [script](scripts/fact_quoted.py) | | |
| sources-conflict | Code settles facts of the base that give one attribute of one entity different values: the stronger source wins, equally strong sources that disagree leave no value, and every dropped fact is in FACTS.md with its reason; nothing goes to the author. | on | [script](scripts/sources_conflict.py) | | |
