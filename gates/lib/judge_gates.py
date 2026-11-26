"""Judge gates: what each judge subagent gets to read.

A judge request is one subagent run for one gate on one unit (a plan level, a heading, a term, a paragraph, a
section). Its input is written to a file in the document's `.gates/inputs/`; the prompt the session gives the
subagent is only `judge_id` and the input path. The id carries a hash of the input, so a judge whose input did not
change is not run again (its verdict is in `.gates/verdicts.json`).
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date
from pathlib import Path
from dataclasses import dataclass

from docs import ITEM_KINDS, LEVELS, NO, PLAN_FILE, PROSE_KINDS, TEXT_KINDS, YES, Block, Doc, brief_part, level_text, plain, plan_text
from common import ENUMERATION_KINDS, Unit, block_name, opens_paragraph, element_kind, first_uses, label, \
    summary_elements, tables
# the finders of the gate scripts whose judges are built here
from announced_count import count_hits
from dates import date_hits
from example_own_line import example_hits
from list_lead_in import list_lead_ins
from no_announcing import announcing_hits
from no_document_talk import document_talk_hits
from no_hedging import hedge_hits
from no_number_reference import number_reference_hits
from no_repetition import repeat_hits
from slop_words import slop_hits
from table_flat import flat_candidates
from term_order import term_order_candidates
from yes_no_grid import yes_no_columns

AGENT = "unslopable:gate-{}"


@dataclass
class JudgeRequest:
    gate: str
    unit: str
    input: str
    agent_type: str = ""  # a gate with no subagent of its own (a project's gate) names the judge that runs it

    @property
    def agent(self) -> str:
        return self.agent_type or AGENT.format(self.gate)

    @property
    def id(self) -> str:
        h = hashlib.sha1(f"{self.gate}\n{self.input}".encode("utf-8")).hexdigest()[:12]
        return f"{self.gate}-{h}"


def _brief(doc: Doc, key: str, title: str) -> str:
    body = brief_part(doc.brief, key).strip() or "(this section of BRIEF.md is empty)"
    return f"## {title} (from BRIEF.md)\n\n{body}\n"


def level_input(doc: Doc, level: int) -> str:
    """The level checked, rebuilt from its items: approval lines are never in a judge's input, so approving a level
    does not change its judges' ids."""
    rows = level_text(doc.plans.get(level, [])) or "(none)\n"
    return f"## The {LEVELS[level]} of the plan (the level being checked)\n\n{rows}\n"


def plan_input(doc: Doc, level: int) -> str:
    """The approved levels above as the nested list, then the level checked."""
    upper = (f"## The plan down to its {LEVELS[level - 1]} (approved levels above)\n\n"
             f"{plan_text(doc.plans, level - 1)}\n") if level > 1 else ""
    return upper + level_input(doc, level)


def _material(doc: Doc) -> str:
    """Where the document's material is: FACTS.md, else the files under sources/ (provisional, README)."""
    facts = doc.folder / "FACTS.md"
    src = doc.folder / "sources"
    if facts.exists():
        files = [facts]
    else:
        files = sorted(p for p in src.rglob("*") if p.is_file()) if src.is_dir() else []
    # the material MATERIAL.md names: folders, files and web addresses
    mat = doc.folder / "MATERIAL.md"
    mat_text = mat.read_text(encoding="utf-8") if mat.exists() else ""
    urls = []
    for m in re.findall(r"`([^`]+)`", mat_text):
        if re.match(r"https?://", m):
            urls.append(m)
            continue
        p = Path(os.path.expanduser(m))
        if p.is_dir():
            files += sorted(q for q in p.rglob("*") if q.is_file() and not q.name.startswith("."))
        elif p.is_file():
            files.append(p)
    if urls:
        return "".join(f"- {p} (sha1 {hashlib.sha1(p.read_bytes()).hexdigest()[:12]})\n" for p in files) + \
            "".join(f"- {u} (online; read it there)\n" for u in urls)
    if not files:
        return "(none: the document folder has no FACTS.md and no files under sources/)\n"
    # the content hash makes a changed material file a new input, so its judge runs again
    return "".join(f"- {p} (sha1 {hashlib.sha1(p.read_bytes()).hexdigest()[:12]})\n" for p in files)


# ---------------------------------------------------------------- plan levels

