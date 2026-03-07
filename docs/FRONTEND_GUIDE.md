# Frontend Guide — Features & API Integration

This document describes the frontend views, feature lists, and how each feature integrates with the Retrieval API. Use it to implement the UI without making backend changes.

**Base URL:** `http://localhost:8000` (or your deployed API origin). All endpoints are under `/api/`.

---

## Feature ↔ Endpoint Map

| # | Feature | Primary endpoint(s) | Secondary / navigation |
|---|---------|---------------------|------------------------|
| 1 | Graph Explorer | `GET /api/graph/overview`, `GET /api/graph/neighborhood/{key}` | `GET /api/entity/{key}` (on node click) |
| 2 | Search + Evidence-Grounded Results | `GET /api/query` | `GET /api/entity/{key}` (on result click), graph neighborhood (View in graph) |
| 3 | Entity Detail Panel | `GET /api/entity/{key}` | — |
| 4 | Evidence Panel | (data from query results + entity detail) | — |
| 5 | Decision Timeline | `GET /api/decisions` | `GET /api/entity/{key}` (on card click) |
| 6 | Contributor View | `GET /api/contributors` | `GET /api/entity/{key}` (on person click) |
| 7 | Dashboard / Stats | `GET /api/stats` | — |

---

## Feature List & Endpoint Integration

### 1. Graph Explorer

**Purpose:** Interactive graph of entities and relationships.

**Feature list:**
- Nodes by type: Commit, PullRequest, Issue, Discussion, DesignDecision, Component, Person, FileNode, Tag (color/shape by type).
- Node size by connection count (`degree` from API).
- Edges labeled with relationship type; opacity by confidence.
- Superseded/historical edges visually distinct from current.
- **Click node** → open Entity Detail (call `GET /api/entity/{natural_key}`).
- **Hover node** → highlight its direct connections.
- **Hover edge** → tooltip: evidence excerpt, confidence, source.
- **Double-click node** → reload graph centered on that node (neighborhood).
- **Filters:** node types, min confidence, time range, relationship type.

**Endpoints:**

| Action | Method | Path | Query params | Use response |
|--------|--------|------|--------------|--------------|
| Initial / landing graph | GET | `/api/graph/overview` | `max_nodes` (default 100) | `nodes`, `edges`, `metadata` for rendering |
| Graph centered on node | GET | `/api/graph/neighborhood/{natural_key}` | `depth` (1–3), `max_nodes` (default 50) | Same schema as overview |
| Open entity on click | GET | `/api/entity/{natural_key}` | — | See “Entity Detail Panel” |

**Response shape (graph):**
```json
{
  "nodes": [
    { "id": "natural_key", "label": "PullRequest|Component|...", "title": "...", "degree": 12 }
  ],
  "edges": [
    { "source": "id", "target": "id", "type": "INTRODUCES", "confidence": 0.85, "event_time": "...", "evidence_excerpt": "..." }
  ],
  "metadata": { "total_nodes": 100, "total_edges": 180, "sampled": true }
}
```

---

### 2. Search + Evidence-Grounded Results

**Purpose:** Natural language search with ranked, evidence-backed results.

