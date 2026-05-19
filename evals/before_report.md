# Eval report: `20260905T181553Z`

- Items: **50**
- Cite-precision (fact+current, mean of per-item medians): **0.378** (n=30) → CV X ≈ **37.8%**
- Invented source ids: **9** / 50 (target 0)
- Superseded citations: **0** / 10 (target 0)
- Refusal accuracy: **0.100** (n=10)
- Hit@8 (answerable): **0.575** (n=40)
- Span alignment (extraction): **0.800** (n=80)

## By slice

- **current** (n=10): cite=0.275, hit@8=0.6, invented=0, superseded=0
- **fact** (n=20): cite=0.4292, hit@8=0.6, invented=0, superseded=0
- **structural** (n=10): cite=0.4, hit@8=0.5, invented=0, superseded=0
- **unanswerable** (n=10): cite=None, hit@8=0.0, invented=9, superseded=0

## Failures (diagnostic)

- `current-003` [current]: retrieval_miss
- `current-004` [current]: retrieval_miss
- `current-005` [current]: retrieval_miss
- `current-007` [current]: retrieval_miss
- `fact-002` [fact]: retrieval_miss
- `fact-004` [fact]: retrieval_miss
- `fact-005` [fact]: retrieval_miss
- `fact-006` [fact]: retrieval_miss
- `fact-007` [fact]: retrieval_miss
- `fact-008` [fact]: retrieval_miss
- `fact-009` [fact]: retrieval_miss
- `multihop-003` [fact]: retrieval_miss
- `structural-001` [structural]: retrieval_miss
- `structural-002` [structural]: retrieval_miss
- `structural-003` [structural]: retrieval_miss
- `structural-005` [structural]: retrieval_miss
- `structural-006` [structural]: retrieval_miss
- `unanswerable-001` [unanswerable]: refusal_fail
- `unanswerable-003` [unanswerable]: refusal_fail
- `unanswerable-004` [unanswerable]: refusal_fail
- `unanswerable-005` [unanswerable]: refusal_fail
- `unanswerable-006` [unanswerable]: refusal_fail
- `unanswerable-007` [unanswerable]: refusal_fail
- `unanswerable-008` [unanswerable]: refusal_fail
- `unanswerable-009` [unanswerable]: refusal_fail
- `unanswerable-010` [unanswerable]: refusal_fail