def plan_requests(doc: Doc, level: int) -> list[JudgeRequest]:
    out = []
    unit = f"{PLAN_FILE} {LEVELS[level]}"
    both = plan_input(doc, level)
    this = level_input(doc, level)
    out.append(JudgeRequest("goals-covered", unit, _brief(doc, "goals", "Goals") + "\n" + both))
    out.append(JudgeRequest("out-of-scope", unit, _brief(doc, "out of scope", "Out of scope") + "\n" + this))
    if level in (1, 2):
        out.append(JudgeRequest("section-has-material", unit,
                                both + "\n## The document's material (read these files)\n\n" + _material(doc)))
        out.append(JudgeRequest("one-topic", unit, both))
        rows = doc.plans.get(level, [])
        heads = "".join(f"- {r.id}: {plain(r.get('heading'))}\n" for r in rows)
        out.append(JudgeRequest("heading-no-listicle", f"{unit}, headings",
                                f"## Headings of the {LEVELS[level]} (working titles)\n\n{heads}"))
        for r in rows:
            out.append(JudgeRequest("heading-names-topic", f"{PLAN_FILE} {r.id}",
                                    f"## Heading\n\n{plain(r.get('heading'))}\n\n"
                                    f"## What the part under it covers (from the plan)\n\n{plain(r.get('covers'))}\n"))
    if level == 3:
        out += term_order_requests(doc)
    return out


def term_order_requests(doc: Doc) -> list[JudgeRequest]:
    """An `explain` term's word in an element before the element that explains it: the judge decides, for each,
    whether it is the term or an ordinary word."""
    cands = term_order_candidates(doc)
    if not cands:
        return []
    terms_file = doc.folder / "TERMS.md"
    lines = terms_file.read_text(encoding="utf-8").splitlines() if terms_file.exists() else []
    defs = {}
    for t, *_ in cands:
        defs[t] = next((ln.strip() for ln in lines if ln.strip().lstrip("-* ").lower().startswith(t.lower())), t)
    body = "".join(f"- term «{t}» (explained in {el}); earlier, in {prev}: «{says}»\n"
                   for t, el, prev, says in cands)
    terms = "".join(f"- {d}\n" for d in dict.fromkeys(defs.values()))
    return [JudgeRequest("term-order", f"{PLAN_FILE} elements, terms used before their explanation",
                         f"## The terms (from TERMS.md)\n\n{terms}\n## Earlier mentions\n\n{body}")]


def plan_compound_request(cands: list[tuple[str, str, dict]]) -> list[JudgeRequest]:
    """No compound sentence in the plan, judge part: the plan sentences the parse is unsure of."""
    if not cands:
        return []
    lines = "".join(f"- {w}: «{s}» (main verbs by the parse: {', '.join(r['predicates'])}; "
                    f"joined by «{r['joiner'] or '?'}»)\n" for w, s, r in cands)
    return [JudgeRequest("no-compound", f"{PLAN_FILE}, unsure sentences", f"## Sentences\n\n{lines}")]


# ---------------------------------------------------------------- text

def _leaf_of(doc: Doc, element: str) -> str:
    r = doc.plan_row(element)
    return r.get("parent") if r is not None else ""


def _block_text(b: Block) -> str:
    return b.text.strip()


def sections(doc: Doc) -> list[tuple[str, list[int]]]:
    """[(level-1 id, block indexes)] in plan order, for sections that have text."""
    by: dict[str, list[int]] = {}
    for i, b in enumerate(doc.text.blocks):
        s = doc.section_of(b.element) if b.element else ""
        if s:
            by.setdefault(s, []).append(i)
    return [(r.id, by[r.id]) for r in doc.plans.get(1, []) if r.id in by]


def complete(doc: Doc, sid: str) -> bool:
    """Every plan element of the section has text."""
    have = {b.element for b in doc.text.blocks}
    els = [r.id for r in doc.plans.get(3, []) if doc.section_of(r.id) == sid]
    return bool(els) and all(e in have for e in els)


def section_text(doc: Doc, sid: str, idx: list[int], upto: int | None = None) -> str:
    """The section's blocks as the text has them, with the text's own headings (the plan's are working titles):
    before each block, the headings below the document title that stand between it and the block before it."""
    blocks, heads = doc.text.blocks, doc.text.headings
    out = []
    for i in idx:
        if upto is not None and i > upto:
            break
        lo = blocks[i - 1].line_no if i > 0 else 0
        out += [f"{'#' * lvl} {h}" for lvl, h, ln in heads if lvl > 1 and lo < ln < blocks[i].line_no]
        out.append(_block_text(blocks[i]))
    return "\n\n".join(out) + "\n"


