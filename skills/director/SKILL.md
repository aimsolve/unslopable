---
name: director
description: >-
  Makes a new document by running its stages in order: brief, gates, research, references, plan, writer. Use when
  the author starts a new document or comes back to one ("new document", "нужен документ", "сделаем мануал / статью
  / буклет", "продолжим документ").
---

# Director

Run the stages below in order. Each stage leaves its result in the document's folder; start from the first stage
whose result is not there yet. If the author has not said where the document's folder is, ask.

1. **Brief.** Invoke the skill `unslopable:brief`. Done when `BRIEF.md` is approved.
2. **References?** Ask the author whether to search for published documents similar to this one.
3. **Gates.** Start a new session whose first message invokes the skill `unslopable:gates` with the document's
   folder. Done when it ends with its list. After each level of the plan is approved, start this session again
   yourself, without asking the author: it writes the checks the new level makes possible. Running the gates is not
   this session's job: a hook runs them by itself whenever the plan or the text changes.
4. **Research.** Only when `MATERIAL.md` says `None: research is needed.`: start a new session on Opus whose first
   message invokes the skill `unslopable:research` with the document's folder. It works on its own, without the
   author. Done when `FACTS.md` is there and the session ended with the line `finish` printed; tell the author that
   line and the «Not found» section of `FACTS.md`. The research folder the later stages get is `FACTS.md` (the dossier: every fact with its
   number, what was left out, what was not found) and `research/` (the fact base with each fact's quote, and the saved
   pages).
5. **References.** Only if the author said yes in step 2: start a new session whose first message invokes the skill
   `unslopable:references` with the document's folder. Done when `REFERENCES.md` is there.
6. **Plan.** Starts in a clean context (a new session, never the chat of the brief interview): the planner knows
   only the files. Start a new session in the Claude desktop app whose first message invokes the skill
   `unslopable:plan` with the document's folder and the material's paths (the ones `MATERIAL.md` names, or the research
   folder when there was research). Tell the author to go on in that session: the planner asks them there. One file,
   `PLAN.md`, a nested list in three levels: sections, subsections, every element. The author approves each level
   before the next; gates are added after each level. Done when the elements of `PLAN.md` are approved.
7. **Writer.** Starts in a clean context: a new session whose first message invokes the skill `unslopable:writer`
   with the document's folder and the material's paths. Tell the author to go on in that session. Done when
   `TEXT.md` has every element of the plan and every gate passes.

When the next stage is not built yet, tell the author and stop.

Gates are not your concern: a hook gives their results to the agent being checked, and the agent fixes its work
until they pass.
