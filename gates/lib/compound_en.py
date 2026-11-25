"""No compound sentence, the parse for English. Runs under uv with spaCy (see common.UV_SPACY).

stdin: a JSON list of sentences. stdout: a JSON list, one entry per sentence:
  null                                  one main clause (subordinate clauses and several verbs of one subject are fine)
  {"verdict": "error", ...}             two main clauses with different subjects joined by a comma, ";", "and",
                                        "but", "or", "nor", "so", "yet"
  {"verdict": "candidate", ...}         the parse is unsure: a colon or a dash joins them, a pronoun subject that may
                                        be the first subject again, parataxis, or the sentence splits in two;
                                        the judge decides
Each entry also has "predicates" (the main verbs) and "joiner".

Built as another project's clause splitter does it for Polish (12.11), with English dependency labels: a main
predicate is the root or a verb coordinated (`conj`) with a main predicate. Relative, adverbial and complement
clauses (relcl, acl, advcl, ccomp, xcomp) are subordinate and never count.
"""
import json
import sys

import spacy

ERROR_JOINERS = {",", ";", "and", "but", "or", "nor", "so", "yet"}
SUBJ = {"nsubj", "nsubjpass", "expl", "csubj", "csubjpass"}
PRED_POS = {"VERB", "AUX"}


def subject(tok):
    for c in tok.children:
        if c.dep_ in SUBJ:
            return c
    return None


def joiner(doc, prev, p):
    """The word or mark that joins predicate p to the clause before it."""
    left = p.left_edge.i
    for k in range(left - 1, prev.i, -1):
        t = doc[k]
        if t.dep_ == "cc" or t.pos_ == "CCONJ":
            return t.lower_
        if t.text in (",", ";", ":", "—", "–", "-"):
            return t.text
        if not t.is_punct:
            break
    # spaCy hangs "and" on the first verb; find a cc or mark right before the conjunct's subtree
    for c in prev.children:
        if c.dep_ == "cc" and prev.i < c.i < p.i:
            return c.lower_
    return ""


def analyse(nlp, sentence):
    doc = nlp(sentence)
    sents = list(doc.sents)
    roots = [s.root for s in sents]
    if len(sents) > 1 and sum(1 for r in roots if r.pos_ in PRED_POS and subject(r) is not None) > 1:
        return {"verdict": "candidate", "predicates": [r.text for r in roots], "joiner": "sentence split"}
    root = roots[0]
    main = [root]
    frontier = [root]
    while frontier:
        h = frontier.pop()
        for c in h.children:
            if c.dep_ == "conj" and (c.pos_ in PRED_POS or subject(c) is not None):
                main.append(c)
                frontier.append(c)
    main.sort(key=lambda t: t.i)
    para = [c for c in root.children if c.dep_ == "parataxis" and c.pos_ in PRED_POS and subject(c) is not None]
    words = [t.text for t in main + para]
    if para:
        return {"verdict": "candidate", "predicates": words, "joiner": "parataxis"}
    if len(main) < 2:
        return hidden(doc, words)
    first_subj = subject(main[0])
    for prev, p in zip(main, main[1:]):
        own = subject(p)
        if own is None:
            continue  # several verbs of one subject
        j = joiner(doc, prev, p)
        same = first_subj is not None and own.lower_ == first_subj.lower_ and own.pos_ == "PRON"
        if same:
            if j in ("and", "or"):
                continue
            return {"verdict": "candidate", "predicates": words, "joiner": j}
        if own.pos_ == "PRON" and own.lower_ in ("it", "they", "he", "she", "this", "that", "these", "those"):
            return {"verdict": "candidate", "predicates": words, "joiner": j}
        if j in ERROR_JOINERS:
            return {"verdict": "error", "predicates": words, "joiner": j}
        return {"verdict": "candidate", "predicates": words, "joiner": j}
    return hidden(doc, words)


FINITE = {"VBZ", "VBP", "VBD", "MD"}
WH = {"WDT", "WP", "WP$", "WRB"}


def finite(t):
    return t.tag_ in FINITE or any(c.dep_ in ("aux", "auxpass") and c.tag_ in FINITE for c in t.children)


def subordinated(t):
    return any(c.dep_ == "mark" for c in t.children) or t.left_edge.tag_ in WH or any(
        c.tag_ in WH and c.i < t.i for c in t.children)


def hidden(doc, words):
    """A main clause the small model hangs on another one as ccomp/advcl/dep: «Owners add rooms; builders remove
    them» (add = ccomp of remove), «Water stays in the tank and the pump keeps…» (keeps = advcl). A finite verb with no
    subordinating word is a clause of its own: before a semicolon with its own subject it is an error, otherwise the
    judge decides. A complement clause after its verb («the maker says the water stays») is normal and skipped."""
    for t in doc:
        if t.pos_ not in PRED_POS or t.dep_ not in ("ccomp", "advcl", "dep", "parataxis"):
            continue
        if not finite(t) or subordinated(t):
            continue
        if t.dep_ == "ccomp" and t.i > t.head.i:
            continue
        ws = words + [t.text] if t.text not in words else words
        if t.i < t.head.i:
            between = {doc[k].text for k in range(t.right_edge.i + 1, t.head.i)}
            if subject(t) is not None and ";" in between:
                return {"verdict": "error", "predicates": [t.text, t.head.text], "joiner": ";"}
            mark = next((x for x in (";", ":", "—", "–", ",") if x in between), "")
            return {"verdict": "candidate", "predicates": [t.text, t.head.text], "joiner": mark}
        return {"verdict": "candidate", "predicates": ws, "joiner": ""}
    return None


def main():
    sentences = json.load(sys.stdin)
    nlp = spacy.load("en_core_web_sm", exclude=["ner"])
    print(json.dumps([analyse(nlp, s) for s in sentences], ensure_ascii=False))


if __name__ == "__main__":
    main()
