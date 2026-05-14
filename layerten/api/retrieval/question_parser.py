from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from layerten import config, gemini_pool

logger = logging.getLogger(__name__)

STOPWORDS = frozenset(
    "a an the is was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "through during before after above below between out off over under again "
    "further then once here there when where why how all each every both few "
    "more most other some such no nor not only own same so than too very it its "
    "i me my we our you your he him his she her they them their what which who "
    "whom this that these those am are and but if or because until while about".split()
)


@dataclass
class ParsedQuestion:
    intent: str = "general"
    keywords: list[str] = field(default_factory=list)
    entity_refs: list[str] = field(default_factory=list)


def _get_client() -> genai.Client:
    # Shared pool client, which carries an explicit request timeout. A bare
    # genai.Client has none, so a stalled call blocked the event loop and hung
    # the whole API until every later request timed out.
    return gemini_pool.get_client()


_SYSTEM = """You parse user questions about a GitHub repository knowledge graph.
Extract intent, keywords, and entity references. Output ONLY a single-line JSON object, no markdown.

intent: entity_lookup | history | decision | who | why | what_changed | current_state | general
keywords: search terms, lowercase, no stop words
entity_refs: natural keys found in the question, e.g. "pr:42", "issue:10", "person:jxnl"

Use current_state when the question asks what the behaviour is today ("how does X
work now", "what is the current way to Y"). Use what_changed or history only when
the question asks for the sequence of changes over time ("how did X evolve",
"what changed in Y"). A question containing "now" is usually current_state.

Example input: "Why did we switch to Pydantic V2?"
Example output: {"intent":"decision","keywords":["pydantic","v2","switch"],"entity_refs":[]}

Example input: "How are column options specified now?"
Example output: {"intent":"current_state","keywords":["column","options","specified"],"entity_refs":[]}"""


def _keyword_fallback(question: str) -> ParsedQuestion:
    """Simple keyword extraction without LLM."""
    tokens = re.findall(r"[a-zA-Z0-9_\-./:#]+", question.lower())
    keywords = [t for t in tokens if t not in STOPWORDS and len(t) > 1]

    entity_refs: list[str] = []
    for m in re.finditer(r"(?:pr|pull request|pull)[\s#]*(\d+)", question, re.IGNORECASE):
        entity_refs.append(f"pr:{m.group(1)}")
    for m in re.finditer(r"(?:issue)[\s#]*(\d+)", question, re.IGNORECASE):
        entity_refs.append(f"issue:{m.group(1)}")
    for m in re.finditer(r"#(\d+)", question):
        ref = f"pr:{m.group(1)}"
        if ref not in entity_refs:
            entity_refs.append(ref)

    intent = "general"
    q = question.lower()
    if any(w in q for w in ("who ", "author", "contributor")):
        intent = "who"
    elif any(w in q for w in ("why ", "decision", "chose", "reason")):
        intent = "decision"
    elif any(w in q for w in ("history", "changed", "evolution")):
        intent = "history"
    elif any(w in q for w in ("what is", "what does", "explain")):
        intent = "entity_lookup"

    return ParsedQuestion(intent=intent, keywords=keywords, entity_refs=entity_refs)


async def parse_question(question: str) -> ParsedQuestion:
    if not config.GEMINI_API_KEY:
        return _keyword_fallback(question)

    try:
        client = _get_client()
        # The SDK call is synchronous. Called inline it blocks the event loop,
        # so one slow parse stalls every other in-flight request.
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model=config.GEMINI_MODEL_PARSER,
            contents=f"Parse this question: {question}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.0,
                # Thinking models spend this budget on reasoning tokens first.
                # At 300 the budget was exhausted before any text was emitted,
                # so parsing silently fell back to keywords and lost the intent.
                max_output_tokens=512,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
                response_mime_type="application/json",
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            raise ValueError(
                f"empty response (finish_reason="
                f"{getattr(resp.candidates[0], 'finish_reason', None) if resp.candidates else None})"
            )
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        data = json.loads(text)
        return ParsedQuestion(
            intent=data.get("intent", "general"),
            keywords=data.get("keywords", []),
            entity_refs=data.get("entity_refs", []),
        )
    except Exception as exc:  # noqa: BLE001
        # A dead/renamed model degrades every query to the regex fallback, so it
        # must be loud rather than a debug-level warning.
        logger.error(
            "Question parsing failed with model %r (%s) — falling back to keyword "
            "extraction; retrieval quality is degraded until this is fixed",
            config.GEMINI_MODEL_PARSER,
            exc,
        )
        return _keyword_fallback(question)