def subject_chain(b: Block, coh: dict) -> str:
    """One line per sentence: its subject, and whether it is new (neither a pronoun nor a word of the sentence
    before)."""
    out = []
    for k, (sent, sub) in enumerate(zip(b.sentences, coh.get("subjects", [])), 1):
        mark = "" if sub.get("linked") else " — NEW: not in the sentence before"
        out.append(f"{k}. «{sub.get('text') or '?'}»{mark} — sentence: «{sent}»\n")
    new = sum(1 for s in coh.get("subjects", [])[1:] if not s.get("linked"))
    out.append(f"\nNew subjects: {new} of {max(len(b.sentences) - 1, 0)} sentences after the first.\n")
    return "".join(out)


def enumerations(b: Block, coh: dict) -> str:
    out = []
    for e in coh.get("lists", []):
        k = e.get("s", 0)
        sent = b.sentences[k] if k < len(b.sentences) else ""
        out.append(f"- sentence {k + 1} «{sent}»: items " + ", ".join(f"«{x}»" for x in e.get("items", [])) + "\n")
    return "".join(out)


def slop_requests(doc: Doc) -> list[JudgeRequest]:
    """No slop words: one judge per paragraph, list or table where the script found words of the lists."""
    out = []
    for i, hits in slop_hits(doc):
        b = doc.text.blocks[i]
        what = "paragraph" if b.kind == "paragraph" else b.kind
        lines = "".join(f"- «{w}» ({', '.join(src)})\n" for w, src in hits)
        out.append(JudgeRequest("slop-words", f"{what} at TEXT.md line {b.line_no} ({b.element})",
                                f"## The {what}\n\n{_block_text(b)}\n\n## Words and phrases of the slop lists in it\n\n"
                                f"{lines}"))
    return out


# the seven idiosyncrasies of Chakrabarty, Laban, Wu, «Can AI writing be salvaged?» (CHI 2025, arXiv 2409.14509),
# one judge per kind; tense inconsistency is judged only where the parse found a shift
IDIOSYNCRASIES = ("cliche", "redundant-exposition", "purple-prose", "sentence-structure", "lacks-specificity",
                  "awkward-wording")
# the judges that weigh a sentence against the element's purpose get the element's row of the plan
PURPOSE_GATES = ("redundant-exposition", "lacks-specificity")


def elements_text(doc: Doc) -> list[tuple[str, int, str]]:
    """[(element id, line of its first block, its prose)] in text order: every block that carries text (TEXT_KINDS);
    figures left out."""
    by: dict[str, list[Block]] = {}
    for b in doc.text.blocks:
        if b.element and b.kind in TEXT_KINDS:
            by.setdefault(b.element, []).append(b)
    return [(el, bs[0].line_no, "\n\n".join(_block_text(b) for b in bs)) for el, bs in by.items()]


def tense_lines(b: Block, clauses: list[list[dict]]) -> str:
    out = []
    for k, (sent, cs) in enumerate(zip(b.sentences, clauses), 1):
        tn = ", ".join(f"«{c['verb']}» {c['tense']}" for c in cs) or "no tensed clause"
        out.append(f"{k}. {tn} — sentence: «{sent}»\n")
    return "".join(out)


def idiosyncrasy_requests(doc: Doc, tense: dict[int, list[list[dict]]] | None = None) -> list[JudgeRequest]:
    out = []
    for el, line, text in elements_text(doc):
        r = doc.plan_row(el)
        says = plain(re.sub(r";\s*explains\s*:.*$", "", r.get("says"))) if r is not None else ""
        purpose = (f"## What this element is for (from the plan)\n\n{r.get('kind')}: {says}\n\n"
                   if r is not None else "")
        for gate in IDIOSYNCRASIES:
            head = purpose if gate in PURPOSE_GATES else ""
            out.append(JudgeRequest(gate, f"element {el} at TEXT.md line {line}",
                                    f"{head}## The element's text\n\n{text}\n"))
    for i, clauses in (tense or {}).items():
        b = doc.text.blocks[i]
        out.append(JudgeRequest("tense-shift", f"paragraph at TEXT.md line {b.line_no} ({b.element})",
                                f"## Paragraph\n\n{_block_text(b)}\n\n"
                                f"## The tense of each clause, by the parse\n\n{tense_lines(b, clauses)}"))
    return out


