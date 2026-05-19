# Layer10 knowledge graph — final evaluation numbers

Run: `evals/runs/20260906T155126Z` · 52 gold items × 3 reps = 156 responses · 0 timeouts

## Corpus

Single repository, `tiangolo/sqlmodel`. The earlier corpus fused two unrelated
repos (`makeplane/plane` commits with `tiangolo/sqlmodel` PRs and issues), which
produced cross-repo `REFERENCES` edges and made every metric meaningless. That
corpus was rebuilt from scratch and the fusion bug fixed at source.

- 11,610 nodes: 4,586 Commit · 1,402 FileNode · 1,242 Person · 1,125 PullRequest ·
  880 DesignDecision · 601 Discussion · 353 Issue
- 28,734 relationships, including 845 `DECISION_FOR`, 380 `INTRODUCES`,
  131 `SUPERSEDES`, 36 `CLOSES`
- Frozen: `evals/v3/manifest.json` (git rev, corpus SHA-256, model versions)
- Models: extraction `gemini-2.5-pro`, RAG `gemini-2.5-pro`, parser `gemini-2.5-flash`

## Headline

| Metric | Value | n |
|---|---|---|
| Cite-precision (fact+current, mean of per-item medians) | **0.447** | 30 |
| Hit@8, answerable | **0.800** | 40 |
| Refusal accuracy | **1.000** | 12 |
| Invented source IDs | **0** | 52 items / 171 citation markers |
| Superseded citations | **0** | 10 |
| Span alignment (extraction) | **0.800** | 80 |

Cite-precision perfect-item rate 0.40, Wilson 95% CI [0.246, 0.577].

## By slice

| Slice | n | Cite-precision | Hit@8 |
|---|---|---|---|
| fact | 20 | 0.633 | 0.90 |
| structural | 10 | 0.200 | 1.00 |
| current | 10 | 0.075 | 0.40 |
| unanswerable | 12 | — | refused 12/12 |

## Effect of the retrieval fixes

Both runs use the same clean corpus, the same gold set, and the same scorer.
The delta is the ranking and supersession work.

| Metric | Before | After |
|---|---|---|
| Cite-precision | 0.406 | **0.447** |
| Hit@8 | 0.625 | **0.800** |
| Hit@8, structural slice | 0.30 | **1.00** |
| Cite-precision, fact slice | 0.583 | **0.633** |

The structural slice drove the gain. Those questions name an artifact ("Which PR
closed issue #64?"), and the named entity was being outranked by lexical noise —
a dependabot PR titled "Bump tiangolo/issue-**manager**" beat the actual issue.
Two causes: a named entity earned only a 1.5× multiplier inside a product of
eight factors, and `kw_score` multiplied the whole score, so the correct answer
scored near zero because a PR's title shares no vocabulary with a question asking
about it. For a graph retriever the edge is the evidence, not the wording. Named
entities are now pinned, their 1-hop neighbours enter the candidate pool, and
adjacency substitutes for lexical overlap.

## Known limitation

The `current` slice is the weak point: cite-precision 0.075, hit@8 0.40. These
are semantic questions with no named entity ("How does the project currently make
SQLAlchemy components accessible?"), and the graph holds many topically adjacent
decisions. Retrieval returns a neighbour of the right answer — for that question
it returned `decision:re-export-sqlalchemy-engine` where gold is
`decision:comprehensively-re-export-sqlalchemy-classes`.

These are genuine misses, not scoring artifacts. Both nodes were inspected and
describe different scopes (one piecemeal re-export, one comprehensive), so
near-duplicate credit is not warranted. Relatedly, the graph marks both as
`is_current=true` even though the comprehensive decision conceptually supersedes
the piecemeal one, which is a gap in supersession detection during extraction.

## Why no cluster-aware scoring

Cluster-aware scoring was built and then rejected on evidence. Near-duplicate
clustering at threshold 0.6 grouped genuinely distinct decisions — "drop Python
3.6 support" with "add Python 3.13 support" — so crediting cluster members as
interchangeable would have inflated the result. Decisively, **zero gold keys fall
into any cluster**, so cluster-aware and strict scoring are numerically identical
on this set. Strict scoring is reported.

## Metric definitions

- **Cite-precision**: of the source keys cited in an answer, the fraction present
  in that item's gold key set. Per item, the median across 3 reps; reported as the
  mean of those medians over the fact and current slices.
- **Invented source ID**: a citation marker that resolves to no retrieved source
  (out of range, or a source carrying no key). A marker pointing at a real node is
  grounded, so citing one in a refusal is not invention.
- **Refusal accuracy**: on unanswerable items, the fraction where the majority of
  reps deny the requested fact without inventing a marker. A refusal may cite real
  evidence to explain the near miss; an answer that asserts a fact does not count
  as a refusal.
- **Hit@8**: gold key appears in the top 8 retrieved.
- **Superseded citation**: a cited key listed as forbidden (a decision that was
  superseded) on a current-state question.

## Reproducing

```
python evals/build_gold_v3.py          # gold set (52 items)
python evals/freeze_manifest.py        # corpus + model provenance
python evals/backfill_is_current.py    # is_current from SUPERSEDES edges
python evals/run_eval.py --gold evals/v3/gold_v3.jsonl --reps 3 --timeout 300
python evals/score.py evals/runs/<ts>
```
