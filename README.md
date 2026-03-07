# LayerTen — Grounded Long-Term Memory for GitHub Repositories

A system that turns a GitHub repository's scattered knowledge — commits, PRs, issues, discussions, reviews — into a grounded, temporal memory graph. Every fact is backed by evidence, every decision is tracked through its lifecycle, and nothing is ever silently lost.

**Corpus**: GitHub repository (code + social layer via API)
**Graph store**: Neo4j AuraDB
**Extraction model**: Llama 3 8B via Ollama (free, local) / Groq free tier (hosted fallback)

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Ontology & Schema](#ontology--schema)
3. [Neo4j Graph Model](#neo4j-graph-model)
4. [Ingestion Pipeline](#ingestion-pipeline)
5. [Structured Extraction](#structured-extraction)
6. [Deduplication & Canonicalization](#deduplication--canonicalization)
7. [Lifecycle & Tombstoning](#lifecycle--tombstoning)
8. [Retrieval & Grounding](#retrieval--grounding)
9. [Visualization Layer](#visualization-layer)
10. [Observability](#observability)
11. [Layer10 Adaptation](#layer10-adaptation)
12. [Reproduction Instructions](#reproduction-instructions)

**For the Layer10 take-home submission:** See **[docs/LAYER10_TAKEHOME_WRITEUP.md](docs/LAYER10_TAKEHOME_WRITEUP.md)** for the formal write-up that maps to the task PDF (corpus, extraction, deduplication, memory graph, retrieval, visualization, Layer10 adaptation) and answers how we tackle deduplication, conflicts, reversibility, and grounding.

---

## Architecture Overview

```
GitHub API / Webhooks
        │
        ▼
┌───────────────────┐
│  Raw Event Log    │  ← append-only, immutable source of truth
│  (Postgres/file)  │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Extraction       │  ← deterministic + LLM-based (Llama 3 / Groq)
│  Pipeline         │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Dedup &          │  ← entity resolution, claim merging, conflict detection
│  Canonicalization │
└───────┬───────────┘
        │
        ▼
┌───────────────────┐
│  Neo4j AuraDB     │  ← memory graph (entities + claims + evidence)
│  Graph Store      │
└───────┬───────────┘
        │
        ├──► Retrieval API (FastAPI)
        └──► Visualization UI (web)
```

The system has three interleaved layers of truth:
- **Code layer**: files, commits, diffs, branches
- **Social layer**: PRs, issues, discussions, reviews, comments
- **Decision layer**: design decisions inferred from both, linked to components they affect

---

## Ontology & Schema

### Entity Types

```
Entity
├── Repository          root node, anchors everything
├── Person              contributor / reviewer / commenter (with aliases)
├── FileNode            path + blob SHA, versioned per commit
├── Component           logical grouping of files (inferred or explicit)
├── Commit              SHA, message, parent SHAs, diff summary
├── Branch              name, fork point, head, status, merge target
├── PullRequest         number, title, body, state, base/head branch
├── Issue               number, title, body, state, labels
├── Discussion          GitHub Discussions thread
├── Review              PR review (approved / changes requested / commented)
├── Label               bug, enhancement, breaking-change, etc.
└── DesignDecision      extracted from discussions, PR bodies, ADRs
```

### Relationship / Claim Types

Every edge carries evidence. These are the predicates:

| Predicate | Subject | Object | Notes |
|---|---|---|---|
| `MODIFIES` | Commit / PR | FileNode | diff as evidence |
| `CLOSES` | PR / Commit | Issue | |
| `REFERENCES` | any | any | cross-links |
| `AUTHORED_BY` | any | Person | |
| `REVIEWED_BY` | PR | Person | |
| `ASSIGNED_TO` | Issue / PR | Person | temporal — ownership changes |
| `INTRODUCES` | Commit / PR | DesignDecision | new pattern, new abstraction |
| `REVERTS` | Commit / PR | Commit / PR | |
| `DEPRECATES` | Commit / PR | FileNode | |
| `DEPENDS_ON` | FileNode | FileNode | import analysis |
| `BELONGS_TO` | FileNode | Component | |
| `DECISION_FOR` | DesignDecision | Component / Issue / PR | |
| `SUPERSEDES` | DesignDecision | DesignDecision | critical for reversals |
| `RENAMES` | FileNode | FileNode | old → new, linked by commit |
| `MERGED_INTO` | Component / Branch | Component / Branch | |
| `CHERRY_PICKED_FROM` | Commit | Commit | |
| `REBASE_OF` | Commit | Commit | |
| `ON_BRANCH` | Commit | Branch | reachability |
| `STATE_CHANGED_TO` | any | (literal) | lifecycle transitions |

### Core Data Structures

```python
@dataclass
class Entity:
    id: str                     # canonical UUID
    type: EntityType
    natural_key: str            # e.g. "PR#42", "commit:abc123", "file:src/core/auth.py"
    display_name: str
    aliases: list[str]          # e.g. ["johndoe", "John Doe", "jdoe@company.com"]
    metadata: dict
    status: str                 # "active", "deleted", "renamed", "merged_into", etc.
    extraction_version: str     # hash(prompt + model + schema_version)
    created_at: datetime
    updated_at: datetime

@dataclass
class Claim:
    id: str
    subject_id: str
    predicate: PredicateType
    object_id: str              # entity id or literal string
    object_literal: str | None

    # Temporal validity
    event_time_from: datetime   # when this became true in repo history
    event_time_until: datetime | None  # None = still current
    processing_time: datetime   # when the pipeline learned about it

    confidence: float           # 0.0–1.0
    is_current: bool
    superseded_by: str | None

    # Branch scope
    scope_type: str             # "all_branches", "specific_branches", "main_only"
    scope_branch_ids: list[str]
    introduced_at_commit: str

    evidence: list[EvidencePointer]
    extraction_version: str

@dataclass
class EvidencePointer:
    source_id: str              # "PR#42", "commit:abc123", "issue#17"
    source_type: SourceType
    excerpt: str                # exact text snippet from source
    url: str                    # permalink to GitHub
    char_offset_start: int
    char_offset_end: int
    timestamp: datetime
    author_id: str

@dataclass
class DesignDecision:
    id: str
    title: str
    summary: str                # LLM-extracted 1–2 sentence summary
    status: str                 # "proposed", "accepted", "rejected", "superseded"
    rationale: str
    alternatives_considered: list[str]
    affects_components: list[str]
    source_branch_id: str | None
    evidence: list[EvidencePointer]
    event_time_from: datetime
    event_time_until: datetime | None
    superseded_by: str | None

@dataclass
class Branch:
    id: str
    repo_id: str
    name: str
    base_commit_sha: str
    head_commit_sha: str
    forked_from_branch_id: str | None
    forked_at_commit_sha: str | None
    status: str                 # "active", "merged", "deleted", "stale"
    merged_into_branch_id: str | None
    merged_at: datetime | None
    created_at: datetime
    deleted_at: datetime | None
```

---

## Neo4j Graph Model

All entities are nodes. All claims are relationships with properties. Evidence is stored as nested maps on relationships or as linked `Evidence` nodes for complex cases.

### Node Labels & Properties

```cypher
// Repository
CREATE (r:Repository {
  id: $id,
  natural_key: $natural_key,
  name: $name,
  url: $url,
  created_at: datetime()
})

// Person (with aliases stored as list)
CREATE (p:Person {
  id: $id,
  natural_key: $username,
  display_name: $display_name,
  aliases: $aliases,           // ["john@co.com", "John Smith"]
  extraction_version: $version,
  created_at: datetime()
})

// FileNode (versioned by blob SHA)
CREATE (f:FileNode {
  id: $id,
  natural_key: $path,
  path: $path,
  blob_sha: $blob_sha,
  language: $language,
  status: "active",            // "active" | "deleted" | "renamed"
  renamed_from_id: null,
  extraction_version: $version,
  created_at: datetime()
})

// Component (inferred logical grouping)
CREATE (c:Component {
  id: $id,
  natural_key: $name,
  display_name: $name,
  status: "active",            // "active" | "deprecated" | "merged_into" | "split_into" | "deleted"
  successor_ids: [],
  predecessor_ids: [],
  extraction_version: $version,
  created_at: datetime()
})

// Commit
CREATE (cm:Commit {
  id: $id,
  natural_key: $sha,
  sha: $sha,
  message: $message,
  parent_shas: $parent_shas,
  diff_summary: $diff_summary,
  committed_at: datetime($timestamp),
  extraction_version: $version
})

// Branch
CREATE (b:Branch {
  id: $id,
  natural_key: $name,
  name: $name,
  base_commit_sha: $base_sha,
  head_commit_sha: $head_sha,
  status: "active",
  merged_into_branch_id: null,
  merged_at: null,
  created_at: datetime(),
  deleted_at: null
})

// PullRequest
CREATE (pr:PullRequest {
  id: $id,
  natural_key: $number,
  number: $number,
  title: $title,
  body: $body,
  state: $state,
  base_branch: $base,
  head_branch: $head,
  merged_at: $merged_at,
  extraction_version: $version,
  created_at: datetime()
})

// Issue
CREATE (i:Issue {
  id: $id,
  natural_key: $number,
  number: $number,
  title: $title,
  body: $body,
  state: $state,
  labels: $labels,
  extraction_version: $version,
  created_at: datetime()
})

// DesignDecision (first-class node)
CREATE (dd:DesignDecision {
  id: $id,
  title: $title,
  summary: $summary,
  status: "proposed",          // "proposed" | "accepted" | "rejected" | "superseded"
  rationale: $rationale,
  alternatives_considered: $alternatives,
  source_branch_id: $branch_id,
  event_time_from: datetime($from),
  event_time_until: null,
  superseded_by: null,
  extraction_version: $version
})

// Evidence (linked node for rich provenance)
CREATE (ev:Evidence {
  id: $id,
  source_id: $source_id,
  source_type: $source_type,
  excerpt: $excerpt,
  url: $url,
  char_start: $start,
  char_end: $end,
  event_timestamp: datetime($ts),
  author_id: $author_id
})

// RawEvent (immutable log)
CREATE (re:RawEvent {
  id: $id,
  source: "github_api",
  event_type: $event_type,
  payload: $payload_json,
  fetched_at: datetime(),
  api_version: $api_version
})
```

### Relationship Types with Temporal & Branch Properties

Every claim-relationship carries temporal validity, branch scope, confidence, and links to evidence.

```cypher
// Claim as a relationship with full metadata
MATCH (s:Commit {id: $subject_id}), (o:FileNode {id: $object_id})
CREATE (s)-[r:MODIFIES {
  claim_id: $claim_id,
  event_time_from: datetime($from),
  event_time_until: null,
  processing_time: datetime(),
  confidence: $confidence,
  is_current: true,
  superseded_by: null,
  scope_type: $scope_type,
  scope_branch_ids: $branch_ids,
  introduced_at_commit: $commit_sha,
  extraction_version: $version
}]->(o)

// Link evidence to the relationship via an intermediate Evidence node
MATCH (s)-[r:MODIFIES {claim_id: $claim_id}]->(o)
CREATE (ev:Evidence {
  id: $ev_id,
  source_id: $source_id,
  source_type: "commit_diff",
  excerpt: $excerpt,
  url: $url,
  char_start: $start,
  char_end: $end,
  event_timestamp: datetime($ts),
  author_id: $author_id
})
CREATE (ev)-[:SUPPORTS {claim_id: $claim_id}]->(s)
```

### Key Indexes

```cypher
CREATE INDEX entity_natural_key FOR (n:Entity) ON (n.natural_key);
CREATE INDEX commit_sha FOR (n:Commit) ON (n.sha);
CREATE INDEX file_path FOR (n:FileNode) ON (n.path);
CREATE INDEX pr_number FOR (n:PullRequest) ON (n.number);
CREATE INDEX issue_number FOR (n:Issue) ON (n.number);
CREATE INDEX person_key FOR (n:Person) ON (n.natural_key);
CREATE INDEX branch_name FOR (n:Branch) ON (n.name);
CREATE INDEX evidence_source FOR (n:Evidence) ON (n.source_id);
CREATE INDEX decision_status FOR (n:DesignDecision) ON (n.status);

// Full-text index for retrieval
CREATE FULLTEXT INDEX entity_search FOR (n:Person|Component|FileNode|PullRequest|Issue|DesignDecision)
ON EACH [n.display_name, n.title, n.summary, n.path, n.body];
```

---

## Ingestion Pipeline

### Phase 0 — Raw Event Log (Append-Only)

Before any extraction, every API response is written verbatim to an immutable event log. This is the source of truth for reprocessing when the schema changes.

```python
@dataclass
class RawEvent:
    id: str                     # UUID
    source: str                 # "github_api"
    event_type: str             # "pr.opened", "commit.pushed", "issue.closed", ...
    payload: dict               # full API response JSON
    fetched_at: datetime
    api_version: str
```

Schema changes trigger re-extraction from this log — not from the GitHub API again.

### Phase 1 — Bootstrap (Historical Ingest)

```
1. Fetch all commits        (git log + GitHub API)
2. Fetch all PRs             (open + closed + merged, with reviews + comments)
3. Fetch all Issues          (with timeline events for state transitions)
4. Fetch all Discussions     (threaded comments)
5. Fetch all Reviews per PR
6. Fetch file tree at tagged versions (or sampled commits)
7. Write everything to RawEvent log
```

Uses GitHub's GraphQL API to batch-fetch PRs with reviews and comments in a single query, minimizing API calls.

### Phase 2 — Extraction

Split into deterministic (no LLM) and semantic (LLM) paths. See [Structured Extraction](#structured-extraction).

### Phase 3 — Dedup & Canonicalization

See [Deduplication & Canonicalization](#deduplication--canonicalization).

### Phase 4 — Graph Write

Upsert entities and claims into Neo4j using `MERGE` on `natural_key` for idempotency.

```cypher
MERGE (p:Person {natural_key: $username})
ON CREATE SET p.id = $id, p.display_name = $name, p.aliases = $aliases,
              p.created_at = datetime(), p.extraction_version = $version
ON MATCH SET  p.aliases = apoc.coll.union(p.aliases, $aliases),
              p.updated_at = datetime()
```

### Phase 5 — Incremental Updates (Webhook-Driven)

```
GitHub Webhook → Event Queue → Processor

For each new event:
1. Write to RawEvent log (idempotent by event_id)
2. Determine affected entities by natural_key
3. Re-extract only the changed artifact
4. Run dedup against existing claims:
   - New claim conflicts with current → set old event_time_until = now, insert new
   - New claim confirms existing     → add evidence pointer, bump confidence
   - New claim is net-new            → insert with evidence
5. Update is_current flags
6. Invalidate cached summaries for affected components
```

Idempotency: every upsert uses `MERGE` on `natural_key`. Every claim merge is logged to a `ClaimMergeAudit` node.

---

## Structured Extraction

### Deterministic Extraction (No LLM)

Reliable structured data extracted directly from API responses:

- Commit SHA, message, author, timestamp, parent SHAs
- PR number, title, state, base/head branches, merge commit
- Issue number, labels, state transitions (from timeline events)
- File paths changed per commit (from diff)
- Cross-references (GitHub auto-links: `closes #42`, `fixes #17`)
- Review state (approved / changes_requested)
- Branch creation, deletion, merge events

### Semantic Extraction (LLM)

Uses Llama 3 8B (via Ollama locally) or Groq free tier as fallback:

- Extract `DesignDecision` from PR body / discussion threads
- Classify PRs: bug fix | feature | refactor | breaking change | revert
- Extract rationale and alternatives considered from PR descriptions
- Infer Component boundaries from file clustering + PR descriptions
- Detect decision reversals ("we decided X" → later "reverting X because Y")

### Extraction Prompt Contract

```python
EXTRACTION_PROMPT = """
You are extracting structured memory from a GitHub artifact.

Artifact type: {artifact_type}
Content: {content}

Extract:
1. DESIGN DECISIONS: choices made, alternatives rejected, rationale given
2. ENTITY REFERENCES: people, files, components, issues mentioned
3. CLAIMS: facts asserted (ownership, status changes, deprecations)
4. TEMPORAL SIGNALS: "we previously did X", "this replaces Y", "going forward Z"

Return ONLY valid JSON matching this schema: {schema}

For every claim, you MUST include the exact excerpt from the text that supports it.
If you cannot find supporting text, omit the claim.
Confidence: 0.0-1.0 based on how explicitly the claim is stated.
"""
```

### Validation & Repair Loop

```python
def extract_with_repair(artifact, schema, max_retries=3):
    for attempt in range(max_retries):
        raw = call_llm(EXTRACTION_PROMPT.format(...))
        try:
            parsed = schema.parse(raw)
            validated = cross_check_evidence(parsed, artifact)
            if validated.min_confidence > 0.4:
                return validated
        except ValidationError as e:
            raw = call_llm(REPAIR_PROMPT.format(error=e, previous=raw))

    return fallback_deterministic_extraction(artifact)
```

- Pydantic validation ensures structural correctness
- `cross_check_evidence` verifies that cited excerpts actually exist in the source text
- Fallback to deterministic extraction — never lose an artifact

### Extraction Versioning

Every entity and claim is tagged with `extraction_version = hash(prompt_template + model_id + schema_version)`. When any component changes, selectively reprocess only artifacts whose extraction version is stale — without re-fetching from GitHub.

### Quality Gates

| Condition | Destination |
|---|---|
| confidence > 0.8 + single source | Staging (review queue) |
| confidence > 0.8 + multiple sources | Durable memory |
| confidence > 0.6 + cross-evidence | Durable with lower weight |
| Below thresholds | Ephemeral / discarded |

---

## Deduplication & Canonicalization

### Artifact Dedup

| Artifact | Dedup Key | Near-Duplicate |
|---|---|---|
| Commits | SHA (canonical, idempotent) | — |
| PRs / Issues | GitHub number | — |
| Discussion comments | GitHub `node_id` | MinHash on body text |
| Review comments | GitHub `node_id` | MinHash on body text |

### Entity Canonicalization

**Person resolution:**

```
Primary key:    GitHub username
Aliases:        email from commits, display name, co-author trailers
Resolution:     build alias graph, pick username as canonical
Storage:        entity.aliases = ["john@co.com", "John Smith", "jsmith"]
```

**File rename tracking:**

```
Method:         git log --follow to trace renames across history
Model:          old FileNode → RENAMES → new FileNode, linked by commit evidence
Query:          follow RENAMES chain backwards for full file history
```

**Component inference:**

```
Signals:        directory structure, co-modification frequency, PR descriptions
Validation:     human-reviewable before becoming canonical
```

### Claim Dedup

```python
def merge_claims(existing: Claim, new: Claim) -> Claim:
    if claims_are_equivalent(existing, new):
        # Same subject + predicate + object → accumulate evidence
        merged = existing.copy()
        merged.evidence.extend(new.evidence)
        merged.confidence = max(existing.confidence, new.confidence)
        return merged

    if claims_conflict(existing, new):
        # Conflicting claims at different times → temporal supersession
        existing.event_time_until = new.event_time_from
        existing.is_current = False
        existing.superseded_by = new.id
        return new
```

### Conflict Detection

When two claims assert contradictory facts (e.g., two different owners for the same file at the same time), a `ClaimConflict` node is created:

```cypher
CREATE (cc:ClaimConflict {
  id: $id,
  claim_a_id: $claim_a,
  claim_b_id: $claim_b,
  conflict_type: "contradictory_ownership",
  detected_at: datetime(),
  resolution: null,             // "a_wins" | "b_wins" | "both_valid" | "needs_review"
  resolved_at: null
})
```

### Reversibility

Two audit node types log every merge decision with enough context to undo it:

```cypher
// Claim merge audit
CREATE (cma:ClaimMergeAudit {
  id: $id,
  surviving_claim_id: $survivor,
  merged_claim_id: $merged,
  merge_reason: $reason,
  pre_merge_snapshot: $snapshot_json,
  merged_at: datetime(),
  merged_by: "pipeline_v2"
})

// Entity merge audit
CREATE (ema:EntityMergeAudit {
  id: $id,
  surviving_entity_id: $survivor,
  merged_entity_id: $merged,
  merge_reason: $reason,
  alias_mappings: $mappings_json,
  pre_merge_snapshot: $snapshot_json,
  merged_at: datetime(),
  merged_by: "pipeline_v2"
})
```

---

## Lifecycle & Tombstoning

**Core rule: nothing gets hard deleted.** Every deletion in GitHub is recorded as a state transition. The entity stays in the graph. What changes is its `status` and the `is_current` flag on its claims.

### Unified Entity State Machine

```
          created
             │
             ▼
          [active] ◄──────────────────────┐
             │                            │
    ┌────────┼────────┬──────────┐        │ (reopened)
    ▼        ▼        ▼          ▼        │
 renamed  merged   split      deleted ────┘
    │     _into    _into        (entity stays in graph,
    │        │        │          claims marked non-current)
    ▼        ▼        ▼
successor  absorber  children
```

### Branch Lifecycle

When a branch is deleted (typically after merge):

```python
# 1. Update branch entity
branch.status = "merged"  # or "deleted"
branch.deleted_at = event_time
branch.head_commit_sha = last_known_sha  # freeze at last known state

# 2. Terminate branch-scoped claims
# SET event_time_until, is_current = false for claims scoped only to this branch

# 3. For merged branches: promote claims to target branch
# Claims whose commits are reachable from main post-merge get main added to scope
```

Closed-without-merge PRs and deleted branches keep all their `DesignDecision` nodes with status `"rejected"` or `"abandoned"`. This institutional memory — the roads not taken — is among the highest-value data the system captures.

### FileNode Lifecycle

- **Deleted**: `STATE_CHANGED_TO "deleted"` claim with commit evidence. Entity stays.
- **Renamed**: old FileNode gets `RENAMES → new FileNode` relationship. Query layer follows the chain for full history.
- **Re-created**: new FileNode (different blob SHA) linked to old by `REFERENCES` if content is similar; otherwise they are independent entities sharing a path.

### Component Lifecycle

Statuses: `active`, `deprecated`, `merged_into`, `split_into`, `deleted`, `renamed`. Each transition creates claims and updates `successor_ids` / `predecessor_ids` for navigation. Design decisions that referenced old components stay intact and are reachable via forwarding claims.

### Cherry-Picks, Rebases, Force Pushes

| Scenario | Handling |
|---|---|
| Cherry-pick | `CHERRY_PICKED_FROM` claim linking commits. Evidence shared. |
| Rebase | Match by (author, message, diff fingerprint). `REBASE_OF` claim. Old SHAs become aliases. |
| Force push | Old commits marked `status: "rewritten"`. `FORCE_PUSH` event on branch. Evidence pointers get `source_commit_status: "rewritten"`. Claims grounded in those commits stay intact. |

---

## Retrieval & Grounding

### Retrieval API

A FastAPI service that takes a natural language question and returns a **context pack**: ranked evidence snippets with linked entities and claims.

```
GET /query?q=Why did we switch from REST to GraphQL?&branch=main&limit=10
```

**Response: Context Pack**

```json
{
  "question": "Why did we switch from REST to GraphQL?",
  "results": [
    {
      "rank": 1,
      "claim": {
        "subject": "Component:api-layer",
        "predicate": "INTRODUCES",
        "object": "DesignDecision:graphql-migration",
        "confidence": 0.92,
        "is_current": true
      },
      "decision": {
        "title": "Migrate API layer from REST to GraphQL",
        "summary": "Adopted GraphQL to reduce over-fetching and enable frontend teams to self-serve queries.",
        "status": "accepted",
        "rationale": "REST endpoints required backend changes for every new frontend need...",
        "alternatives_considered": ["Keep REST + add BFF layer", "gRPC for internal services"]
      },
      "evidence": [
        {
          "source": "PR#287",
          "excerpt": "This PR introduces GraphQL as our primary API layer. REST was causing...",
          "url": "https://github.com/org/repo/pull/287",
          "timestamp": "2025-08-14T10:23:00Z",
          "author": "janedoe"
        },
        {
          "source": "Discussion#45",
          "excerpt": "After evaluating gRPC and BFF patterns, we decided GraphQL gives us...",
          "url": "https://github.com/org/repo/discussions/45",
          "timestamp": "2025-08-10T15:00:00Z",
          "author": "johndoe"
        }
      ],
      "linked_entities": ["Person:janedoe", "Person:johndoe", "Component:api-layer"]
    }
  ],
  "metadata": {
    "branch": "main",
    "as_of": "2026-03-07T00:00:00Z",
    "total_candidates": 47,
    "pruned_to": 10
  }
}
```

### Query Pipeline

```
Question
   │
   ▼
┌──────────────────────┐
│ 1. Question Analysis │  Parse intent: entity lookup, history, decision, comparison
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 2. Candidate Recall  │  Hybrid: full-text (Neo4j FTS) + embedding similarity (vector index)
│                      │  + exact match on natural keys mentioned in question
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 3. Graph Expansion   │  From candidate nodes, traverse 1–2 hops:
│                      │  - claims about the entity
│                      │  - evidence supporting those claims
│                      │  - related design decisions
│                      │  - connected components / people
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 4. Rank & Prune      │  Score by: relevance × confidence × recency × diversity
│                      │  Deduplicate overlapping evidence
│                      │  Cap expansion to prevent combinatorial blowup
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 5. Format & Ground   │  Every returned item includes evidence with source URL
│                      │  Conflicting claims shown side-by-side with timestamps
│                      │  Citations formatted as [source](url)
└──────────────────────┘
```

### Candidate Recall: Hybrid Strategy

```cypher
// Full-text search on entities
CALL db.index.fulltext.queryNodes("entity_search", $question_keywords)
YIELD node, score
WHERE score > 0.3
RETURN node, score
ORDER BY score DESC
LIMIT 50
```

Combined with embedding similarity via Neo4j's vector index (using sentence-transformers embeddings stored on nodes):

```cypher
// Vector similarity search
CALL db.index.vector.queryNodes("entity_embeddings", 20, $question_embedding)
YIELD node, score
RETURN node, score
```

Results from both are merged, deduplicated by entity ID, and ranked by combined score.

### Handling Ambiguity and Conflicts

When multiple claims contradict each other (e.g., two different assertions about ownership at different times):

- **Show both** with clear temporal markers: "As of [date], [claim A]. Previously, [claim B]."
- If a `ClaimConflict` node exists and is unresolved, surface it explicitly: "There is a conflict between [source A] and [source B] — both assert different facts."
- Recency and confidence break ties for ranking, but both sides are always retrievable.

### Branch-Aware Retrieval

```python
def get_current_claims(subject_id: str, predicate: str, branch: str = "main"):
    """Retrieve claims valid on a specific branch."""
    return neo4j.run("""
        MATCH (s {id: $subject_id})-[r]->(o)
        WHERE type(r) = $predicate
          AND r.is_current = true
          AND (r.scope_type = 'all_branches'
               OR $branch IN r.scope_branch_ids)
        RETURN r, o
        ORDER BY r.confidence DESC
    """, subject_id=subject_id, predicate=predicate, branch=branch)
```

---

## Visualization Layer

A web UI for exploring the memory graph, built with a lightweight stack.

**Stack**: FastAPI backend + vanilla JS frontend with D3.js for graph rendering, or Neo4j Browser / Bloom as a rapid alternative.

### Views

#### 1. Graph Explorer

Interactive force-directed graph visualization:

- **Nodes** colored by type (Person = blue, FileNode = green, PR = purple, DesignDecision = gold)
- **Edges** labeled with predicate, styled by `is_current` (solid = current, dashed = historical)
- **Filters**: by entity type, time range, confidence threshold, branch
- Click any node to see its properties and connected claims
- Time slider to see the graph state at any point in history

#### 2. Evidence Panel

When a claim/relationship is selected:

- Exact excerpt from source, highlighted
- Source metadata: type (PR / issue / commit / discussion), author, timestamp
- Direct link to GitHub URL
- Confidence score and extraction version
- Other claims supported by the same evidence

#### 3. Entity Detail View

For any entity (person, file, component, decision):

- Timeline of all claims involving this entity, ordered chronologically
- Status history (active → renamed → merged, etc.)
- Aliases and merge history (with audit trail)
- For files: full rename chain with links to each version
- For decisions: rationale, alternatives, current status, supersession chain

#### 4. Dedup & Merge Inspector

- List of all entity merges with audit entries
- For each merge: pre-merge snapshots of both entities, merge reason, who/what triggered it
- Ability to see which aliases map to which canonical entity
- Claim merge history: which claims were combined, evidence accumulated

#### 5. Decision Timeline

A dedicated view for `DesignDecision` nodes:

- Chronological timeline grouped by component
- Status indicators: proposed → accepted / rejected / superseded
- Click-through to evidence (the PR, discussion, or issue where the decision was made)
- Supersession chains shown as connected nodes

### Implementation Approach

```
/viz
├── index.html          # single-page app shell
├── graph.js            # D3.js force graph rendering
├── evidence.js         # evidence panel rendering
├── timeline.js         # decision timeline view
├── api.js              # fetch wrapper for FastAPI endpoints
└── styles.css

/api
├── main.py             # FastAPI app
├── routes/
│   ├── query.py        # retrieval API
│   ├── entities.py     # entity CRUD + detail views
│   ├── claims.py       # claim listing + filtering
│   ├── evidence.py     # evidence lookup
│   ├── decisions.py    # design decision views
│   └── audit.py        # merge audit inspector
└── neo4j_client.py     # Neo4j driver wrapper
```

---

## Observability

### Metrics to Track

| Metric | What It Measures | Alert Threshold |
|---|---|---|
| `extraction.confidence.p50` / `p95` | Distribution of LLM extraction confidence | p50 < 0.6 |
| `extraction.failure_rate` | % of artifacts where LLM extraction fails all retries | > 5% |
| `extraction.fallback_rate` | % falling back to deterministic-only extraction | > 15% |
| `claims.conflict_rate` | New claims that conflict with existing current claims | > 10% sustained |
| `claims.ungrounded_ratio` | Claims with zero evidence pointers | > 0% (every claim must have evidence) |
| `claims.current_vs_historical` | Ratio of `is_current=true` to total claims | Monitor for drift |
| `dedup.merge_rate` | Entity/claim merges per ingestion batch | Spike = possible bad merge logic |
| `dedup.false_merge_rate` | Merges reversed via audit (manual or automated) | > 1% |
| `evidence.stale_url_rate` | Evidence URLs that return 404 on periodic check | > 5% |
| `pipeline.event_lag` | Time between GitHub event and graph write | > 5 minutes |
| `pipeline.reprocessing_backlog` | Artifacts needing re-extraction due to version change | Monitor during upgrades |
| `graph.node_count` / `edge_count` | Graph size over time | Unexpected jumps |
| `retrieval.latency.p95` | Query response time | > 2s |
| `retrieval.empty_result_rate` | Queries returning zero results | > 20% |

### Implementation

```python
# Lightweight: structured logging + Prometheus counters

from prometheus_client import Counter, Histogram, Gauge

extraction_confidence = Histogram(
    "extraction_confidence", "Confidence scores from LLM extraction",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)
extraction_failures = Counter(
    "extraction_failures_total", "Extraction attempts that exhausted retries"
)
claim_conflicts = Counter(
    "claim_conflicts_total", "New claims conflicting with existing"
)
pipeline_event_lag = Histogram(
    "pipeline_event_lag_seconds", "Lag between GitHub event and graph write"
)
retrieval_latency = Histogram(
    "retrieval_latency_seconds", "Retrieval query latency"
)
```

### Health Check Queries (periodic)

```cypher
// Ungrounded claims (should be zero)
MATCH (s)-[r]->(o)
WHERE NOT EXISTS {
  MATCH (ev:Evidence)-[:SUPPORTS]->(s)
  WHERE ev.claim_id = r.claim_id
}
RETURN count(r) AS ungrounded_claims

// Stale extraction versions
MATCH (n)
WHERE n.extraction_version <> $current_version
RETURN labels(n)[0] AS type, count(n) AS stale_count

// Conflict backlog
MATCH (cc:ClaimConflict)
WHERE cc.resolution IS NULL
RETURN count(cc) AS unresolved_conflicts
```

---

## Layer10 Adaptation

This section explains how the system built for a GitHub corpus adapts to Layer10's target environment: email, Slack/Teams, docs, and Jira/Linear.

### Ontology Changes

| GitHub Concept | Layer10 Equivalent | Adaptation |
|---|---|---|
| Repository | Organization / Workspace | Root anchor becomes multi-workspace |
| PR | Jira ticket, Linear issue | Same lifecycle (open → review → merged/closed) but different field schemas |
| Issue | Jira ticket, support ticket, Linear issue | Map labels → Jira priorities/components |
| Discussion | Slack thread, email chain | Thread structure varies (Slack = flat + threaded, email = reply chains with quoting) |
| Review | Jira comment, Slack reaction, email reply | Less structured — need NLP to detect approval vs. pushback |
| Commit / Diff | Doc edit, Notion page revision | Different granularity — doc edits don't have SHAs |
| Branch | Jira sprint, project phase | Temporal scoping via sprint boundaries instead of git branches |
| FileNode | Document, wiki page, Confluence page | Version history from doc platform API instead of git |
| Component | Jira project, Slack channel, team | More explicit (Jira projects are named) but also fuzzier (Slack channels drift) |

### Extraction Contract Changes

**Email**: Parse MIME structure. Handle forwarding chains (quoted content creates near-duplicates). Extract sender/recipient as Person entities. Threading via `In-Reply-To` / `References` headers. Signature stripping before LLM extraction.

**Slack**: Real-time event stream (Slack Events API) instead of batch fetch. Threads are first-class. Reactions (`+1`, eyes emoji) as lightweight approval signals. Channel membership changes = team composition claims. Edited/deleted messages require tracking `message_changed` / `message_deleted` events — original text preserved in RawEvent log.

**Jira/Linear**: Structured fields (status, assignee, priority, sprint, components) extracted deterministically — almost no LLM needed for field-level data. Rich text in descriptions/comments still needs semantic extraction for decisions. Changelog API provides exact state transitions with timestamps — richer than GitHub timeline events.

**Docs (Notion, Confluence, Google Docs)**: Version history API for temporal tracking. Collaboration/commenting as evidence sources. Structural hierarchy (workspace → page → sub-page) maps to Component containment.

### Dedup Strategy Changes

| Challenge | GitHub Approach | Layer10 Approach |
|---|---|---|
| Content duplication | MinHash on comment bodies | MinHash + quoted-content detection for email; edit-chain dedup for Slack |
| Person resolution | GitHub username as anchor | Cross-platform identity graph: Slack user ID ↔ Jira user ↔ email address ↔ name. Requires fuzzy matching + optional admin-provided mappings. |
| Artifact cross-referencing | GitHub auto-links (`#42`) | Parse Jira ticket keys (`PROJ-123`), Slack message permalinks, doc URLs from all text. Build a cross-platform reference graph. |
| Near-duplicate discussions | Rare in GitHub | Common: same topic discussed in Slack, then summarized in a Jira ticket, then referenced in an email. Dedup by semantic similarity + temporal proximity. |

### Grounding & Safety

- **Provenance**: every claim must trace back to a specific message/ticket/doc revision with a stable permalink.
- **Deletions/Redactions**: when a Slack message is deleted or a doc is redacted, the RawEvent log retains the original for audit, but the Evidence node gets `redacted_at` timestamp and the excerpt is cleared. Claims grounded only in redacted evidence are flagged for review.
- **Citation format**: `[Slack: #engineering, @johndoe, 2025-08-14](permalink)` or `[Jira: PROJ-123, comment by @jane](permalink)`.

### Long-Term Memory Behavior

**What becomes durable memory:**
- Design decisions with explicit rationale (from any source)
- Ownership assignments (ticket assignee, channel topic owner, doc editor)
- Status transitions (ticket state changes, project phase shifts)
- Cross-referenced facts confirmed by multiple sources

**What stays ephemeral:**
- Casual Slack chatter without decision content
- Email small talk / scheduling
- Redundant status updates ("still working on it")
- Low-confidence single-source claims below quality gate thresholds

**Preventing drift:**
- Periodic confidence decay: claims not re-confirmed within a configurable window get `confidence *= decay_factor`
- Stale ownership detection: if a person hasn't touched a component in N months, their `OWNS` claim confidence decays
- Reconciliation jobs: compare graph state against current source-of-truth (Jira current assignee, Slack channel topic) and flag divergence

### Operational Reality

**Scaling**: Neo4j AuraDB handles graph storage and queries. Raw event log in Postgres or S3 for high-volume append. Extraction workers scale horizontally — each artifact is independent.

**Cost**: Llama 3 via Ollama is free for local extraction. Groq free tier for burst capacity. Embedding model (sentence-transformers) runs locally. Neo4j AuraDB free tier for development; paid tier for production scale.

**Incremental updates**: webhook-driven for real-time sources (Slack, GitHub). Polling for batch sources (email via IMAP, Jira changelog). All idempotent via natural keys.

**Evaluation / regression testing**: maintain a golden set of manually verified (entity, claim, evidence) triples. On each pipeline change, run extraction on the golden set and compare output. Alert on precision/recall regression.

---

## Reproduction Instructions

Pipeline order: **Fetch** → **Merge** → **Sort** → **Process** → **API** → **Frontend**. Full write-up aligned to the Layer10 PDF: **docs/LAYER10_TAKEHOME_WRITEUP.md**.

### Prerequisites

- Python 3.11+
- Docker (for Ollama)
- Neo4j AuraDB instance (free tier)
- GitHub personal access token (for API access)

### Setup

```bash
# Clone the repo
git clone <repo-url> && cd layerten

# Install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Start Ollama with Llama 3
docker run -d -p 11434:11434 ollama/ollama
docker exec -it <container> ollama pull llama3:8b

# Configure environment
cp .env.example .env
# Edit .env with:
#   GITHUB_TOKEN=ghp_...
#   NEO4J_URI=neo4j+s://xxx.databases.neo4j.io
#   NEO4J_USER=neo4j
#   NEO4J_PASSWORD=...
#   TARGET_REPO=owner/repo
#   OLLAMA_URL=http://localhost:11434
```

### Run End-to-End

```bash
# 1. Fetch: bootstrap — get all historical data from GitHub (clone + API)
python -m layerten.fetch.bootstrap

# 2. Merge: canonicalize and merge raw events (commits, PRs, issues, persons, etc.)
python -m layerten.merge

# 3. Sort: build timeline (topological commits + chronological others) → data/unified/timeline.jsonl
python -m layerten.sort

# 4. Process: extract into Neo4j (deterministic + optional agentic LLM). Use --reset to wipe and re-run.
python -m layerten.process --reset

# 5. Start the API
python -m layerten.api

# 6. Open the frontend (graph-spy-lens) and point it at http://localhost:8000
# See graph-spy-lens/README.md and docs/FRONTEND_GUIDE.md
```

### Run Incremental Updates

Re-run fetch to pull new data, then merge, sort, and process. Processing is incremental by default (uses `data/process_checkpoint.json`). Use `python -m layerten.process` without `--reset` to resume; use `--reset` to wipe the graph and reprocess from scratch.

### Example Queries

```bash
# Retrieval API (after starting the API with python -m layerten.api)
curl "http://localhost:8000/api/query?q=Why+did+we+refactor+the+auth+module&limit=5"
curl "http://localhost:8000/api/query?q=Who+owns+the+payments+component&limit=5"
curl "http://localhost:8000/api/decisions?limit=20"
```
