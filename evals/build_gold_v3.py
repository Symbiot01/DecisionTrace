"""Build and adjudicate the v3 gold set.

The first-pass generator produced questions that could not measure retrieval:

  * fact/current questions restated the gold decision's title verbatim, so a
    substring match scored a hit and nothing about ranking was tested;
  * every structural question was the literal string "Which issue or pull
    request was closed by this change?", with no referent for "this change" and
    24 different gold answers;
  * only 3 unanswerable candidates existed, all far outside the domain.

This module generates questions that are answerable from the corpus but do not
contain the answer, validates each one against a title-leak rule, and mixes in
near-domain unanswerables (plausible for an ORM, absent from SQLModel) so the
refusal slice is not trivially easy.

Usage:
    python evals/build_gold_v3.py --candidates evals/v3/candidates.jsonl \
        --out evals/v3/gold_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from layerten import config  # noqa: E402

_STOP = {
    "the", "and", "for", "with", "from", "this", "that", "into", "when", "were",
    "have", "been", "will", "should", "would", "than", "then", "using", "used",
    "use", "via", "was", "are", "not", "but", "its", "how", "what", "why",
    "does", "did", "make", "made", "when", "where", "which", "while",
}

# Plausible for an ORM built on SQLAlchemy + Pydantic, absent from this repo.
# Near-domain refusals are the ones a keyword matcher gets wrong.
NEAR_DOMAIN_UNANSWERABLE = [
    "How does SQLModel implement connection pooling for MongoDB?",
    "Which Cassandra consistency level does SQLModel default to for writes?",
    "How do I configure SQLModel to shard tables across multiple Postgres clusters?",
    "What is SQLModel's built-in caching layer for query results called?",
    "How does SQLModel handle automatic database failover during a write?",
    "Which GraphQL schema generator ships with SQLModel?",
    "How does SQLModel's row-level security policy engine evaluate predicates?",
    "What is the default retry budget for SQLModel's async connection retries?",
    "How does SQLModel compile queries to Apache Arrow record batches?",
]

_FACT_SYSTEM = """You write evaluation questions for a code-knowledge retrieval system.

You are given the EXCERPT describing an engineering decision in a Python ORM
library, plus its TITLE.

Write ONE question that a developer would plausibly ask, which the excerpt
answers.

Hard rules:
- Ask about the technical substance in the EXCERPT (the problem, the behaviour,
  the mechanism). Do NOT ask "why was the decision made to <title>".
- Do NOT reuse the distinctive wording of the TITLE. If the title says
  "Re-initialize SQLAlchemy InstanceState on model_copy", do not use the phrase
  "re-initialize InstanceState"; ask about the observable problem instead.
- Do NOT mention any identifier like pr:123, issue:45, or decision:some-slug.
- One sentence, under 140 characters, phrased naturally.
Return only JSON: {"question": "..."}"""

_CURRENT_SYSTEM = """You write evaluation questions for a code-knowledge retrieval system.

You are given two competing engineering decisions in a Python ORM library: the
CURRENT approach and the SUPERSEDED older approach.

Write ONE question asking what the project does *now* about the shared topic.

Hard rules:
- Identify the shared topic and ask about the present state of it.
- Do NOT reuse the distinctive wording of either title. The question must not
  reveal which approach won.
- Do NOT mention any identifier like pr:123 or decision:some-slug.
- One sentence, under 140 characters, phrased naturally.
Return only JSON: {"question": "..."}"""


def tokens(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9_]+", (text or "").lower())
        if len(w) > 3 and w not in _STOP
    }


def leaks_title(question: str, title: str, threshold: float = 0.6) -> bool:
    """True if the question reuses most of the title's distinctive tokens."""
    t = tokens(title)
    if not t:
        return False
    overlap = len(t & tokens(question)) / len(t)
    return overlap >= threshold


def mentions_key(question: str, keys: list[str]) -> bool:
    q = question.lower()
    for key in keys:
        if key.lower() in q:
            return True
        slug = key.split(":", 1)[-1]
        if len(slug) > 6 and slug.lower() in q:
            return True
    return False


