"""Tense of each finite clause, the parse for English. Runs under uv with spaCy (see common.UV_SPACY).

stdin: a JSON list of paragraphs, each a list of sentences. stdout: a JSON list, one entry per paragraph:
  [[{"verb": "was released", "tense": "past"}, {"verb": "supports", "tense": "present"}], ...]   one list per sentence

A clause's tense comes from its first auxiliary or, with none, from its verb: will/shall → future; a past-tense form
(VBD) → past; a present-tense form (VBZ/VBP) → present. Clauses with another auxiliary (can, may, should…) and
non-finite verbs have no tense and are left out. These are marks for the judge `gate-tense-shift`, which decides
whether a shift is an error; the script fails nothing by itself.
"""
import json
import sys

import spacy

CLAUSE = {"ROOT", "conj", "ccomp", "advcl", "relcl", "acl", "parataxis", "csubj", "pcomp"}
FUTURE = {"will", "shall", "'ll", "wo"}


def tense(h):
    aux = sorted((c for c in h.children if c.dep_ in ("aux", "auxpass")), key=lambda c: c.i)
    if aux:
        a = aux[0]
        if a.lower_ in FUTURE:
            return "future", aux
        if a.tag_ == "MD":
            return None, aux
        if a.tag_ == "VBD":
            return "past", aux
        if a.tag_ in ("VBZ", "VBP"):
            return "present", aux
        return None, aux
    if h.tag_ == "VBD":
        return "past", []
    if h.tag_ in ("VBZ", "VBP"):
        return "present", []
    return None, []


def analyse(nlp, sentences):
    out = []
    for s in sentences:
        clauses = []
        for t in nlp(s):
            if t.pos_ not in ("VERB", "AUX") or t.dep_ not in CLAUSE:
                continue
            tn, aux = tense(t)
            if tn:
                words = sorted(aux + [t] + [c for c in t.children if c.dep_ == "neg"], key=lambda x: x.i)
                clauses.append({"verb": "".join(w.text_with_ws for w in words).strip(), "tense": tn})
        out.append(clauses)
    return out


def main():
    paragraphs = json.load(sys.stdin)
    nlp = spacy.load("en_core_web_sm", exclude=["ner"])
    print(json.dumps([analyse(nlp, p) for p in paragraphs], ensure_ascii=False))


if __name__ == "__main__":
    main()
