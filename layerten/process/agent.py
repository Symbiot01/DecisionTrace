from __future__ import annotations

import json
import logging
import time

from google.genai import types

from layerten.config import GEMINI_API_KEY, GEMINI_MODEL_EXTRACTION as GEMINI_MODEL
from layerten.gemini_pool import generate_content_limited
from layerten.process.bootstrap import ReferenceData
from layerten.process.neo4j_client import Neo4jClient
from layerten.process.prompts import SYSTEM_PROMPT, format_event_prompt
from layerten.process.tools.code_access import read_codebase, read_diff
from layerten.process.tools.event_access import get_event, get_related_events
from layerten.process.tools.graph_read import query_graph
from layerten.process.tools.graph_write import (
    supersede_claim,
    update_node,
    write_node,
    write_relationship,
)

logger = logging.getLogger(__name__)

TOOL_DECLARATIONS = types.Tool(function_declarations=[
    {
        "name": "read_diff",
        "description": "Get the untruncated diff for a commit. Optionally filter to a single file path.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "sha": {"type": "STRING", "description": "The commit SHA"},
                "path": {"type": "STRING", "description": "Optional file path to filter diff"},
            },
            "required": ["sha"],
        },
    },
    {
        "name": "read_codebase",
        "description": "Read a file's content at any git ref (commit SHA, branch, tag, or HEAD).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "File path relative to repo root"},
                "ref": {"type": "STRING", "description": "Git ref (SHA, branch, tag). Defaults to HEAD."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "query_graph",
        "description": "Execute a read-only Cypher query against the knowledge graph. Only MATCH/RETURN allowed.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "cypher": {"type": "STRING", "description": "The Cypher query (read-only)"},
            },
            "required": ["cypher"],
        },
    },
    {
        "name": "get_event",
        "description": "Get the full event data for a given natural_key from the timeline.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "Natural key, e.g. 'pr:42' or 'commit:abc123'"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_related_events",
        "description": "Find events related to a given key via cross-references or shared attributes.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "Natural key of the source event"},
                "types": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Filter by event types, e.g. ['pr', 'commit']. Null for all.",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "write_node",
        "description": "Create or update an entity node (DesignDecision, Component, etc.) with evidence.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "label": {"type": "STRING", "description": "Node label (e.g. DesignDecision, Component)"},
                "natural_key": {"type": "STRING", "description": "Unique key, e.g. 'decision:migrate-to-pydantic-v2'"},
                "properties": {
                    "type": "OBJECT",
                    "description": "Node properties (title, status, confidence, etc.)",
                },
                "evidence": {
                    "type": "OBJECT",
                    "description": "Evidence object with 'excerpt' (exact quote) and 'source' (event key)",
                },
            },
            "required": ["label", "natural_key", "properties", "evidence"],
        },
    },
    {
        "name": "write_relationship",
        "description": "Create a relationship between two existing nodes with evidence.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "subject_key": {"type": "STRING", "description": "Natural key of the subject node"},
                "predicate": {"type": "STRING", "description": "Relationship type (e.g. INTRODUCES, SUPERSEDES)"},
                "object_key": {"type": "STRING", "description": "Natural key of the object node"},
                "properties": {
                    "type": "OBJECT",
                    "description": "Relationship properties (event_time_from, confidence, etc.)",
                },
                "evidence": {
                    "type": "OBJECT",
                    "description": "Evidence object with 'excerpt' and 'source'",
                },
            },
            "required": ["subject_key", "predicate", "object_key", "properties", "evidence"],
        },
    },
    {
        "name": "update_node",
        "description": "Update properties on an existing node.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "natural_key": {"type": "STRING", "description": "Natural key of the node to update"},
                "updates": {"type": "OBJECT", "description": "Properties to update"},
                "evidence": {"type": "OBJECT", "description": "Evidence with 'excerpt' and 'source'"},
            },
            "required": ["natural_key", "updates", "evidence"],
        },
    },
    {
        "name": "supersede_claim",
        "description": "Mark an old claim as superseded and optionally create a new one.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "old_claim_key": {"type": "STRING", "description": "Natural key of the claim to supersede"},
                "new_claim": {
                    "type": "OBJECT",
                    "description": "New claim: {label, natural_key, properties}",
                },
                "reason": {"type": "STRING", "description": "Why the old claim is superseded"},
                "evidence": {"type": "OBJECT", "description": "Evidence with 'excerpt' and 'source'"},
            },
            "required": ["old_claim_key", "new_claim", "reason", "evidence"],
        },
    },
])