def text_requests(doc: Doc, compound_candidates: list[tuple[Unit, str, dict]],
                  cohesion: dict[int, dict] | None = None,
                  tense: dict[int, list[list[dict]]] | None = None,
                  truncated: dict[int, list[str]] | None = None) -> list[JudgeRequest]:
    out: list[JudgeRequest] = []
    blocks = doc.text.blocks
    secs = sections(doc)
    sec_of_block = {i: sid for sid, idx in secs for i in idx}
    idx_of = dict(secs)

    # term explained and led in: one judge per `explain` term, on its section up to the sentence of first use
    for term, u in first_uses(doc).items():
        if opens_paragraph(u, blocks):
            continue  # already failed by the script part
        sid = sec_of_block.get(u.block)
        before = section_text(doc, sid, idx_of[sid], upto=u.block) if sid else _block_text(blocks[u.block])
        out.append(JudgeRequest("term-explained", f"term «{term}»",
                                f"## Term\n\n{term}\n\n## The sentence of its first use\n\n{u.text}\n\n"
                                f"## The text up to and including that sentence's block\n\n{before}"))

    # no compound sentence, judge part: the sentences the parse is unsure of
    if compound_candidates:
        lines = "".join(f"- {label(u, blocks)}: «{s}» (main verbs by the parse: {', '.join(r['predicates'])}; "
                        f"joined by «{r['joiner'] or '?'}»)\n" for u, s, r in compound_candidates)
        out.append(JudgeRequest("no-compound", "TEXT.md, unsure sentences", f"## Sentences\n\n{lines}"))

    # sentence to sentence, paragraph to paragraph: one judge per paragraph
    for i, b in enumerate(blocks):
        if b.kind not in PROSE_KINDS or not b.element:
            continue
        unit = f"{b.kind} at TEXT.md line {b.line_no} ({b.element})"
        if len(b.sentences) >= 2:
            out.append(JudgeRequest("flow-sentences", unit, f"## Paragraph\n\n{_block_text(b)}\n"))
        coh = (cohesion or {}).get(i)
        if coh and len(b.sentences) >= 3:
            out.append(JudgeRequest("fact-soup", unit, f"## Paragraph\n\n{_block_text(b)}\n\n"
                                    f"## The subject of each sentence, by the parse\n\n{subject_chain(b, coh)}"))
        if coh and coh.get("lists"):
            out.append(JudgeRequest("inline-list", unit, f"## Paragraph\n\n{_block_text(b)}\n\n"
                                    f"## Enumerations the parse found\n\n{enumerations(b, coh)}"))
        prev = i - 1
        if prev >= 0 and blocks[prev].element and _leaf_of(doc, blocks[prev].element) == _leaf_of(doc, b.element):
            lf = doc.plan_row(_leaf_of(doc, b.element))
            topic = (f"{plain(lf.get('heading'))}: {plain(lf.get('covers'))}" if lf else "")
            out.append(JudgeRequest("flow-paragraphs", unit,
                                    f"## The topic of this part (heading: what it covers, from the plan)\n\n{topic}\n\n"
                                    f"## The block before\n\n{_block_text(blocks[prev])}\n\n"
                                    f"## The paragraph checked\n\n{_block_text(b)}\n"))

    # every list or table is led in: one judge per list or table that has a paragraph right before it
    for i, prev in list_lead_ins(doc):
        if prev is None:
            continue  # failed by the script part
        b = blocks[i]
        what = block_name(b)
        last = blocks[prev].sentences[-1] if blocks[prev].sentences else _block_text(blocks[prev])
        out.append(JudgeRequest("list-lead-in", f"{what} at TEXT.md line {b.line_no} ({b.element})",
                                f"## The paragraph right before the {what}\n\n{_block_text(blocks[prev])}\n\n"
                                f"## Its last sentence\n\n{last}\n\n## The {what}\n\n{_block_text(b)}\n"))

    # an announced number equals what follows: one judge per paragraph with a number before a word
    for i, hits in count_hits(doc):
        b = blocks[i]
        nxt = _block_text(blocks[i + 1]) if i + 1 < len(blocks) else "(none: the paragraph ends the text)"
        lines = "".join(f"- «{h}»\n" for h in hits)
        out.append(JudgeRequest("announced-count", f"paragraph at TEXT.md line {b.line_no} ({b.element})",
                                f"## Sentences with a number\n\n{lines}\n## Their paragraph\n\n{_block_text(b)}\n\n"
                                f"## The block after it\n\n{nxt}\n"))

    # section to section, and nothing out of scope: one judge per section, once the section is complete
    need = _brief(doc, "need", "Why the reader came: the Need")
    oos = _brief(doc, "out of scope", "Out of scope")
    for k, (sid, idx) in enumerate(secs):
        if not complete(doc, sid):
            continue
        this = section_text(doc, sid, idx)
        if k == 0:
            prev_txt = "(none: this is the first section)\n"
        else:
            psid, pidx = secs[k - 1]
            prev_txt = section_text(doc, psid, pidx)
        out.append(JudgeRequest("flow-sections", f"section {sid}",
                                need + f"\n## The section before\n\n{prev_txt}\n## The section checked\n\n{this}"))
        out.append(JudgeRequest("out-of-scope", f"section {sid}", oos + f"\n## The text checked\n\n{this}"))

    # no hedging, no reference by number: the script flags, one judge per gate decides
    for gate, finder in (("no-hedging", hedge_hits), ("no-number-reference", number_reference_hits)):
        hits = finder(doc)
        if hits:
            lines = "".join(f"- {label(u, blocks)}: «{s}»\n" for u, s in hits)
            out.append(JudgeRequest(gate, "TEXT.md, flagged sentences", f"## Flagged sentences\n\n{lines}"))
    out += slop_requests(doc)
    out += idiosyncrasy_requests(doc, tense)
    out += table_requests(doc)
    out += text_requests_2311(doc, truncated)
    out += transition_requests(doc)
    return out


