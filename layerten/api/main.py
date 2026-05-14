from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from layerten import config
from layerten.process.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)

neo4j_client: Neo4jClient | None = None


def get_neo4j() -> Neo4jClient:
    assert neo4j_client is not None, "Neo4j not initialised"
    return neo4j_client


def check_gemini_models() -> dict[str, bool]:
    """Verify configured Gemini models still exist.

    A deprecated model returns 404 at call time and the callers fall back
    silently, so retrieval quality degrades with no obvious signal. Probe once
    at startup and log loudly. Never fatal: the API still serves graph routes.
    """
    results: dict[str, bool] = {}
    if not config.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set; question parsing and Ask are degraded")
        return results

    from google import genai

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    for label, model in (
        ("parser", config.GEMINI_MODEL_PARSER),
        ("rag", config.GEMINI_MODEL_RAG),
    ):
        try:
            client.models.get(model=model)
            results[label] = True
        except Exception as exc:  # noqa: BLE001
            results[label] = False
            logger.error(
                "Configured %s model %r is unavailable (%s). Set GEMINI_MODEL_%s "
                "to a supported model.",
                label,
                model,
                exc,
                label.upper(),
            )
    if all(results.values()):
        logger.info(
            "Gemini models OK: parser=%s rag=%s",
            config.GEMINI_MODEL_PARSER,
            config.GEMINI_MODEL_RAG,
        )
    return results


@asynccontextmanager
async def lifespan(app: FastAPI):
    global neo4j_client
    neo4j_client = Neo4jClient(
        uri=config.NEO4J_URI,
        username=config.NEO4J_USERNAME,
        password=config.NEO4J_PASSWORD,
        database=config.NEO4J_DATABASE,
    )
    neo4j_client.schema_init()
    logger.info("Neo4j connected, schema initialized")
    check_gemini_models()
    yield
    neo4j_client.close()
    logger.info("Neo4j disconnected")


app = FastAPI(title="LayerTen Retrieval API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from layerten.api.routes import query, ask, entities, graph, decisions, contributors, stats, pipeline  # noqa: E402

app.include_router(query.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(decisions.router, prefix="/api")
app.include_router(contributors.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
