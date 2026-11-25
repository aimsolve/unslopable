"""The script gates of one file in order: `run_plan` for PLAN.md, `run_text` for TEXT.md. The hook runs the
spaCy-based ones and the figure scripts itself."""
from __future__ import annotations

from docs import Doc, PLAN_FILE
from common import Failure, Unit, body_units, drop_off, gates_off, plan_headings, where
from fact_one_place import gate_fact_one_place
from formats import fenced_format, gate_switches, plan_steps_form, text_format, tiles_format
from heading_max_words import gate_heading_max_words
from heading_no_colon_dash import gate_heading_no_colon_dash
from leftover_markers import gate_leftover_markers
from links import gate_links
from list_lead_in import gate_list_lead_in
from no_compound import gate_compound
from no_semicolon import gate_semicolons
from one_sentence_per_item import gate_one_sentence_per_item
from out_of_scope import gate_oos_search
from plan_elements_written import gate_plan_elements_written
from plan_length import gate_plan_length
from plan_wall import gate_plan_wall
from sentence_max_words import gate_sentence_words
from table_duplicate_row import gate_table_duplicate_rows
from table_flat import gate_table_flat
from table_footnote import gate_table_footnotes
from term_counts import gate_term_counts
from term_first_use import gate_term_first_sentence
from term_marked import gate_term_marked
from terms_placed import gate_terms_placed
from text_length import gate_text_length
from tiles import gate_plan_tiles, gate_text_tiles


def run_plan(doc: Doc, upto: int) -> list[Failure]:
    """The format problems of PLAN.md and the gates of its levels 1..upto."""
    out = [Failure("format", PLAN_FILE, "", p) for p in doc.plan_problems]
    if not doc.plans.get(1):
        out.append(Failure("format", PLAN_FILE, "", "no sections: the plan is one list whose top items are sections, "
                                                    "`id · **heading** · what it covers · N lines`"))
        return out
    for level in range(1, upto + 1):
        if not doc.plans.get(level):
            continue
        if level in (1, 2):
            heads = plan_headings(doc, level)
            out += gate_heading_no_colon_dash(heads) + gate_heading_max_words(doc, heads)
        if level == 3:
            out += gate_fact_one_place(doc)
            out += gate_terms_placed(doc)
            out += gate_plan_wall(doc)
            out += gate_plan_tiles(doc)
            out += plan_steps_form(doc)
        out += gate_plan_length(doc, level)
        pieces = [(f"{PLAN_FILE} {x.id}", " ".join(v for k, v in x.cells.items() if k not in ("parent", "lines")))
                  for r in doc.plans[level] for x in [r] + r.tiles]
        out += gate_oos_search(doc, pieces)
    out += gate_switches(doc)
    return drop_off(doc, _dedupe(out), "plan")


def run_text(doc: Doc, notices: list[str]) -> tuple[list[Failure], list[tuple[Unit, str, dict]]]:
    if not doc.plans.get(3):
        return [Failure("format", "TEXT.md", "", f"{PLAN_FILE} has no elements; the text is written from the "
                                                 "approved plan, element by element")], []
    out = text_format(doc)
    heads = [(f"TEXT.md line {ln}", h) for _, h, ln in doc.text.headings]
    out += gate_heading_no_colon_dash(heads) + gate_heading_max_words(doc, heads)
    out += gate_sentence_words(doc)
    out += gate_semicolons(doc)
    out += gate_one_sentence_per_item(doc)
    out += gate_list_lead_in(doc)
    out += tiles_format(doc)
    out += fenced_format(doc)
    out += gate_text_tiles(doc)
    out += gate_table_footnotes(doc)
    out += gate_table_duplicate_rows(doc)
    out += gate_table_flat(doc)
    out += gate_term_first_sentence(doc)
    out += gate_term_marked(doc)
    out += gate_term_counts(doc)
    out += gate_text_length(doc)
    out += gate_switches(doc)
    pieces = [(where(u, doc.text.blocks), u.text) for u in body_units(doc.text.blocks)]
    pieces += [(f"TEXT.md line {ln}", h) for _, h, ln in doc.text.headings]
    out += gate_oos_search(doc, pieces)
    # final document: every plan element up to the last written one, no leftover markers, links resolve
    out += gate_plan_elements_written(doc, notices)
    out += gate_leftover_markers(doc)
    out += gate_links(doc, notices)
    errors, cands = gate_compound(doc, notices) if "no-compound" not in gates_off(doc) else ([], [])
    out += errors
    return drop_off(doc, _dedupe(out), "text"), cands


def _dedupe(fs: list[Failure]) -> list[Failure]:
    seen, out = set(), []
    for f in fs:
        k = (f.gate, f.where, f.quote, f.why)
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out