# ---------------------------------------------------------------- text: transitions between pieces

GIST_CHARS = 1500  # a table or a list longer than this goes to a transition judge as its first lines only
_FIGURE_LINE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)\s>]+)")


def text_elements(doc: Doc) -> list[tuple[str, list[int]]]:
    """[(element id, its block indexes)] in text order: each run of blocks under one element marker."""
    out: list[tuple[str, list[int]]] = []
    for i, b in enumerate(doc.text.blocks):
        if not b.element:
            continue
        if out and out[-1][0] == b.element and out[-1][1][-1] == i - 1:
            out[-1][1].append(i)
        else:
            out.append((b.element, [i]))
    return out


def _excerpt(b: Block, end: bool) -> tuple[str, str]:
    """(what it is, the text) of a block's end (`end`) or start, for a transition judge: a prose block of up to three
    sentences whole, else its last (first) two sentences; a figure by its caption; a table or a list whole, or its
    first lines when it is long."""
    what = block_name(b) if b.kind != "paragraph" else "paragraph"
    if b.kind == "figure":
        m = _FIGURE_LINE.search(b.text)
        return "figure, its caption", f"«{m.group(1).strip()}» ({m.group(2)})" if m else _block_text(b)
    sents = b.sentences
    if sents:
        if len(sents) <= 3:
            return f"{what}, whole", " ".join(sents)
        return (f"{what}, its last two sentences", " ".join(sents[-2:])) if end else \
            (f"{what}, its first two sentences", " ".join(sents[:2]))
    text = _block_text(b)
    if len(text) <= GIST_CHARS:
        return f"{what}, whole", text
    lines, kept, size = text.splitlines(), [], 0
    for ln in lines:
        if kept and size + len(ln) > GIST_CHARS:
            break
        kept.append(ln)
        size += len(ln) + 1
    return f"{what}, its first lines", "\n".join(kept) + f"\n(… {len(lines) - len(kept)} more lines not shown)"


def _end_of(doc: Doc, idx: list[int]) -> tuple[str, str]:
    return _excerpt(doc.text.blocks[idx[-1]], True)


def _start_of(doc: Doc, idx: list[int]) -> tuple[str, str]:
    return _excerpt(doc.text.blocks[idx[0]], False)


def _headings_before(doc: Doc, i: int) -> list[str]:
    """The text's headings (below the document title) between block i and the block before it."""
    blocks = doc.text.blocks
    lo = blocks[i - 1].line_no if i > 0 else 0
    return [f"{'#' * lvl} {h}" for lvl, h, ln in doc.text.headings if lvl > 1 and lo < ln < blocks[i].line_no]


