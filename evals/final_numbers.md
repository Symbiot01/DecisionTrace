# Final eval numbers

## Before → after (gold.jsonl) → gold_v2 unanswerables

| Metric | Before | After (v1) | Final (v2 unans) |
|--------|--------|------------|------------------|
| Cite-precision X | 37.8% | 43.3% | **43.3%** (n=30) |
| Invented source_ids | 9/50 | 5/50 | **0/50** |
| Superseded citations | 0/10 | 0/10 | **0/10** |
| Refusal accuracy | 0.100 | 0.500 | **1.000** (n=10) |
| Hit@8 | 0.575 | 0.550 | 0.550 |
| Span alignment | 0.800 | 0.800 | 0.800 |

## CV line

On gold repo Q&A (fact/current/unanswerable): **43.3** cite-precision and **0** invented source_ids; SUPERSEDED claims skipped (**0** superseded citations).

Print literal zeros on PDF: **True**
Remaining unanswerable failures: none
