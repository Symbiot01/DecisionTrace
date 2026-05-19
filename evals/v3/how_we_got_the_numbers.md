# How the Layer10 numbers were produced

A record of what was measured first, every defect that measurement exposed, and
how each was fixed. Written so the numbers in `final_numbers.md` can be defended
line by line.

## The first thing: measure before touching anything

There was no prior system to compare against, so the first move was to build a
frozen gold set and score a baseline — not to start improving retrieval. Without
a baseline there is no way to tell a fix from a regression.

1. `mine_candidates.py` — pull candidate facts from Neo4j and the unified timeline.
2. `gen_questions.py` — generate a natural-language question per candidate at
   temperature 0.
3. `run_eval.py` — replay the gold set against `/api/ask` and `/api/query`,
   3 reps each, persisting every raw response.
4. `score.py` — rule-based metrics: cite-precision, invented source IDs,
   superseded citations, refusal accuracy, hit@N.

**Baseline: cite-precision 40.8%, hit@8 0.55.** Everything below came from asking
why those two numbers were low, and each answer was a real defect rather than a
tuning opportunity.

---

## Round 1 — the baseline was measuring a broken system

### The parser had been silently dead

`question_parser.py` hardcoded `gemini-2.0-flash`. That endpoint had been
retired, so every parse raised, was caught by a broad `except`, and fell back to
naive keyword extraction. Intent and entity references were never being
extracted at all — logged at `warning` and therefore invisible.

Fixed by moving the model to `GEMINI_MODEL_PARSER` config, logging the failure at
`error` with the model name, and adding a startup probe in `main.py` that
verifies every configured model is reachable before serving traffic. A silent
degradation became a loud one.

### The ranker put a Lucene score in a probability slot

`evidence_conf` was being filled with the raw full-text score when a node had no
confidence-bearing claims. Lucene scores are unbounded, so an evidence-free node
scoring 19.5 outranked a well-evidenced node at 0.9 confidence.

Fixed by normalising the full-text score into its own bounded multiplier,
replacing raw keyword overlap with IDF-weighted coverage damped by text length
(so long commit messages stop winning on incidental term matches), giving
excerpt-bearing nodes an explicit bonus, and adding a relative score floor.
A future-dated timestamp was also scoring as *freshest*; it now scores as unknown.

### The corpus was two repositories fused together

The graph held `makeplane/plane` commits alongside `tiangolo/sqlmodel` PRs and
issues. Deduplication keyed on event ID without a repo scope, so a second repo's
events merged into the first. This manufactured cross-repo `REFERENCES` edges and
wrong `source_url`s, which made every metric meaningless.

This is the defect that invalidated the baseline. Fixed at source rather than by
cleaning data: a `repo` field on every raw event, repo-scoped `get_fetched_ids`,
`assert_single_repo()` before a fetch runs, and an origin guard in `clone_repo`
that refuses to reuse a clone pointing at a different remote. Then a full rebuild
on `tiangolo/sqlmodel` alone, with a regression test on the scoping logic.

### Extraction was dropping ~30% of events without saying so

`agentic_extract` iterated `candidate.content.parts` unconditionally. When Gemini
returned no parts — blocked content, or `MAX_TOKENS` — that raised
`TypeError: NoneType is not iterable`, was swallowed, and the event produced
nothing.

Fixed by guarding both `response.candidates` and `candidate.content.parts`, and
distinguishing the two cases: if tool calls already happened, an empty response
means completion; if not, it is a failure worth retrying.

### Processing deadlocked on the final batch

All worker threads sat in `futex_do_wait`. Three compounding causes: the Gemini
client had no request timeout, concurrency was set to 400, and the batch waited
on every future unconditionally.

Fixed with `GEMINI_REQUEST_TIMEOUT_S` on the pooled client, concurrency lowered
to 32, and `as_completed(timeout=AGENTIC_BATCH_TIMEOUT_S)` so one stuck event
cannot stall a batch — unfinished futures are cancelled.

### Citable evidence was being truncated away

`graph_expander` collected claims with `LIMIT 50 ORDER BY r.confidence DESC`.
Deterministic `MODIFIES` edges carry confidence 1.0, so thousands of them
crowded out the `INTRODUCES` edges that actually carry excerpts. Ordering now
puts excerpt-bearing relationships first, then confidence.

### Citations were attributed to the wrong node

Two-hop expansion appended *neighbours'* claims to the retrieved node's claim
list, so `pr:922` could cite `issue:20`'s evidence. The formatter now keeps only
claims incident to the retrieved node. Separately, artifacts with no excerpt at
all (commits, PRs, issues) were uncitable; they may now cite themselves by their
own title or message.

### The gold set itself was weak

Auto-generated questions leaked their answers verbatim from the node title, the
structural questions were generic ("Which issue did this change close?") with no
referent, and there were too few unanswerable items. `build_gold_v3.py` rewrites
generation: excerpt-grounded prompts that forbid reusing title wording, a
token-overlap check that rejects leaky questions, deterministic templates that
name a concrete artifact, grouped co-valid answers where several PRs close one
issue, and hand-written near-domain unanswerables.

---

## Round 2 — defects the clean rerun exposed

### Thinking tokens starved the parser