def ask_gemini(client: genai.Client, system: str, payload: dict) -> str | None:
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL_PARSER,
            contents=json.dumps(payload, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=system,
                temperature=0.0,
                max_output_tokens=2048,
                response_mime_type="application/json",
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return None
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        return (json.loads(text).get("question") or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        print(f"  ! gemini failed: {exc}", file=sys.stderr)
        return None


def build_fact(client, rows, want: int) -> list[dict]:
    out = []
    for row in rows:
        if len(out) >= want:
            break
        title = row.get("title") or ""
        excerpt = (row.get("excerpt") or "")[:1500]
        if len(excerpt) < 80:
            continue  # too thin to ask a substantive question about
        q = ask_gemini(
            client, _FACT_SYSTEM, {"TITLE": title, "EXCERPT": excerpt}
        )
        if not q:
            continue
        keys = (row.get("gold_source_keys") or []) + (row.get("gold_entity_keys") or [])
        if leaks_title(q, title) or mentions_key(q, keys):
            print(f"  rejected (leak): {q[:80]}")
            continue
        out.append(
            {
                "slice": "fact",
                "question": q,
                "gold_source_keys": row["gold_source_keys"],
                "gold_entity_keys": row["gold_entity_keys"],
                "forbidden_keys": row.get("forbidden_keys", []),
                "must_refuse": False,
            }
        )
    return out


def build_current(client, rows, want: int) -> list[dict]:
    out = []
    for row in rows:
        if len(out) >= want:
            break
        newer, older = row.get("newer_title") or "", row.get("older_title") or ""
        q = ask_gemini(
            client, _CURRENT_SYSTEM, {"CURRENT": newer, "SUPERSEDED": older}
        )
        if not q:
            continue
        keys = (
            (row.get("gold_source_keys") or [])
            + (row.get("gold_entity_keys") or [])
            + (row.get("forbidden_keys") or [])
        )
        if leaks_title(q, newer) or mentions_key(q, keys):
            print(f"  rejected (leak): {q[:80]}")
            continue
        out.append(
            {
                "slice": "current",
                "question": q,
                "gold_source_keys": row["gold_source_keys"],
                "gold_entity_keys": row["gold_entity_keys"],
                "forbidden_keys": row.get("forbidden_keys", []),
                "must_refuse": False,
            }
        )
    return out


def build_structural(rows, want: int) -> list[dict]:
    """Deterministic: the question must name the artifact it asks about.

    'Which issue or pull request was closed by this change?' had no referent,
    so every structural item was unanswerable as posed.
    """
    # Several artifacts can close the same issue, which produced two items with
    # identical question text and different single-answer gold sets. Group by
    # (noun, object) so one question carries every co-valid answer.
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row.get("kind") != "closes":
            continue
        subject, obj = row.get("subject", ""), row.get("object", "")
        if not subject or not obj or ":" not in obj:
            continue
        noun = {
            "pr": "pull request",
            "discussion": "discussion",
            "commit": "commit",
            "issue": "issue",
        }.get(subject.split(":", 1)[0], "change")
        entry = grouped.setdefault(
            (noun, obj), {"subjects": set(), "obj": obj, "noun": noun}
        )
        entry["subjects"].add(subject)

    out = []
    for (noun, obj), entry in grouped.items():
        if len(out) >= want:
            break
        obj_kind, obj_num = obj.split(":", 1)
        keys = sorted(entry["subjects"]) + [obj]
        out.append(
            {
                "slice": "structural",
                "question": f"Which {noun} closed {obj_kind} #{obj_num}?",
                "gold_source_keys": keys,
                "gold_entity_keys": keys,
                "forbidden_keys": [],
                "must_refuse": False,
            }
        )
    return out


def build_unanswerable(rows, want: int) -> list[dict]:
    out = []
    for row in rows:
        q = row.get("title")
        if q:
            out.append(
                {
                    "slice": "unanswerable",
                    "question": q,
                    "gold_source_keys": [],
                    "gold_entity_keys": [],
                    "forbidden_keys": [],
                    "must_refuse": True,
                }
            )
    for q in NEAR_DOMAIN_UNANSWERABLE:
        out.append(
            {
                "slice": "unanswerable",
                "question": q,
                "gold_source_keys": [],
                "gold_entity_keys": [],
                "forbidden_keys": [],
                "must_refuse": True,
            }
        )
    return out[:want]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", default="evals/v3/candidates.jsonl")
    ap.add_argument("--out", default="evals/v3/gold_v3.jsonl")
    ap.add_argument("--fact", type=int, default=20)
    ap.add_argument("--current", type=int, default=10)
    ap.add_argument("--structural", type=int, default=10)
    ap.add_argument("--unanswerable", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260906)
    args = ap.parse_args()

    rows = [json.loads(l) for l in open(args.candidates)]
    by_slice: dict[str, list[dict]] = {}
    for r in rows:
        by_slice.setdefault(r.get("slice", "?"), []).append(r)

    rng = random.Random(args.seed)
    for v in by_slice.values():
        rng.shuffle(v)

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    print("fact...")
    items = build_fact(client, by_slice.get("fact", []), args.fact)
    print("current...")
    items += build_current(client, by_slice.get("current", []), args.current)
    print("structural...")
    items += build_structural(by_slice.get("structural", []), args.structural)
    print("unanswerable...")
    items += build_unanswerable(by_slice.get("unanswerable", []), args.unanswerable)

    counts: dict[str, int] = {}
    with open(args.out, "w") as f:
        for i, item in enumerate(items, 1):
            item = {"id": f"{item['slice']}-{counts.get(item['slice'], 0) + 1:03d}", **item}
            counts[item["slice"]] = counts.get(item["slice"], 0) + 1
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"\nwrote {args.out}: {counts} (total {sum(counts.values())})")


if __name__ == "__main__":
    main()
