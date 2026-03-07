from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from layerten import config

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


_gemini_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


_SYSTEM = """You parse user questions about a GitHub repository knowledge graph.
Extract intent, keywords, and entity references. Output ONLY a single-line JSON object, no markdown.

intent: entity_lookup | history | decision | who | why | what_changed | general
keywords: search terms, lowercase, no stop words
entity_refs: natural keys found in the question, e.g. "pr:42", "issue:10", "person:jxnl"

Example input: "Why did we switch to Pydantic V2?"
Example output: {"intent":"decision","keywords":["pydantic","v2","switch"],"entity_refs":[]}"""


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
        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Parse this question: {question}",
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM,
                temperature=0.0,
                max_output_tokens=300,
                response_mime_type="application/json",
            ),
        )
        text = resp.text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
        data = json.loads(text)
        return ParsedQuestion(
            intent=data.get("intent", "general"),
            keywords=data.get("keywords", []),
            entity_refs=data.get("entity_refs", []),
        )
    except Exception:
        logger.warning("Gemini question parsing failed, using keyword fallback", exc_info=True)
        return _keyword_fallback(question)