def _heading_of(doc: Doc, rid: str, first_block: int, deepest: bool) -> str:
    """The heading the text gives a section or subsection that starts at `first_block`: the headings right before it
    (`deepest`: only the last one), else the plan's working title with a note."""
    heads = _headings_before(doc, first_block)
    r = doc.plan_row(rid)
    if heads and deepest and r is not None and r.level == 2 and heads[-1].startswith("## "):
        return (f"{heads[-1]}\n(the section's heading: this subsection is the section's intro and has no heading of "
                "its own)")
    if heads:
        return heads[-1] if deepest else "\n".join(heads)
    return f"(the text gives no heading here; the plan's working title: «{plain(r.get('heading')) if r else rid}»)"


def _part(title: str, what_text: tuple[str, str]) -> str:
    return f"## {title} ({what_text[0]})\n\n{what_text[1]}\n\n"


def transition_requests(doc: Doc) -> list[JudgeRequest]:
    """The seams of the text, one judge each: element to element inside one leaf of the plan (a pair whose later
    element starts with a list, tiles, a table, a yes/no block or steps is list-lead-in's), subsection to subsection
    inside one section (none inside a section marked `subsections: parallel`), section to section. A seam is judged
    once the later piece has text."""
    out: list[JudgeRequest] = []
    blocks = doc.text.blocks
    # an element with no plan row breaks the chain: the elements on either side of it are no direct neighbours
    all_els = text_elements(doc)
    for (e1, i1), (e2, i2) in zip(all_els, all_els[1:]):
        if not _leaf_of(doc, e1) or _leaf_of(doc, e1) != _leaf_of(doc, e2) \
                or blocks[i2[0]].kind in ENUMERATION_KINDS:
            continue
        out.append(JudgeRequest("transition-elements", f"seam {e1} → {e2} at TEXT.md line {blocks[i2[0]].line_no}",
                                _part(f"The end of the earlier element {e1}", _end_of(doc, i1))
                                + _part(f"The start of the later element {e2}", _start_of(doc, i2))))

    # the leaves in text order, each with its elements' blocks
    leaves: list[tuple[str, list[int]]] = []
    for e, idx in ((e, idx) for e, idx in all_els if _leaf_of(doc, e)):
        leaf = _leaf_of(doc, e)
        if leaves and leaves[-1][0] == leaf:
            leaves[-1][1].extend(idx)
        else:
            leaves.append((leaf, list(idx)))
    for (l1, i1), (l2, i2) in zip(leaves, leaves[1:]):
        s1, s2 = doc.section_of(l1), doc.section_of(l2)
        if not s1 or not s2:
            continue
        if s1 == s2:
            sec = doc.plan_row(s1)
            if l1 == l2 or sec is None or sec.get("subsections") == "parallel":
                continue
            out.append(JudgeRequest(
                "transition-subsections", f"seam {l1} → {l2} at TEXT.md line {blocks[i2[0]].line_no}",
                f"## The earlier subsection's heading\n\n{_heading_of(doc, l1, i1[0], True)}\n\n"
                + _part("Its end", _end_of(doc, i1))
                + f"## The next subsection's heading\n\n{_heading_of(doc, l2, i2[0], True)}\n\n"
                + _part("Its start", _start_of(doc, i2))))
        else:
            first1 = next(i for leaf, idx in leaves for i in idx[:1] if doc.section_of(leaf) == s1)
            # the section's own heading only: the headings before its first block may also hold its first
            # subsection's, which is not what the end belongs to; the last subsection's heading is given apart
            last_sub = "" if l1 == s1 else \
                f"## The heading of its last subsection\n\n{_heading_of(doc, l1, i1[0], True)}\n\n"
            out.append(JudgeRequest(
                "transition-sections", f"seam {s1} → {s2} at TEXT.md line {blocks[i2[0]].line_no}",
                f"## The earlier section's heading\n\n{_heading_of(doc, s1, first1, False).splitlines()[0]}\n\n"
                + last_sub + _part("Its end", _end_of(doc, i1))
                + f"## The next section's heading or headings\n\n{_heading_of(doc, s2, i2[0], False)}\n\n"
                + _part("Its start", _start_of(doc, i2))))
    return out


# ---------------------------------------------------------------- text: finders and their judges

WEEKDAY_TOOL = Path(__file__).resolve().parent / "weekday.py"


def _sentences_and_block(title: str, hits: list[str], b: Block) -> str:
    lines = "".join(f"- «{h}»\n" for h in hits)
    return f"## {title}\n\n{lines}\n## Their block\n\n{_block_text(b)}\n"


