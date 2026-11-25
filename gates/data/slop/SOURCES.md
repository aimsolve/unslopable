# Slop word lists — sources

The gate «No slop words» (`gates/library.md`) flags every word and phrase of these four files, merged whole
(nothing cut, function words and fiction names included); one judge per paragraph decides each hit.
The files are copied unchanged from their repositories on 2026-11-23.

| File | What it is | Source | Licence |
|---|---|---|---|
| `kobak_excess_words.csv` | 900 words whose frequency in PubMed abstracts rose sharply after ChatGPT, 2013–2024, annotated content / style | Kobak, González-Márquez, Horvát, Lause. «Delving into LLM-assisted writing in biomedical publications through excess vocabulary», Science Advances 2025 (arXiv 2406.07016). github.com/berenslab/llm-excess-vocab, `results/excess_words.csv`, commit 53db991 | MIT |
| `antislop_slop_words.json` | 2000 words over-represented in LLM output against a human baseline, with counts (measured on creative writing) | Paech et al. «Antislop: A Comprehensive Framework for Identifying and Eliminating Repetitive Patterns in Language Models», ICLR 2026 (arXiv 2510.15061). github.com/sam-paech/antislop-sampler, `slop_words_2025-04-07.json`, commit 0ae330e | Apache-2.0 |
| `antislop_slop_phrases.json` | 2500 over-represented phrases, with counts | same repository, `slop_phrases_2025-04-07.json` | Apache-2.0 |
| `antislop_hand_list.json` | 517 words and phrases with sampler weights: the measured list supplemented by phrases LLM users dislike | same repository, `slop_phrase_prob_adjustments.json` | Apache-2.0 |

Leading or trailing spaces and commas of an entry (the hand list has a few, like `" ,rasped"`) are dropped when the
lists are read; matching is whole-word and case-insensitive.
