#!/usr/bin/env python3
"""Generate natural-language questions for mined candidates (Gemini, temperature=0).

Hard rule: question must not contain any gold natural_key (unless slice=entity_lookup).
Writes evals/questions_draft.jsonl for human adjudication.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

from layerten import config  # noqa: E402

logger = logging.getLogger(__name__)

_SYSTEM = """You write short natural-language questions for a GitHub repository knowledge-graph eval.

Rules:
- Output ONLY a JSON object: {"question": "..."}
- One clear question, max 22 words.
- Do NOT include any natural_key strings (no "pr:123", "issue:4", "commit:abc", "decision:...", "person:...", "tag:...").
- Do NOT include raw SHA hashes.
- Prefer "why / what / who / which" questions grounded in the title and excerpt.
- For unanswerable / must_refuse items, write a question about the hint_topic as if asking the graph.
- For current/supersedes items, ask what the CURRENT decision or approach is (not the old one).
"""


def _forbidden_substrings(row: dict) -> list[str]:
    keys = []
    for field in ("gold_source_keys", "gold_entity_keys", "forbidden_keys"):
        keys.extend(row.get(field) or [])
    for field in ("decision_key", "newer_key", "older_key", "subject", "object", "natural_key"):
        if row.get(field):
            keys.append(row[field])
    out = []
    for k in keys:
        if not k:
            continue
        out.append(k)
        if ":" in k:
            out.append(k.split(":", 1)[1])
    return out


def _contains_forbidden(question: str, forbidden: list[str]) -> bool:
    q = question.lower()
    for f in forbidden:
        if not f:
            continue
        # Skip tiny fragments
        if len(f) < 6 and ":" not in f:
            continue
        if f.lower() in q:
            return True
    return False


def _fallback_question(row: dict) -> str:
    slice_ = row.get("slice")
    if slice_ == "fact":
        title = row.get("title") or "this design decision"
        return f"Why was the decision made to {title[0].lower() + title[1:] if title else 'change this'}?"
    if slice_ == "current":
        title = row.get("newer_title") or "the current approach"
        return f"What is the current approach regarding {title}?"
    if slice_ == "structural":
        kind = row.get("kind")
        if kind == "closes":
            return "Which issue or pull request was closed by this change?"
        if kind == "authored_by":
            msg = (row.get("message") or "").split("\n", 1)[0][:60]
            return f"Who authored the commit about {msg}?" if msg else "Who authored this commit?"
        return "What files or entities are linked by this structural claim?"
    if slice_ == "unanswerable":
        topic = row.get("hint_topic") or row.get("title") or "this topic"
        return f"What does the knowledge graph say about {topic}?"
    return "What evidence supports this claim in the repository knowledge graph?"


def _prompt_for(row: dict) -> str:
    payload = {
        "slice": row.get("slice"),
        "title": row.get("title") or row.get("newer_title") or row.get("hint_topic"),
        "excerpt": (row.get("excerpt") or row.get("message") or row.get("message_excerpt") or "")[:400],
        "kind": row.get("kind"),
        "must_refuse": row.get("must_refuse", False),
        "older_title": row.get("older_title"),
        "newer_title": row.get("newer_title"),
        "person_name": row.get("person_name"),
    }
    return "Create a question for this eval candidate:\n" + json.dumps(payload, ensure_ascii=False)


def generate_question(client: genai.Client, row: dict) -> str:
    if not config.GEMINI_API_KEY:
        return _fallback_question(row)
    try:
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL_PARSER,
            contents=_prompt_for(row),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.0,
                max_output_tokens=120,
                response_mime_type="application/json",
            ),
        )
        text = (resp.text or "").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        data = json.loads(text)
        q = (data.get("question") or "").strip()
        if not q:
            return _fallback_question(row)
        return q
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini question gen failed: %s", exc)
        return _fallback_question(row)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates", type=Path, default=PROJECT_ROOT / "evals" / "candidates.jsonl"
    )
    parser.add_argument(
        "--out", type=Path, default=PROJECT_ROOT / "evals" / "questions_draft.jsonl"
    )
    parser.add_argument("--per-slice", type=int, default=25)
    args = parser.parse_args()

    rows = [json.loads(line) for line in args.candidates.read_text().splitlines() if line.strip()]
    by_slice: dict[str, list] = {}
    for r in rows:
        by_slice.setdefault(r["slice"], []).append(r)

    selected: list[dict] = []
    for slice_name, items in by_slice.items():
        selected.extend(items[: args.per_slice])

    client = genai.Client(api_key=config.GEMINI_API_KEY) if config.GEMINI_API_KEY else None
    out_rows = []
    for i, row in enumerate(selected):
        if client:
            question = generate_question(client, row)
        else:
            question = _fallback_question(row)
        forbidden = _forbidden_substrings(row)
        if _contains_forbidden(question, forbidden):
            logger.warning("Regenerating question that leaked a gold key: %s", question)
            question = _fallback_question(row)
            if _contains_forbidden(question, forbidden):
                # Strip any leaked keys
                for f in forbidden:
                    question = re.sub(re.escape(f), "", question, flags=re.IGNORECASE)
                question = " ".join(question.split())

        out = {
            "draft_id": f"{row['slice']}-{i:03d}",
            "slice": row["slice"],
            "question": question,
            "gold_source_keys": row.get("gold_source_keys") or [],
            "gold_entity_keys": row.get("gold_entity_keys") or [],
            "forbidden_keys": row.get("forbidden_keys") or [],
            "must_refuse": bool(row.get("must_refuse")),
            "candidate": {
                k: row.get(k)
                for k in (
                    "decision_key",
                    "title",
                    "newer_key",
                    "newer_title",
                    "older_key",
                    "kind",
                    "subject",
                    "object",
                    "natural_key",
                    "timeline_index",
                    "hint_topic",
                    "evidence_source",
                )
                if row.get(k) is not None
            },
            "adjudicated": False,
        }
        out_rows.append(out)
        if (i + 1) % 10 == 0:
            logger.info("Generated %d/%d questions", i + 1, len(selected))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        for row in out_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    logger.info("Wrote %d draft questions to %s", len(out_rows), args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
