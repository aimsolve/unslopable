"""Sentences with no verb, the parse for English. Runs under uv with spaCy (see common.UV_SPACY).

stdin: a JSON list of sentences. stdout: a JSON list of booleans, one per sentence: true when the parse finds a verb
or an auxiliary in it. A sentence with none is a candidate for the judge gate-no-truncated; the script fails nothing
by itself.
"""
import json
import sys

import spacy


def main() -> None:
    sentences = json.load(sys.stdin)
    nlp = spacy.load("en_core_web_sm", disable=["ner"])
    out = [any(t.pos_ in ("VERB", "AUX") for t in doc) for doc in nlp.pipe(sentences)]
    json.dump(out, sys.stdout)


if __name__ == "__main__":
    main()
