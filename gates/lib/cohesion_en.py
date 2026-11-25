"""Paragraph cohesion, the parse for English. Runs under uv with spaCy (see common.UV_SPACY).

stdin: a JSON list of paragraphs, each a list of sentences. stdout: a JSON list, one entry per paragraph:
  {"subjects": [{"text": "the open risks", "head": "risk", "pron": false, "linked": true}, ...],
   "lists": [{"s": 2, "items": ["web search", "memory", "the transcripts"]}, ...]}

subjects: the subject of each sentence's main clause, as its noun phrase. `linked` says whether the sentence's
subject is a pronoun, a word of the sentence before (its head's lemma) or the subject the paragraph is on (the last
subject that was not a pronoun); the first sentence is linked.
lists: every coordination of three or more items in one sentence («A, B and C»), as the parse finds it.
Both are marks for the judges (gate-fact-soup, gate-inline-list); the script fails nothing by itself.
"""
import json
import sys

import spacy

SUBJ = {"nsubj", "nsubjpass", "csubj", "csubjpass", "expl"}
PRON = {"it", "they", "this", "these", "that", "those", "he", "she", "we", "its", "their", "which"}


def _short(toks, n=8):
    words = [t.text for t in toks if not t.is_space]
    return " ".join(words[:n]) + (" …" if len(words) > n else "")


def subject(sent, chunks):
    root = sent.root
    cand = [c for c in root.children if c.dep_ in SUBJ]
    if not cand:  # «X is Y because …» parsed with the copula elsewhere: take the first subject in the sentence
        cand = [t for t in sent if t.dep_ in SUBJ]
    if not cand:
        return None
    s = cand[0]
    span = next((c for c in chunks if c.start <= s.i < c.end), None)
    text = span.text if span is not None else _short(s.subtree)
    return {"text": text, "head": s.lemma_.lower(), "pron": s.lower_ in PRON or s.pos_ == "PRON"}


def coordinations(sent):
    """Items of every coordination with three or more members."""
    out = []
    for t in sent:
        if t.dep_ == "conj":
            continue
        items, todo = [t], [t]
        while todo:
            x = todo.pop()
            for c in x.children:
                if c.dep_ == "conj":
                    items.append(c)
                    todo.append(c)
        if len(items) < 3:
            continue
        items.sort(key=lambda x: x.i)
        texts = []
        for it in items:
            skip = set()
            for c in it.children:
                if c.dep_ in ("conj", "cc", "punct", "preconj"):
                    skip |= {y.i for y in c.subtree}
            texts.append(_short([y for y in it.subtree if y.i not in skip], 6))
        out.append(texts)
    return out


def analyse(nlp, sentences):
    subjects, lists = [], []
    prev_lemmas, topic = set(), ""
    for i, s in enumerate(sentences):
        doc = nlp(s)
        chunks = list(doc.noun_chunks)
        subj = None
        for sent in doc.sents:
            subj = subject(sent, chunks)
            if subj:
                break
        if subj is None:
            subj = {"text": "", "head": "", "pron": False}
        subj["linked"] = bool(i == 0 or subj["pron"] or (subj["head"] and (subj["head"] in prev_lemmas
                                                                         or subj["head"] == topic)))
        if subj["head"] and not subj["pron"]:
            topic = subj["head"]
        subjects.append(subj)
        for items in coordinations(doc):
            lists.append({"s": i, "items": items})
        prev_lemmas = {t.lemma_.lower() for t in doc if t.is_alpha and not t.is_stop}
    return {"subjects": subjects, "lists": lists}


def main():
    paragraphs = json.load(sys.stdin)
    nlp = spacy.load("en_core_web_sm", exclude=["ner"])
    print(json.dumps([analyse(nlp, p) for p in paragraphs], ensure_ascii=False))


if __name__ == "__main__":
    main()
