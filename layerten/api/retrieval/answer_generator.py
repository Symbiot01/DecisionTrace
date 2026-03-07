from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types

from layerten import config

logger = logging.getLogger(__name__)

_ASK_CLIENT: genai.Client | None = None


def _get_client() -> genai.Client:
    global _ASK_CLIENT
    if _ASK_CLIENT is None:
        _ASK_CLIENT = genai.Client(api_key=config.GEMINI_API_KEY)
    return _ASK_CLIENT


def build_evidence_context(formatted_results: list[dict[str, Any]], max_sources: int = 8) -> str:
    """Build a numbered evidence block for the LLM. Each source is [N] with excerpt, description/rationale when present, and source key."""
    lines = []
    for i, r in enumerate(formatted_results[:max_sources], start=1):
        entity = r.get("subject_entity") or {}
        title = entity.get("title", "")
        evidence = r.get("evidence") or {}
        excerpt = evidence.get("excerpt") or "(no excerpt)"
        source_key = evidence.get("source_key") or entity.get("natural_key", "")
        claim = r.get("claim")
        claim_str = ""
        if claim:
            claim_str = f" Claim: {claim.get('subject_key')} --{claim.get('predicate')}--> {claim.get('object_key')}."
        block = f"[{i}] {title}{claim_str}\nEvidence: {excerpt}"
        for key in ("description", "rationale", "summary"):
            val = entity.get(key)
            if val and isinstance(val, str) and val.strip():
                block += f"\n{key.capitalize()}: {val.strip()}"
        block += f"\nSource: {source_key}"
        lines.append(block)
    return "\n\n".join(lines) if lines else "(No evidence retrieved.)"


_SYSTEM = """You answer questions about a software repository using ONLY the numbered evidence provided below.

Rules:
- Answer the user's question directly first. Start with 1-2 sentences that directly address what they asked (e.g. if they ask "why", lead with the reason or rationale from the evidence).
- Prefer evidence that explicitly states a decision, rationale, "why", or description when the question asks for a reason or explanation. Evidence blocks may include a "Description:" or "Rationale:" line—use that when the question asks "why" or "how".
- Base every part of your answer on the evidence. Cite sources with [1], [2], etc. after the relevant sentence or phrase.
- If no evidence directly answers the question, say so clearly at the start (e.g. "The evidence does not directly state why...") and then briefly summarize what the evidence does say.
- Be concise. Prefer short paragraphs and bullet points when listing multiple facts.
- Do not invent information. Only use what appears in the evidence blocks.
- When referencing a decision, PR, or issue, use the citation number so the user can check the source."""


async def generate_answer(question: str, formatted_results: list[dict[str, Any]]) -> str:
    """Generate an answer that cites the provided evidence. Returns answer text with [1], [2] markers."""
    if not config.GEMINI_API_KEY:
        return (
            "Answer generation is not configured (missing GEMINI_API_KEY). "
            "Use the Search tab to view retrieved evidence only."
        )

    context = build_evidence_context(formatted_results)
    if "(No evidence retrieved.)" in context:
        return "No relevant evidence was found in the knowledge graph for this question. Try rephrasing or use Search to explore."

    user_content = f"""Evidence from the knowledge graph:

{context}

---

Question: {question}

Instructions: Answer the question directly in your first 1-2 sentences. Use the evidence block that best answers the question (e.g. for "why" questions, prefer blocks that include Description or Rationale). Cite each fact with [1], [2], etc."""

    try:
        client = _get_client()
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.2,
                max_output_tokens=1024,
            ),
        )
        text = (resp.text or "").strip()
        return text if text else "Could not generate an answer."
    except Exception as e:
        logger.warning("Answer generation failed: %s", e, exc_info=True)
        return f"Answer generation failed: {e}. Use the Search tab to view the retrieved evidence."