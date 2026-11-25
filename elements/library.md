# Element library

The elements a document is built from, for every kind of document: a report, a manual, an article. The planner
reads this list, decides which elements a document uses and where, and writes each element's `kind` in `PLAN.md`
with the name below. The writer writes each kind in the form its skill gives. The illustrator reads the schematic of
an element it draws; the image generator makes every `generated_image`.

This is a reference, not a closed list. When the content calls for an element that is not here, the planner may use
it: it names the kind in a word or two and says in the element's third field what the reader sees.

Each element has a schematic next to this file, `<kind>.svg`: a black, white and grey wireframe with no brand. Grey
bars stand for lines of text, black bars for bold text. It shows what the element is and how its parts sit, not how
it looks in a given document: colours, fonts and sizes come from the document's brand. Its `<desc>` says the same
in words.

One line per element: kind — what it is for — when to use it — schematic.

- `paragraph` — one line of thought in running prose, each sentence following from the one before — for reasoning, cause and effect, a story; never for three or more things side by side — `paragraph.svg`
- `bulleted_list` — three or more items of the same kind, in no set order — for any enumeration: parts of a pump, kinds of apples, what a house needs before winter — `bulleted_list.svg`
- `numbered_list` — items of the same kind whose order matters, or that the text names by number — for a ranking or a sequence the reader only reads; a process the reader carries out is `steps` — `numbered_list.svg`
- `table` — several things compared on the same features: a row per thing, a column per feature, one value per cell — for two-dimensional data: three pumps by flow, power and price — `table.svg`
- `tiles` — options the reader chooses between, each on a card with its own drawn picture, a title and at most two lines — only for a choice: a wooden house, a brick house or a tent — `tiles.svg`
- `diagram` — how the parts of a system connect or which path something takes: blocks, arrows, numbered steps — for a structure or a flow that words alone make hard to follow: water from the well through the pump to the tank — `diagram.svg`
- `screenshot` — a picture of a real screen, cropped with an even margin of its background on every side — when the reader has to recognise a window, a menu or a button — `screenshot.svg`
- `summary` — a short restatement of the main points at the end of a section or of the document, with no new fact — for a long section or document the reader may come back to — `summary.svg`
- `callout` — one conclusion or key point in a framed box, so it cannot be missed — for the one thing the reader should take from a section if they read nothing else — `callout.svg`
- `yes_no` — what a thing does set against what it does not do: two columns, ✓ on the left, ✗ on the right — when both sides have items: what the apple press handles and what it does not — `yes_no.svg`
- `pull_quote` — a short phrase set large, from a person or from the text itself, to set an accent — for the sentence the reader should remember, or what a named person said about the subject — `pull_quote.svg`
- `steps` — a process the reader carries out themselves: numbered steps, each with a short title and a body — for instructions in order: how to start the pump for the first time. Two forms: `steps horizontal` (on one line across the page, for three to five steps with bodies of at most two lines) and `steps vertical` (down the page, for more steps or longer bodies) — `steps-horizontal.svg`, `steps-vertical.svg`
- `stat` — one big number the point rests on, and a caption saying what it means — when one figure carries the argument: a tree drops 40% of its apples before they ripen — `stat.svg`
- `faq` — the questions the reader will ask, each with a short answer — for side questions the body does not answer, at the end of a section or document — `faq.svg`
- `definition` — a term and what it means, in a box, where the reader first meets it — for a term the reader must hold to follow the rest: a check valve — `definition.svg`
- `chart` — numbers over time or across categories, as bars or a line — when the shape of the numbers matters more than each value: apples picked per month — `chart.svg`
- `generated_image` — a picture made for this document by an image model from a prompt: a scene, an object, an idea shown as an illustration — when the reader should see something no screenshot, diagram or chart shows: the garden in its first summer; never for numbers, labels or text the reader must read, and never a near-copy of a reference picture. The plan gives what it shows, its style and, when there are any, the reference pictures it follows — `generated_image.svg`
