# Eval report: `20260905T183052Z`

- Items: **50**
- Cite-precision (fact+current, mean of per-item medians): **0.433** (n=30) → CV X ≈ **43.3%**
- Invented source ids: **5** / 50 (target 0)
- Superseded citations: **0** / 10 (target 0)
- Refusal accuracy: **0.500** (n=10)
- Hit@8 (answerable): **0.550** (n=40)
- Span alignment (extraction): **0.800** (n=80)

## By slice

- **current** (n=10): cite=0.3, hit@8=0.4, invented=0, superseded=0
- **fact** (n=20): cite=0.5, hit@8=0.65, invented=0, superseded=0
- **structural** (n=10): cite=0.0, hit@8=0.5, invented=0, superseded=0
- **unanswerable** (n=10): cite=None, hit@8=0.0, invented=5, superseded=0

## Failures (diagnostic)

- `current-002` [current]: retrieval_miss
- `current-003` [current]: retrieval_miss
- `current-004` [current]: retrieval_miss
- `current-005` [current]: retrieval_miss
- `current-007` [current]: retrieval_miss
- `current-010` [current]: retrieval_miss
- `fact-002` [fact]: retrieval_miss
- `fact-004` [fact]: retrieval_miss
- `fact-005` [fact]: retrieval_miss
- `fact-006` [fact]: retrieval_miss
- `fact-007` [fact]: retrieval_miss
- `multihop-002` [fact]: retrieval_miss
- `multihop-003` [fact]: retrieval_miss
- `structural-001` [structural]: retrieval_miss
- `structural-002` [structural]: retrieval_miss
- `structural-003` [structural]: retrieval_miss
- `structural-005` [structural]: retrieval_miss
- `structural-006` [structural]: retrieval_miss
- `unanswerable-004` [unanswerable]: refusal_fail
- `unanswerable-006` [unanswerable]: refusal_fail
- `unanswerable-007` [unanswerable]: refusal_fail
- `unanswerable-008` [unanswerable]: refusal_fail
- `unanswerable-010` [unanswerable]: refusal_fail