def text_requests_2311(doc: Doc, truncated: dict[int, list[str]] | None = None) -> list[JudgeRequest]:
    out: list[JudgeRequest] = []
    blocks = doc.text.blocks

    def unit(i: int) -> str:
        return f"{blocks[i].kind} at TEXT.md line {blocks[i].line_no} ({blocks[i].element})"

    # no talk about the document, no announcing later contents: off by default, one judge per flagged block
    for gate, finder in (("no-document-talk", document_talk_hits), ("no-announcing", announcing_hits)):
        for i, hits in finder(doc):
            out.append(JudgeRequest(gate, unit(i), _sentences_and_block("Flagged sentences", hits, blocks[i])))

    # a full-sentence example stands on its own line: one judge per paragraph with an example marker
    for i, hits in example_hits(doc):
        out.append(JudgeRequest("example-own-line", unit(i),
                                _sentences_and_block("Sentences with an example marker", hits, blocks[i])))

    # no truncated sentence: one judge per paragraph the script flagged
    for i, hits in sorted((truncated or {}).items()):
        out.append(JudgeRequest("no-truncated", unit(i),
                                _sentences_and_block("Sentences with no end mark or no verb", hits, blocks[i])))

    # tense against today: one judge per block with a date; weekday: ONE judge with every date sentence and a tool
    dates = date_hits(doc)
    if dates:
        # today's date is part of the tense judges' input on purpose: a sentence right on a later day may be wrong
        # the next, so these judges run again on the first write of a new day
        today = date.today()
        by_block: dict[int, list[str]] = {}
        for u, s in dates:
            by_block.setdefault(u.block, []).append(s)
        for i, hits in by_block.items():
            out.append(JudgeRequest("date-tense", unit(i),
                                    f"## Today\n\n{today.isoformat()} ({today:%A})\n\n"
                                    + _sentences_and_block("Sentences with a date", hits, blocks[i])))
        lines = "".join(f"- {label(u, blocks)}: «{s}»\n" for u, s in dates)
        out.append(JudgeRequest("date-weekday", "TEXT.md, every sentence with a date",
                                f"## The tool\n\npython3 \"{WEEKDAY_TOOL}\" YYYY-MM-DD [YYYY-MM-DD …]\n\n"
                                f"## The year of a date written without one\n\nThe year the text around it gives; "
                                f"else {today.year}.\n\n## Sentences with a date\n\n{lines}"))

    # no repetition across sections: one judge per complete section, against the sections before it
    hits = repeat_hits(doc)
    secs = sections(doc)

    def no_summary(ix: list[int]) -> list[int]:  # a summary repeats by design and has its own gate
        return [i for i in ix if "summary" not in element_kind(doc, blocks[i].element)]
    for k, (sid, idx) in enumerate(secs):
        mine = [(el, first, run) for el, first, run in hits if doc.section_of(el) == sid]
        keep = no_summary(idx)
        prior = "".join(section_text(doc, s, no_summary(ix)) + "\n" for s, ix in secs[:k] if no_summary(ix))
        if not complete(doc, sid) or not keep or (not prior and not mine):
            continue  # the first section with text other than summaries is judged only on a script hit
        before = prior or "(none: no section before this one, summaries left out)\n"
        found = "".join(f"- «{run}» — here in {el}, earlier in {first}\n" for el, first, run in mine) or \
            "(none: no identical run of words; look for the same point in other words)\n"
        out.append(JudgeRequest("no-repetition", f"section {sid}",
                                f"## Identical runs of words a script found\n\n{found}\n"
                                f"## The text before this section\n\n{before}\n"
                                f"## The section checked (summary elements left out)\n\n"
                                f"{section_text(doc, sid, keep)}"))

    # a summary adds nothing new and keeps the qualifiers: one judge per summary element, once the rest is written
    for sid_el in summary_elements(doc):
        mine = [i for i, b in enumerate(blocks) if b.element == sid_el]
        rest = "".join(section_text(doc, s, [i for i in ix if blocks[i].element != sid_el]) + "\n"
                       for s, ix in secs if any(blocks[i].element != sid_el for i in ix))
        out.append(JudgeRequest("summary-faithful", f"summary {sid_el}",
                                f"## The summary (element {sid_el})\n\n"
                                + "\n\n".join(_block_text(blocks[i]) for i in mine)
                                + f"\n\n## The rest of the text\n\n{rest}"))
    return out