def _sanitize_for_json(obj):
    """Convert Neo4j DateTime and other non-serializable types to strings."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)


def _execute_tool(
    name: str,
    args: dict,
    neo4j: Neo4jClient,
    ref_data: ReferenceData,
) -> dict:
    """Route a function call to the appropriate tool and return the result."""
    if name == "read_diff":
        return read_diff(args["sha"], args.get("path"))
    elif name == "read_codebase":
        return read_codebase(args["path"], args.get("ref", "HEAD"))
    elif name == "query_graph":
        return query_graph(args["cypher"], neo4j)
    elif name == "get_event":
        return get_event(args["key"], ref_data)
    elif name == "get_related_events":
        return get_related_events(args["key"], args.get("types"), ref_data)
    elif name == "write_node":
        return write_node(
            args["label"], args["natural_key"],
            args.get("properties", {}), args.get("evidence", {}), neo4j,
        )
    elif name == "write_relationship":
        return write_relationship(
            args.get("subject_key", args.get("subj", "")),
            args.get("predicate", args.get("pred", "")),
            args.get("object_key", args.get("obj", "")),
            args.get("properties", {}), args.get("evidence", {}), neo4j,
        )
    elif name == "update_node":
        return update_node(
            args["natural_key"], args.get("updates", {}),
            args.get("evidence", {}), neo4j,
        )
    elif name == "supersede_claim":
        return supersede_claim(
            args["old_claim_key"], args.get("new_claim", {}),
            args.get("reason", ""), args.get("evidence", {}), neo4j,
        )
    else:
        return {"error": f"Unknown tool: {name}"}


def agentic_extract(
    event: dict,
    neo4j: Neo4jClient,
    ref_data: ReferenceData,
    max_turns: int = 10,
):
    """Run the Gemini agentic extraction loop for a single event."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=[TOOL_DECLARATIONS],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        ),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            disable=True,
        ),
    )

    event_prompt = format_event_prompt(event)
    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=event_prompt)],
        ),
    ]

    nk = event.get("natural_key", "")
    total_tool_calls = 0

    for turn in range(max_turns):
        try:
            response = generate_content_limited(
                model=GEMINI_MODEL,
                contents=contents,
                config=config,
            )
        except Exception as e:
            logger.error("Gemini API error for %s (turn %d): %s", nk, turn, e)
            if "429" in str(e) or "quota" in str(e).lower():
                logger.warning("Rate limited, sleeping 60s...")
                time.sleep(60)
                continue
            break

        # A blocked, empty, or token-truncated response still returns a
        # candidate, but with content.parts set to None. Iterating it raised
        # "'NoneType' object is not iterable" and silently dropped ~30% of
        # events, so treat it as a retryable empty turn instead.
        candidates = response.candidates or []
        if not candidates:
            logger.warning(
                "Gemini returned no candidates for %s (turn %d, prompt_feedback=%s)",
                nk,
                turn,
                getattr(response, "prompt_feedback", None),
            )
            continue

        candidate = candidates[0]
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) if content is not None else None
        if not parts:
            finish_reason = getattr(candidate, "finish_reason", None)
            # An empty turn after the agent has already called tools is just how
            # it signals completion. Before any tool call it means nothing was
            # extracted, which is worth one more attempt.
            if total_tool_calls:
                logger.debug(
                    "Empty final turn for %s after %d tool calls (finish_reason=%s)",
                    nk,
                    total_tool_calls,
                    finish_reason,
                )
                break
            logger.warning(
                "Gemini returned no content parts for %s before any tool call "
                "(turn %d, finish_reason=%s)",
                nk,
                turn,
                finish_reason,
            )
            continue

        function_calls = [p for p in parts if p.function_call]

        if not function_calls:
            text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
            if text_parts:
                logger.debug("Agent response for %s: %s", nk, text_parts[0][:200])
            break

        function_responses = []
        for part in function_calls:
            fc = part.function_call
            total_tool_calls += 1
            logger.debug("Tool call %s(%s) for %s", fc.name, str(fc.args)[:200], nk)

            try:
                result = _execute_tool(fc.name, dict(fc.args), neo4j, ref_data)
            except Exception as e:
                logger.warning("Tool %s failed: %s", fc.name, e)
                result = {"error": str(e)}

            result = _sanitize_for_json(result)
            result_str = json.dumps(result, default=str)
            if len(result_str) > 10000:
                result = {"summary": result_str[:9000] + "... (truncated)"}

            function_responses.append(
                types.Part.from_function_response(name=fc.name, response=result)
            )

        contents.append(candidate.content)
        contents.append(
            types.Content(role="user", parts=function_responses)
        )

    turns_used = turn + 1 if max_turns > 0 else 0
    logger.info(
        "Agentic extraction for %s: %d turns, %d tool calls",
        nk, turns_used, total_tool_calls,
    )
