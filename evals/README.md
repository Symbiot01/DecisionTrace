# Layer10 evaluation harness

Frozen gold set and rule-based scoring for the claim-graph model.

## Quick path

```bash
# 1) Mine candidates + span alignment (read-only Neo4j + timeline)
python evals/mine_candidates.py

# 2) Draft questions (Gemini temperature=0), then adjudicate into gold.jsonl
python evals/gen_questions.py
# (human adjudication → evals/gold.jsonl; sha256 recorded in manifest.json)

# 3) Backfill supersession flags (after retrieval fixes land)
python evals/backfill_is_current.py

# 4) Run Ask/Query against a live API (3 reps / item)
python -m layerten.api   # separate terminal, UVICORN_RELOAD=0
python evals/run_eval.py --reps 3

# 5) Score the latest run
python evals/score.py    # or: python evals/score.py evals/runs/<ts>
```

## Artifacts

| Path | Role |
|------|------|
| `manifest.json` | Corpus freeze: checkpoint, timeline sha256, graph counts, gold sha256 |
| `candidates.jsonl` | Auto-mined fact/current/structural/unanswerable rows |
| `span_alignment.json` | Extraction faithfulness (`evidence_excerpt` ⊆ source body) |
| `gold.jsonl` | Frozen adjudicated set v1 |
| `gold_v2.jsonl` | Same fact/current/structural; unanswerables replaced with unrelated fixtures (use this for CV zeros) |
| `final_numbers.md` | Before/after/final metrics + CV line |
| `runs/<ts>/raw/` | Full Ask/Query payloads (gitignored) |
| `runs/<ts>/metrics.json` | Aggregate metrics + per-item diagnostics |
| `runs/<ts>/report.md` | Human-readable summary |

## Metrics (CV)

- **X cite-precision**: mean of per-item median cite-precision on `fact` + `current`
- **0 invented source_ids**: citation markers that do not map into `sources`, or any cite on `must_refuse`
- **0 superseded citations**: cited key ∈ `forbidden_keys` on `current` items

## Unit tests

```bash
pip install -r requirements-dev.txt
pytest tests/test_validator.py -q
```