# ---------------------------------------------------------------- tables and tiles

def _paragraph_before(doc: Doc, i: int) -> str:
    """The paragraph right before block i (its lead-in, as `list_lead_ins` finds it), or a note that there is none."""
    prev = dict(list_lead_ins(doc)).get(i)
    return _block_text(doc.text.blocks[prev]) if prev is not None else "(none: no paragraph stands right before it)"


def _notes_after(doc: Doc, i: int) -> str:
    """The paragraphs right after block i under the same element marker: a note under a table or tiles."""
    blocks = doc.text.blocks
    out = []
    for b in blocks[i + 1:]:
        if b.element != blocks[i].element or b.kind != "paragraph":
            break
        out.append(_block_text(b))
    return "\n\n".join(out) if out else "(none: nothing follows it under the same element)"


def external_items_request(doc: Doc, i: int, unit: str) -> JudgeRequest:
    """Items from an outside source: every code or name of someone else's list that the block names is
    in TERMS.md, and its mark is met — `explain`: explained here or before; `link`: its gist and a link. The judge
    decides which items come from an outside source, so it runs on every list, table and tiles block of 2+ items."""
    blocks = doc.text.blocks
    terms_file = doc.folder / "TERMS.md"
    terms = terms_file.read_text(encoding="utf-8").strip() if terms_file.exists() else "(there is no TERMS.md)"
    before = "\n\n".join(_block_text(b) for b in blocks[:i]) or "(none: the block is the first in the text)"
    b = blocks[i]
    return JudgeRequest("external-items", unit,
                        f"## The {b.kind} (the block checked)\n\n{_block_text(b)}\n\n"
                        f"## The document's term list (TERMS.md)\n\n{terms}\n\n"
                        f"## The text before the block\n\n{before}\n")


def table_requests(doc: Doc) -> list[JudgeRequest]:
    """The judges of tables, lists and tiles, one per block."""
    out: list[JudgeRequest] = []
    blocks = doc.text.blocks

    def unit(b: Block) -> str:
        return f"{b.kind} at TEXT.md line {b.line_no} ({b.element})"

    for _, b in tables(doc):
        if len(b.rows) >= 2:
            out.append(JudgeRequest("cell-answers-header", unit(b), f"## The table\n\n{_block_text(b)}\n"))
    for i, cols in yes_no_columns(doc):
        b = blocks[i]
        out.append(JudgeRequest("yes-no-grid", unit(b), f"## The table\n\n{_block_text(b)}\n\n"
                                "## Columns a script flagged (a yes/no header, or cells that start with a yes/no "
                                "word)\n\n" + "".join(f"- {c}\n" for c in cols)))
    for i, cells in flat_candidates(doc):
        b = blocks[i]
        out.append(JudgeRequest("table-flat", unit(b), f"## The table\n\n{_block_text(b)}\n\n"
                                "## Cells a script flagged (several parts, or `label: value` pairs)\n\n" +
                                "".join(f"- «{c.strip()}»\n" for c in cells)))
    for i, b in enumerate(blocks):
        if not b.element:
            continue
        n = len(b.items) if b.kind in ITEM_KINDS + ("tiles",) else len(b.rows) - 1 if b.kind == "table" else 0
        if n >= 2:
            head = (f"the yes/no block (items with {YES} are what the thing does, items with {NO} what it does not do)"
                    if b.kind == "yes-no" else b.kind)
            out.append(JudgeRequest("same-kind", unit(b), f"## The {head}\n\n{_block_text(b)}\n"))
        if b.kind == "tiles":
            out.append(JudgeRequest("tiles-choice", unit(b),
                                    f"## The paragraph right before the tiles\n\n{_paragraph_before(doc, i)}\n\n"
                                    f"## The tiles (one list item per tile: its title in bold, then its body)\n\n"
                                    f"{_block_text(b)}\n"))
        if n >= 2:
            out.append(external_items_request(doc, i, unit(b)))
        if b.kind in ("table", "tiles"):
            what = "the tiles (one list item per tile: its title in bold, then its body)" if b.kind == "tiles" \
                else "the table (its first row is the header)"
            out.append(JudgeRequest("no-hidden-fact", unit(b),
                                    f"## {what[0].upper() + what[1:]}\n\n{_block_text(b)}\n\n"
                                    f"## What follows it under the same element (a note, if any)\n\n"
                                    f"{_notes_after(doc, i)}\n"))
    return out