**Feature list:**
- Search bar: submit query string to `/api/query`.
- Each result shows:
  - **Claim:** subject → predicate → object; confidence badge (e.g. green >0.8, yellow 0.6–0.8, red 0.4–0.6).
  - **Evidence excerpt:** blockquote from source.
  - **Source citation:** link to GitHub (use `evidence.source_url` and label e.g. “PR #42 by jxnl, 2024-01-15”).
  - **Linked entities:** clickable chips; navigate to entity or center graph.
- If present: “Supersedes: [older decision]” from `result.supersedes`.
- Click result → navigate to Entity Detail for `subject_entity.natural_key` (or chosen entity).
- “View in graph” → open Graph Explorer with neighborhood of that node (`/api/graph/neighborhood/{natural_key}`).

**Endpoint:**

| Action | Method | Path | Query params | Use response |
|--------|--------|------|--------------|--------------|
| Run search | GET | `/api/query` | `q` (required), `limit` (default 10), `min_confidence` (default 0.4) | `question`, `intent`, `results`, `conflicts`, `metadata` |

**Response shape:**
```json
{
  "question": "Why did we switch to Pydantic V2?",
  "intent": "decision",
  "results": [
    {
      "rank": 1,
      "score": 0.92,
      "claim": { "subject_key", "predicate", "object_key", "confidence", "event_time" },
      "subject_entity": { "type", "natural_key", "title", "url" },
      "evidence": { "excerpt", "source_key", "source_url", "timestamp" },
      "linked_entities": [{ "natural_key", "type", "display_name" }],
      "supersedes": { "natural_key", "title", "evidence_excerpt", "source_url" } | null
    }
  ],
  "conflicts": [...],
  "metadata": { "candidates_found", "returned", "processing_ms" }
}
```

---

### 3. Entity Detail Panel

**Purpose:** Full view of one entity: properties, claims, and chains (supersession/rename).

**Feature list:**
- **Header:** type badge, title/name, `natural_key`.
- **Properties:** table from `entity.properties`.
- **Claims timeline:** list from `claims` (incoming + outgoing); each: predicate, other entity (clickable → `/api/entity/{other_entity.natural_key}`), evidence excerpt (expandable), confidence, timestamp.
- **Person:** show contribution stats if available (from claims or separate UI).
- **DesignDecision:** supersession chain from `supersession_chain`; status badge; linked components.
- **FileNode:** rename chain from `rename_chain`.
- **Component:** files (BELONGS_TO) and decisions (DECISION_FOR) from claims.
- Optional: primary link from `entity.url` (e.g. GitHub).

**Endpoint:**

| Action | Method | Path | Query params | Use response |
|--------|--------|------|--------------|--------------|
| Load entity | GET | `/api/entity/{natural_key}` | — | `entity`, `claims`, `supersession_chain`, `rename_chain` |

**Path:** `natural_key` is path segment (e.g. `pr:42`, `person:jxnl`, `decision:pydantic-v2-migration`). Support keys that contain slashes (e.g. `file:src/foo.py`) via path encoding.

**Response shape:**
```json
{
  "entity": {
    "type": "DesignDecision",
    "natural_key": "decision:pydantic-v2-migration",
    "properties": { "title", "status", "evidence_excerpt", "evidence_source", "created_at", ... },
    "url": "https://github.com/567-labs/instructor/pull/312"
  },
  "claims": [
    {
      "direction": "incoming|outgoing",
      "predicate": "INTRODUCES",
      "other_entity": { "natural_key", "type", "title" },
      "evidence_excerpt": "...",
      "confidence": 0.85,
      "event_time": "...",
      "source_url": "https://..."
    }
  ],
  "supersession_chain": [ { "natural_key", "title", "status", "event_time" } ] | null,
  "rename_chain": [ { "natural_key", "path" } ] | null
}
```

---

### 4. Evidence Panel

**Purpose:** Expandable evidence view for a single claim/source.

**Feature list:**
- Exact excerpt in a blockquote (`evidence.excerpt` or claim `evidence_excerpt`).
- Source metadata: event type (infer from `natural_key` prefix), `natural_key`, author if available, timestamp.
- Confidence with label (e.g. 1.0 = structured, 0.8 = explicit text, 0.6 = implied, 0.4 = inferred).
- Link to GitHub (from `source_url` or entity `url`).
- Optional: “Related claims” from same source (same `evidence_source` / `source_key`).

**Data source:** No dedicated endpoint. Use:
- Search: `results[].evidence` and `results[].claim`.
- Entity: `claims[].evidence_excerpt`, `claims[].source_url`, `claims[].confidence`, `entity.url`.

---

### 5. Decision Timeline

**Purpose:** Chronological list of design decisions with filters.

**Feature list:**
- Vertical timeline of decision cards: title, status badge (accepted / superseded / proposed), evidence excerpt, source link, component tags.
- Draw SUPERSEDES as arrows between cards (use `supersedes` / `superseded_by`).
- Filters: component (`component`), status (`status`), time range (filter client-side or extend API later).
- Pagination: `limit`, `offset`.
- Click card → Entity Detail for that decision (`/api/entity/{natural_key}`).

**Endpoint:**

| Action | Method | Path | Query params | Use response |
|--------|--------|------|--------------|--------------|
| List decisions | GET | `/api/decisions` | `component`, `status`, `limit`, `offset` | `decisions`, `total`, `limit`, `offset` |

**Response shape:**
```json
{
  "decisions": [
    {
      "natural_key": "decision:pydantic-v2-migration",
      "title": "Migrate validation to Pydantic V2",
      "status": "accepted",
      "event_time": "2024-06-15T10:23:00Z",
      "evidence_excerpt": "...",
      "source_key": "pr:312",
      "source_url": "https://github.com/567-labs/instructor/pull/312",
      "components": ["component:validation"],
      "supersedes": "decision:pydantic-v1-validators",
      "superseded_by": null
    }
  ],
  "total": 199,
  "limit": 50,
  "offset": 0
}
```

---

### 6. Contributor View

**Purpose:** Who contributed and what decisions they introduced.

**Feature list:**
- Ranked list by contribution count (`stats.total_contributions`).
- Per person: display_name, aliases, contribution breakdown (commits, PRs, reviews, issues).
- Decisions they introduced: list with links to Entity Detail.
- Optional: simple activity-over-time (e.g. from claims’ `event_time` if you aggregate).

**Endpoint:**

| Action | Method | Path | Query params | Use response |
|--------|--------|------|--------------|--------------|
| List contributors | GET | `/api/contributors` | `limit` (default 20) | `contributors` |

**Response shape:**
```json
{
  "contributors": [
    {
      "natural_key": "person:jxnl",
      "display_name": "Jason",
      "aliases": ["jxnl", "jxnl@users.noreply.github.com"],
      "url": "https://github.com/jxnl",
      "stats": {
        "total_contributions": 862,
        "commits": 750,
        "prs_authored": 95,
        "reviews_given": 12,
        "issues_opened": 5
      },
      "decisions_introduced": [
        { "natural_key": "decision:pydantic-v2-migration", "title": "Migrate to Pydantic V2" }
      ]
    }
  ]
}
```

---

### 7. Dashboard / Stats

**Purpose:** High-level stats of the knowledge graph and pipeline.

**Feature list:**
- Node count cards by label (`nodes`).
- Relationship count cards by type (`relationships`).
- Processing progress: checkpoint index, total events, percent complete (`processing`).
- Top 5 most-connected nodes (`top_connected`).
- Top 5 most-modified files (`top_modified_files`).
- Optional: links from top nodes to Entity Detail or Graph neighborhood.

**Endpoint:**

| Action | Method | Path | Query params | Use response |
|--------|--------|------|--------------|--------------|
| Load stats | GET | `/api/stats` | — | `nodes`, `relationships`, `processing`, `top_connected`, `top_modified_files` |

**Response shape:**
```json
{
  "nodes": { "Commit": 1168, "FileNode": 374, "DesignDecision": 199, ... },
  "relationships": { "MODIFIES": 3537, "AUTHORED_BY": 1504, ... },
  "processing": {
    "checkpoint_index": 1473,
    "total_events": 8449,
    "percent_complete": 17.4
  },
  "top_connected": [
    { "natural_key": "person:jxnl", "type": "Person", "degree": 862 }
  ],
  "top_modified_files": [
    { "path": "instructor/patch.py", "commit_count": 45 }
  ]
}
```

---

## Quick Reference: All Endpoints

| Method | Path | Params | Purpose |
|--------|------|--------|---------|
| GET | `/api/query` | `q`, `limit`, `min_confidence` | Natural language search, evidence-grounded results |
| GET | `/api/entity/{natural_key}` | — | Full entity detail, claims, supersession/rename chains |
| GET | `/api/graph/overview` | `max_nodes` | Sampled graph for landing/overview |
| GET | `/api/graph/neighborhood/{natural_key}` | `depth`, `max_nodes` | Graph around one node |
| GET | `/api/decisions` | `component`, `status`, `limit`, `offset` | Paginated decisions with filters |
| GET | `/api/contributors` | `limit` | Ranked contributors and decisions introduced |
| GET | `/api/stats` | — | Dashboard: node/rel counts, progress, top nodes/files |

---

## Navigation Patterns

- **Search result → Entity:** `window.location` or router to `/entity/{subject_entity.natural_key}` (or entity detail route), load via `GET /api/entity/{natural_key}`.
- **Search result → Graph:** Open Graph Explorer and call `GET /api/graph/neighborhood/{subject_entity.natural_key}` to center on that node.
- **Graph node click → Entity:** `GET /api/entity/{node.id}` and show Entity Detail panel or page.
- **Graph double-click → Recenter:** Replace current graph data with `GET /api/graph/neighborhood/{node.id}`.
- **Decision/contributor card → Entity:** Same as above using card’s `natural_key`.

Use `natural_key` consistently for all entity links and API path/query parameters. Encode for URLs when the key contains special characters (e.g. `:`, `/`).

---

## Frontend implementation status (graph-spy-lens)

Comparison of the **graph-spy-lens** app against this guide. Use this to see what’s done and what’s left.

### Implemented

| Feature | Status | Notes |
|--------|--------|--------|
| **Dashboard / Stats** | Done | Node/rel counts, processing progress, top connected, top modified files. Uses `GET /api/stats`. |
| **Search + results** | Done | Query input, min-confidence slider, results with subject_entity, evidence, linked entities, supersedes, “View in graph”. Handles null `claim` and null/partial `evidence`. Uses `GET /api/query`. |
| **Entity Detail** | Done | Header (type, title, natural_key, GitHub link), properties table, supersession chain, rename chain, claims timeline with expandable EvidencePanel. Uses `GET /api/entity/{key}`. |
| **Graph Explorer** | Done | Overview + neighborhood via `?center=`, node type toggles, min-confidence filter, node color by type, node size by degree, click → entity, double-click → recenter. Uses overview + neighborhood + entity endpoints. |
| **Decision Timeline** | Done | Filters (status, component), pagination, cards with title, status, date, evidence, components, supersedes/superseded_by. Uses `GET /api/decisions`. |
| **Contributor View** | Done | Ranked table with stats (commits, PRs, reviews, issues), expandable row with aliases and decisions_introduced. Uses `GET /api/contributors`. |
| **Evidence Panel** | Done | Excerpt (blockquote), confidence badge + label, source key, timestamp, GitHub link. Used in Search, Entity, Decisions. Accepts optional/null excerpt. |
| **Navigation** | Done | Sidebar: Dashboard, Search, Graph, Decisions, Contributors. Entity chips link to `/entity/{key}`. “View in graph” uses `/graph?center={key}`. |
| **API client** | Done | `api.ts` with types and helpers for all seven endpoints; `encodeKey()` for natural_key in paths. |

### Remaining / optional

| Item | Guide reference | Priority |
|------|-----------------|----------|
| **Edge hover tooltip** | Graph: “Hover edge → tooltip: evidence excerpt, confidence, source” | Optional | 
| **SUPERSEDES arrows in Decision Timeline** | “Draw SUPERSEDES as arrows between cards” | Optional (currently text only) |
| **Dashboard links from top nodes** | “Optional: links from top nodes to Entity Detail or Graph” | Optional |
| **Person contribution stats on Entity Detail** | “Person nodes: contribution stats (commits, PRs, reviews)” | Optional (would need extra fetch or backend field) |
| **Time range filter** | Graph: “time range”; Decisions: “by time range” | Optional (client-side or API extension) |
| **Relationship type filter (graph)** | “relationship type filter” | Optional |

### API contract notes

- **Search results:** `claim` and `evidence` can be null when the result is node-only (e.g. DesignDecision with node-level evidence). The UI should render subject_entity and evidence when present and skip claim line when `claim` is null.
- **Conflicts:** Response shape is `{ subject_key, predicate, conflicting_objects, claims }`, not a full SearchResult. Render subject_key, predicate, and conflicting_objects.
- **Entity path:** Use `encodeURIComponent(natural_key)` for `/entity/...` when natural_key contains `:` or `/`.
