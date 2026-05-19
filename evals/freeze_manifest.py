"""Record exactly what the numbers were measured against.

Without this, a metric is unreproducible: the graph can be rebuilt, the gold set
edited, or the corpus boundary moved, and nothing in the report would show it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layerten import config  # noqa: E402
from layerten.process.neo4j_client import Neo4jClient  # noqa: E402


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_rev() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="evals/v3/gold_v3.jsonl")
    ap.add_argument("--out", default="evals/v3/manifest.json")
    args = ap.parse_args()

    db = Neo4jClient(
        config.NEO4J_URI, config.NEO4J_USERNAME, config.NEO4J_PASSWORD, config.NEO4J_DATABASE
    )
    nodes = {
        r["l"]: r["c"]
        for r in db.read_query(
            "MATCH (n) UNWIND labels(n) AS l RETURN l, count(*) AS c ORDER BY c DESC"
        )
    }
    rels = {
        r["t"]: r["c"]
        for r in db.read_query(
            "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC"
        )
    }
    repos = db.read_query("MATCH (r:Repository) RETURN r.natural_key AS nk")
    db.close()

    gold_path = Path(args.gold)
    gold_rows = [json.loads(l) for l in open(gold_path)]
    slices: dict[str, int] = {}
    for r in gold_rows:
        slices[r["slice"]] = slices.get(r["slice"], 0) + 1

    checkpoint = json.loads(Path(config.PROCESS_CHECKPOINT_PATH).read_text())

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": git_rev(),
        "target_repo": config.TARGET_REPO,
        "repository_nodes": [r["nk"] for r in repos],
        "models": {
            "extraction": config.GEMINI_MODEL_EXTRACTION,
            "rag": config.GEMINI_MODEL_RAG,
            "parser": config.GEMINI_MODEL_PARSER,
        },
        "corpus": {
            "timeline_path": str(config.UNIFIED_TIMELINE_PATH),
            "timeline_sha256": sha256(config.UNIFIED_TIMELINE_PATH),
            "raw_events_sha256": sha256(config.RAW_EVENTS_PATH),
            "last_processed_index": checkpoint.get("last_processed_index"),
        },
        "graph": {"nodes": nodes, "relationships": rels},
        "gold": {
            "path": str(gold_path),
            "sha256": sha256(gold_path),
            "n_items": len(gold_rows),
            "slices": slices,
        },
    }

    Path(args.out).write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
