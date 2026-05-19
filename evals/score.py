#!/usr/bin/env python3
"""Score a run directory against gold (rule-based only).

Emits metrics.json and report.md in the run directory.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CITE_RE = re.compile(r"\[(\d+)\]")


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    low = (centre - margin) / denom
    high = (centre + margin) / denom
    return (max(0.0, low), min(1.0, high))


def _retrieved_pack(sources: list[dict]) -> set[str]:
    keys: set[str] = set()
    for s in sources or []:
        ev = s.get("evidence") or {}
        if ev.get("source_key"):
            keys.add(ev["source_key"])
        se = s.get("subject_entity") or {}
        if se.get("natural_key"):
            keys.add(se["natural_key"])
    return keys


def _cited_keys(answer: str, sources: list[dict]) -> tuple[list[str], list[int]]:
    """Return cited source_keys (best-effort) and any invented marker numbers."""
    if not answer:
        return [], []
    markers = [int(m) for m in CITE_RE.findall(answer)]
    cited: list[str] = []
    invented_markers: list[int] = []
    for n in markers:
        idx = n - 1
        if idx < 0 or idx >= len(sources or []):
            invented_markers.append(n)
            continue
        src = sources[idx]
        ev = src.get("evidence") or {}
        key = ev.get("source_key") or (src.get("subject_entity") or {}).get("natural_key")
        if key:
            cited.append(key)
        else:
            invented_markers.append(n)
    return cited, invented_markers


_DENIAL_CUES = (
    "no relevant evidence",
    "does not directly",
    "not found",
    "no evidence",
    "cannot answer",
    "don't have",
    "do not have",
    "not in the knowledge graph",
    "no information",
    "no mention",
    "does not indicate",
    "does not mention",
    "not mentioned",
)


def _is_refusal(answer: str, cited: list[str]) -> bool:
    """A refusal denies that the requested fact is present in the evidence.

    Citing real sources does not disqualify it. Explaining the near miss --
    "there is no mention of a query cache; the evidence covers SQL compilation
    caching [1]" -- is a grounded refusal, and treating it as an answer scored
    the system's best unanswerable behaviour as a failure.
    """
    text = (answer or "").lower()
    if any(c in text for c in _DENIAL_CUES):
        return True
    return not CITE_RE.search(answer or "")


def score_rep(gold: dict, ask: dict | None, error: str | None) -> dict:
    if error or ask is None:
        return {
            "ok": False,
            "error": error or "missing ask payload",
            "cite_precision": None,
            "hit_at_8": False,
            "invented": True,
            "superseded_hit": False,
            "refused": False,
            "cited_keys": [],
            "retrieved_pack": [],
        }

    answer = ask.get("answer") or ""
    sources = ask.get("sources") or []
    pack = _retrieved_pack(sources)
    cited, invented_markers = _cited_keys(answer, sources)
    gold_keys = set(gold.get("gold_source_keys") or []) | set(gold.get("gold_entity_keys") or [])
    forbidden = set(gold.get("forbidden_keys") or [])
    must_refuse = bool(gold.get("must_refuse"))

    hit = bool(gold_keys & pack) if gold_keys else False

    if must_refuse:
        # "Invented" means a marker that resolves to no retrieved source, i.e.
        # fabricated provenance. A marker pointing at a real node is grounded
        # even on an unanswerable question, so citing one is not invention.
        invented = bool(invented_markers)
        cite_precision = None
        refused = _is_refusal(answer, cited) and not invented_markers
        superseded_hit = False
    else:
        invented = bool(invented_markers)
        if cited:
            good = sum(1 for k in cited if k in gold_keys)
            cite_precision = good / len(cited)
        else:
            # No citations on an answerable item: precision undefined; count as 0 for aggregate
            cite_precision = 0.0
            invented = invented  # markers only
        refused = False
        superseded_hit = bool(set(cited) & forbidden)

    return {
        "ok": True,
        "error": None,
        "cite_precision": cite_precision,
        "hit_at_8": hit,
        "invented": invented,
        "superseded_hit": superseded_hit,
        "refused": refused,
        "cited_keys": cited,
        "retrieved_pack": sorted(pack),
        "invented_markers": invented_markers,
        "answer_preview": answer[:240],
    }


def median_or_none(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    return float(statistics.median(vals))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_dir",
        type=Path,
        nargs="?",
        help="evals/runs/<ts> directory (default: latest)",
    )
    parser.add_argument(
        "--span",
        type=Path,
        default=PROJECT_ROOT / "evals" / "span_alignment.json",
    )
    args = parser.parse_args()

    if args.run_dir is None:
        runs = sorted((PROJECT_ROOT / "evals" / "runs").glob("*"))
        if not runs:
            raise SystemExit("No runs found under evals/runs/")
        args.run_dir = runs[-1]

    run_dir = args.run_dir
    raw_dir = run_dir / "raw"
    files = sorted(raw_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No raw files in {raw_dir}")

    by_id: dict[str, list[dict]] = defaultdict(list)
    gold_by_id: dict[str, dict] = {}
    for path in files:
        payload = json.loads(path.read_text())
        gold = payload["gold"]
        gid = gold["id"]
        gold_by_id[gid] = gold
        scored = score_rep(gold, payload.get("ask"), payload.get("error"))
        scored["rep"] = payload.get("rep")
        scored["path"] = str(path)
        by_id[gid].append(scored)

    # Per-item median across reps
    items = []
    for gid, reps in sorted(by_id.items()):
        gold = gold_by_id[gid]
        cps = [r["cite_precision"] for r in reps if r["cite_precision"] is not None]
        item = {
            "id": gid,
            "slice": gold["slice"],
            "must_refuse": gold.get("must_refuse", False),
            "cite_precision_median": median_or_none(cps),
            "hit_at_8": statistics.median([1.0 if r["hit_at_8"] else 0.0 for r in reps]) >= 0.5,
            "invented_any": any(r["invented"] for r in reps),
            "invented_majority": sum(1 for r in reps if r["invented"]) > len(reps) / 2,
            "superseded_any": any(r["superseded_hit"] for r in reps),
            "refused_majority": sum(1 for r in reps if r["refused"]) > len(reps) / 2,
            "disagreement": {
                "cite_precision_range": (
                    (max(cps) - min(cps)) if len(cps) >= 2 else 0.0
                ),
                "hit_flip": len({r["hit_at_8"] for r in reps}) > 1,
                "invented_flip": len({r["invented"] for r in reps}) > 1,
            },
            "reps": reps,
        }
        items.append(item)

    # Aggregates
    def slice_items(name: str | None = None, answerable_only: bool = False):
        out = items
        if name:
            out = [i for i in out if i["slice"] == name]
        if answerable_only:
            out = [i for i in out if not i["must_refuse"]]
        return out

    fact_current = [i for i in items if i["slice"] in ("fact", "current")]
    cite_vals = [i["cite_precision_median"] for i in fact_current if i["cite_precision_median"] is not None]
    cite_mean = statistics.mean(cite_vals) if cite_vals else 0.0
    # Treat cite-precision as micro over items using median; also count "perfect" items
    cite_successes = sum(1 for v in cite_vals if v >= 1.0)
    invented_answerable = [i for i in items if not i["must_refuse"]]
    invented_count = sum(1 for i in invented_answerable if i["invented_majority"])
    invented_refuse = sum(1 for i in items if i["must_refuse"] and i["invented_majority"])
    invented_total = invented_count + invented_refuse
    superseded = [i for i in items if i["slice"] == "current"]
    superseded_hits = sum(1 for i in superseded if i["superseded_any"])
    unans = [i for i in items if i["must_refuse"]]
    refuse_ok = sum(1 for i in unans if i["refused_majority"] and not i["invented_majority"])
    hit_items = [i for i in items if not i["must_refuse"]]
    hit_ok = sum(1 for i in hit_items if i["hit_at_8"])

    span = None
    if args.span.exists():
        span = json.loads(args.span.read_text())

    metrics = {
        "run_dir": str(run_dir),
        "n_items": len(items),
        "cite_precision": {
            "slice": "fact+current",
            "n": len(cite_vals),
            "mean_of_medians": round(cite_mean, 4),
            "perfect_rate": round(cite_successes / len(cite_vals), 4) if cite_vals else 0.0,
            "wilson_95_perfect": [
                round(x, 4) for x in _wilson_interval(cite_successes, len(cite_vals) or 1)
            ],
            "X_for_cv": round(100.0 * cite_mean, 1),
        },
        "hit_at_8": {
            "n": len(hit_items),
            "rate": round(hit_ok / len(hit_items), 4) if hit_items else 0.0,
        },
        "invented_source_ids": {
            "n": len(items),
            "count": invented_total,
            "rate": round(invented_total / len(items), 4) if items else 0.0,
            "target": 0,
        },
        "superseded_citations": {
            "n": len(superseded),
            "count": superseded_hits,
            "rate": round(superseded_hits / len(superseded), 4) if superseded else 0.0,
            "target": 0,
        },
        "refusal_accuracy": {
            "n": len(unans),
            "correct": refuse_ok,
            "rate": round(refuse_ok / len(unans), 4) if unans else 0.0,
        },
        "span_alignment": {
            "n": (span or {}).get("n"),
            "rate": (span or {}).get("alignment_rate"),
            "aligned": (span or {}).get("aligned"),
        },
        "by_slice": {},
        "items": items,
    }

    for slice_name in sorted({i["slice"] for i in items}):
        subset = slice_items(slice_name)
        cps = [i["cite_precision_median"] for i in subset if i["cite_precision_median"] is not None]
        metrics["by_slice"][slice_name] = {
            "n": len(subset),
            "cite_precision_mean": round(statistics.mean(cps), 4) if cps else None,
            "hit_at_8": round(
                sum(1 for i in subset if i["hit_at_8"]) / len(subset), 4
            )
            if subset
            else 0.0,
            "invented": sum(1 for i in subset if i["invented_majority"]),
            "superseded": sum(1 for i in subset if i["superseded_any"]),
        }

    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n")

    lines = [
        f"# Eval report: `{run_dir.name}`",
        "",
        f"- Items: **{metrics['n_items']}**",
        f"- Cite-precision (fact+current, mean of per-item medians): "
        f"**{metrics['cite_precision']['mean_of_medians']:.3f}** "
        f"(n={metrics['cite_precision']['n']}) → CV X ≈ "
        f"**{metrics['cite_precision']['X_for_cv']}%**",
        f"- Invented source ids: **{metrics['invented_source_ids']['count']}** / "
        f"{metrics['invented_source_ids']['n']} (target 0)",
        f"- Superseded citations: **{metrics['superseded_citations']['count']}** / "
        f"{metrics['superseded_citations']['n']} (target 0)",
        f"- Refusal accuracy: **{metrics['refusal_accuracy']['rate']:.3f}** "
        f"(n={metrics['refusal_accuracy']['n']})",
        f"- Hit@8 (answerable): **{metrics['hit_at_8']['rate']:.3f}** "
        f"(n={metrics['hit_at_8']['n']})",
        f"- Span alignment (extraction): **{(metrics['span_alignment']['rate'] or 0):.3f}** "
        f"(n={metrics['span_alignment']['n']})",
        "",
        "## By slice",
        "",
    ]
    for name, row in metrics["by_slice"].items():
        lines.append(
            f"- **{name}** (n={row['n']}): cite={row['cite_precision_mean']}, "
            f"hit@8={row['hit_at_8']}, invented={row['invented']}, "
            f"superseded={row['superseded']}"
        )
    lines.extend(["", "## Failures (diagnostic)", ""])
    for i in items:
        flags = []
        if i["must_refuse"] and (i["invented_majority"] or not i["refused_majority"]):
            flags.append("refusal_fail")
        if not i["must_refuse"] and not i["hit_at_8"]:
            flags.append("retrieval_miss")
        if i["superseded_any"]:
            flags.append("superseded_cite")
        if i["invented_majority"] and not i["must_refuse"]:
            flags.append("invented")
        if flags:
            lines.append(f"- `{i['id']}` [{i['slice']}]: {', '.join(flags)}")
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")

    print(json.dumps({k: metrics[k] for k in metrics if k != "items"}, indent=2))
    print(f"\nWrote {run_dir / 'metrics.json'}")
    print(f"Wrote {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
