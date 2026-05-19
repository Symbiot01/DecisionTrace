"""Cluster near-duplicate DesignDecision nodes.

The extraction pass runs per-artifact, so the same architectural decision is
recorded many times from different commits/PRs with slightly different titles.
For retrieval that is harmless, but for scoring it means a citation can be
factually right and still miss the single gold key. This builds an explicit
equivalence map so cite-precision can be reported both strictly (exact node)
and cluster-aware (any node recording the same decision).

Usage:
    python evals/cluster_decisions.py --threshold 0.6 [--inspect]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from layerten import config  # noqa: E402
from layerten.process.neo4j_client import Neo4jClient  # noqa: E402

OUT_PATH = Path(__file__).parent / "decision_clusters.json"

_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "into", "when",
    "were", "have", "been", "will", "should", "would", "than", "then",
    "using", "used", "use", "via", "was", "are", "not", "but", "its",
    "decision", "change", "changed", "added", "add", "update", "updated",
}


def tokens(text: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9_]+", (text or "").lower())
    return frozenset(w for w in words if len(w) > 3 and w not in _STOP)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


class UnionFind:
    def __init__(self, keys: list[str]) -> None:
        self.parent = {k: k for k in keys}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--inspect", action="store_true", help="print threshold sweep and samples")
    ap.add_argument("--out", default=str(OUT_PATH))
    args = ap.parse_args()
    out_path = Path(args.out)

    db = Neo4jClient(
        config.NEO4J_URI, config.NEO4J_USERNAME, config.NEO4J_PASSWORD, config.NEO4J_DATABASE
    )
    rows = db.read_query(
        """
        MATCH (d:DesignDecision)
        RETURN d.natural_key AS nk, d.title AS title, d.description AS description
        """
    )
    db.close()

    nodes = [r for r in rows if r.get("nk")]
    print(f"decisions: {len(nodes)}")

    tok = {r["nk"]: tokens(f"{r.get('title') or ''} {r.get('description') or ''}") for r in nodes}
    titles = {r["nk"]: (r.get("title") or "") for r in nodes}

    # Blocking: only compare decisions sharing at least one token, so we avoid
    # the full O(n^2) sweep and never merge on stopword-only overlap.
    inverted: dict[str, list[str]] = defaultdict(list)
    for nk, ts in tok.items():
        for t in ts:
            inverted[t].append(nk)

    pairs: set[tuple[str, str]] = set()
    for t, keys in inverted.items():
        if len(keys) > 200:  # too common to be discriminative
            continue
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = sorted((keys[i], keys[j]))
                pairs.add((a, b))

    sims = {(a, b): jaccard(tok[a], tok[b]) for a, b in pairs}

    if args.inspect:
        print("\nthreshold sweep:")
        for th in (0.5, 0.6, 0.7, 0.8, 0.9):
            uf = UnionFind(list(tok))
            for (a, b), s in sims.items():
                if s >= th:
                    uf.union(a, b)
            groups = defaultdict(list)
            for nk in tok:
                groups[uf.find(nk)].append(nk)
            sizes = sorted((len(v) for v in groups.values()), reverse=True)
            multi = [s for s in sizes if s > 1]
            print(
                f"  th={th}: clusters={len(groups)} multi={len(multi)} "
                f"largest={sizes[0]} clustered_nodes={sum(multi)}"
            )

    uf = UnionFind(list(tok))
    for (a, b), s in sims.items():
        if s >= args.threshold:
            uf.union(a, b)

    groups: dict[str, list[str]] = defaultdict(list)
    for nk in tok:
        groups[uf.find(nk)].append(nk)

    clusters = {root: sorted(members) for root, members in groups.items() if len(members) > 1}
    key_to_cluster = {nk: root for root, members in clusters.items() for nk in members}

    if args.inspect:
        print(f"\nsample clusters at th={args.threshold}:")
        for root, members in sorted(clusters.items(), key=lambda x: -len(x[1]))[:6]:
            print(f"  [{len(members)}] {root[:60]}")
            for m in members[:4]:
                print(f"       - {titles[m][:80]}")

    payload = {
        "threshold": args.threshold,
        "total_decisions": len(nodes),
        "clusters": clusters,
        "key_to_cluster": key_to_cluster,
        "clustered_nodes": len(key_to_cluster),
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(
        f"\nwrote {out_path}: {len(clusters)} multi-node clusters covering "
        f"{len(key_to_cluster)}/{len(nodes)} decisions"
    )


if __name__ == "__main__":
    main()
