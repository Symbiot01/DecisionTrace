#!/usr/bin/env python3
"""Run gold items against /api/ask and /api/query (3 reps each).

Persists raw responses under evals/runs/<ts>/raw/<id>.<rep>.json
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def _get(client: httpx.Client, path: str, params: dict) -> dict:
    r = client.get(path, params=params)
    r.raise_for_status()
    return r.json()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=PROJECT_ROOT / "evals" / "gold.jsonl")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--min-confidence", type=float, default=0.4)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--sleep", type=float, default=0.15)
    parser.add_argument(
        "--ids",
        default="",
        help="Comma-separated gold ids to run (default: all)",
    )
    args = parser.parse_args()

    gold = [json.loads(l) for l in args.gold.read_text().splitlines() if l.strip()]
    if args.ids.strip():
        want = {x.strip() for x in args.ids.split(",") if x.strip()}
        gold = [g for g in gold if g["id"] in want]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = PROJECT_ROOT / "evals" / "runs" / ts
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "reps": args.reps,
        "limit": args.limit,
        "min_confidence": args.min_confidence,
        "gold_path": str(args.gold),
        "n_items": len(gold),
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    index: list[dict] = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        # Health check
        try:
            client.get("/api/stats").raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.error("API not reachable at %s: %s", args.base_url, exc)
            return 1

        for i, item in enumerate(gold):
            gid = item["id"]
            logger.info("[%d/%d] %s", i + 1, len(gold), gid)
            for rep in range(args.reps):
                params = {
                    "q": item["question"],
                    "limit": args.limit,
                    "min_confidence": args.min_confidence,
                }
                t0 = time.time()
                ask = None
                query = None
                error = None
                try:
                    ask = _get(client, "/api/ask", params)
                    query = _get(client, "/api/query", params)
                except Exception as exc:  # noqa: BLE001
                    error = f"{type(exc).__name__}: {exc}"
                    logger.warning("Request failed for %s rep=%d: %s", gid, rep, error)
                elapsed_ms = int((time.time() - t0) * 1000)
                payload = {
                    "gold": item,
                    "rep": rep,
                    "elapsed_ms": elapsed_ms,
                    "error": error,
                    "ask": ask,
                    "query": query,
                    "request": {
                        "path_ask": "/api/ask",
                        "path_query": "/api/query",
                        "params": params,
                    },
                }
                out_path = raw_dir / f"{gid}.{rep}.json"
                out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
                index.append(
                    {
                        "id": gid,
                        "rep": rep,
                        "path": str(out_path.relative_to(PROJECT_ROOT)),
                        "error": error,
                        "elapsed_ms": elapsed_ms,
                    }
                )
                time.sleep(args.sleep)

    (run_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    meta["finished_at"] = datetime.now(timezone.utc).isoformat()
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(str(run_dir))
    logger.info("Done. Run dir: %s", run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
