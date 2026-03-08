# LayerTen — Grounded Long-Term Memory for GitHub Repositories

**Live app:** [**https://layerten.sahilpatel.wiki**](https://layerten.sahilpatel.wiki) · More details: [**https://layerten.sahilpatel.wiki/design**](https://layerten.sahilpatel.wiki/design)

This codebase turns a GitHub repository’s scattered knowledge — commits, PRs, issues, discussions, reviews — into a **grounded, temporal memory graph** in Neo4j. Every fact is tied to evidence, decisions are tracked over time, and the graph supports querying, retrieval, and visualization. The pipeline is: **fetch** (GitHub API + clone) → **merge** (deduplicate and canonicalize) → **sort** (timeline) → **process** (extract into Neo4j). The API (FastAPI) and frontend (graph-spy-lens) let you search, ask questions, and explore the graph.

---

## Quick start

The pipeline has four stages: **fetch** → **merge** → **sort** → **process**.

**Fetch, merge, and sort are already done for this repo.** The outputs are in the `data/` folder (raw events, unified events, timeline). You do **not** need to run fetch, merge, or sort to use the app or to inspect the existing data.

To **replicate and populate your own knowledge graph** (e.g. with your own Neo4j), you only need to run **processing**, which reads from `data/unified/timeline.jsonl` and writes into Neo4j. You still need the merged/sorted data: either use the existing `data/` in the repo, or run fetch → merge → sort once for your chosen repo (see [Full pipeline](#full-pipeline) below).

**Minimal steps to run the app with the existing data:**

1. **Neo4j** — Run a Neo4j instance (e.g. AuraDB or Docker) and set its URL and credentials in `.env`.
2. **Process** — Build the graph from the existing timeline:
   ```bash
   pip install -r requirements.txt
   python -m layerten.process --reset
   ```
3. **API** — Start the backend:
   ```bash
   python -m layerten.api
   ```
4. **Frontend** — From `graph-spy-lens/` run `npm install` and `npm run dev`, or use Docker (see below).

---

## API and frontend

- **Backend:** FastAPI app in `layerten/api/` — query, ask, entities, graph, decisions, contributors, stats. Run with `python -m layerten.api` (default port 8000).
- **Frontend:** `graph-spy-lens` (Vite + React) — dashboard, search, ask, graph explorer, decisions, contributors, system design. It talks to the API via `VITE_API_BASE` (default `http://localhost:8000`).

**Live deployment:** The frontend is at **https://layerten.sahilpatel.wiki**. More details (ontology, dedup, retrieval, adaptation) are on the **System Design** page: **https://layerten.sahilpatel.wiki/design**.

---

## Running with Docker

You can run both the API and the frontend with Docker.

**Backend (API):**

```bash
docker build -f Dockerfile.backend -t layerten-api .
docker run -p 8000:8000 --env-file .env layerten-api
```

**Frontend (graph-spy-lens):**

```bash
cd graph-spy-lens
docker build --build-arg VITE_API_BASE=https://layertenbackend.sahilpatel.wiki -t layerten-frontend .
docker run -p 8080:80 layerten-frontend
```

**Environment variables (example `.env` for backend):**

```env
# Neo4j (required for API and process)
NEO4J_URI=neo4j+s://xxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j

# Optional: for Ask answer generation (Gemini)
GEMINI_API_KEY=your-gemini-api-key

# Optional: for fetch (only if you run fetch/merge/sort)
GITHUB_TOKEN=ghp_xxxx
```

Use your own API URL for `VITE_API_BASE` when building the frontend image if it will talk to a different backend.

---

## Full pipeline (fetch → merge → sort → process)

If you want to run the full pipeline from a GitHub repo (e.g. a different repo or a fresh run):

```bash
# 1. Fetch (clone + GitHub API) → data/raw_events/events.jsonl
python -m layerten.fetch.bootstrap

# 2. Merge (dedupe, canonicalize) → data/unified/events.jsonl, persons, branches, etc.
python -m layerten.merge

# 3. Sort (timeline) → data/unified/timeline.jsonl
python -m layerten.sort

# 4. Process (Neo4j) — requires NEO4J_* in .env
python -m layerten.process --reset
```

Then start the API and frontend as in [Quick start](#quick-start) and [API and frontend](#api-and-frontend).

---

## More documentation

- **Frontend features and API integration:** [docs/FRONTEND_GUIDE.md](docs/FRONTEND_GUIDE.md)