`gemini-2.5-flash` is a thinking model and `max_output_tokens` was 300. Thinking
consumed the entire budget before any text was emitted, so `resp.text` came back
empty, JSON parsing failed, and the parser fell back to keywords again — the same
silent degradation as Round 1, from a different cause. It was also why the run
crawled at 2.7 min/item.

Fixed with `thinking_budget=0` (correct for structured extraction), a 512-token
ceiling, and an explicit raise carrying `finish_reason` instead of dying on
`None.strip()`. Parser failures went 11 → 0, intent became deterministic across
repeated identical questions, and query latency dropped to ~1.7s.

### There was no way to say "what is true now"

The intent taxonomy had no current-state value, so "How are column options
specified **now**?" classified as `what_changed` — which the ranker treats as a
history intent and therefore *stops filtering superseded decisions*. Every
current-slice question was being scored with supersession switched off.

Fixed by adding a `current_state` intent, which routes through the ranker's
existing non-history path, so no ranker logic changed.

### Supersession was inert

All 880 `DesignDecision` nodes had `is_current = NULL` despite 131 `SUPERSEDES`
edges — the backfill had never been run against the rebuilt graph. The reported
"0 superseded citations" was therefore vacuous: nothing *could* be flagged.
After backfilling, 853 current / 27 superseded, and the check is real.

### A named entity lost to lexical noise

The largest single win. For "Which pull request closed issue #64?" the parser
correctly extracted `issue:64` and recall found it, but it never reached the top
8 — beaten by a dependabot PR titled "Bump tiangolo/issue-**manager**".

Two causes. A directly matched entity earned only a 1.5× multiplier inside a
product of eight factors. Worse, `kw_score` multiplied the whole score, so the
*correct* answer scored near zero: a PR's title shares no vocabulary with a
question asking which PR closed an issue. For a graph retriever that premise is
backwards — the edge is the evidence, not the wording.

Fixed in three parts: 1-hop neighbours of a named entity now enter the candidate
pool (the question names the issue but wants the PR), named entities are pinned
above keyword guesses and exempt from the relevance cutoff, and adjacency to a
named entity substitutes for lexical overlap. Structural hit@8 went 0.30 → 1.00,
overall hit@8 0.625 → 0.800.

### The API hung outright

Mid-run, 34 requests timed out and then the server stopped responding entirely —
200s with zero bytes at 0.1% CPU. A thread dump showed the main thread blocked in
`wait_woken` on an open connection to Google.

`GEMINI_REQUEST_TIMEOUT_S` had only ever been applied to `gemini_pool.py`; the
retrieval path built its own `genai.Client` instances with **no timeout**. And
both `parse_question` and `generate_answer` were `async def` wrapping synchronous
SDK calls, so a single stalled request blocked the event loop for every other
request.

Fixed by routing both through the shared pooled client and moving the blocking
calls off the loop with `asyncio.to_thread`. `/ask` became a stable 12s, and four
concurrent requests now finish in 14s rather than the ~48s that serialisation
would cost.

### The scorer punished correct behaviour

`_is_refusal` returned `False` for any answer containing a citation, and on
unanswerable items `invented = bool(cited) or bool(invented_markers)`. So a
citation to a **real retrieved node** counted as a fabricated source ID. The
system's best unanswerable behaviour — denying the fact while pointing at the
near miss, "there is no mention of a query result cache; the evidence covers SQL
compilation caching [1]" — scored as two separate failures.

Fixed by separating two distinct ideas. *Invented* now means a marker that
resolves to no retrieved source, which is fabrication. A refusal may cite real
evidence, but an answer that **asserts** a fact still fails, which is the failure
the metric exists to catch.

Because this changed a scorer after results were visible, it was verified rather
than trusted: all 12 unanswerable answers were read manually (every one an
unambiguous denial), a fabricated `[7]` against a one-source list still flags,
an assertive answer with a citation still fails, and both runs were re-scored
with the same corrected scorer for comparison. Under it, refusal accuracy was
1.000 in *both* runs — so that apparent regression was never a model change.

---

## What was rejected

**Cluster-aware scoring**, which was built and then dropped on evidence. Titles
clustered at 0.6 similarity grouped genuinely distinct decisions — "drop Python
3.6 support" with "add Python 3.13 support" — so treating cluster members as
interchangeable would have inflated the result. And zero gold keys fall into any
cluster, so it is numerically identical to strict scoring here. Strict is reported.

**Near-duplicate credit on the `current` slice.** The two decisions involved were
inspected directly and describe different scopes (one piecemeal re-export, one
comprehensive), so the misses are real. That slice stays at 0.075 cite-precision
and 0.40 hit@8 in the published numbers.

---

## Guardrails left behind

34 tests, covering the defects above so they cannot return silently:

- model availability probed at startup, and asserted in tests
- ranker invariants: no Lucene score in the confidence slot, long bodies damped,
  future timestamps neutral, named entities pinned and cutoff-exempt, anchor
  neighbours not zeroed by absent keyword overlap
- repo scoping on the raw event log
- validator rejects claims with no evidence excerpt
- scorer semantics: unresolvable markers are invention, grounded refusals are not,
  assertive answers are still failures

Provenance for the run is frozen in `manifest.json`: git revision, corpus
SHA-256, last processed index, node and relationship counts, and model versions.
