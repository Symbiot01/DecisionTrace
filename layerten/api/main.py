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

from layerten.api.routes import query, ask, entities, graph, decisions, contributors, stats  # noqa: E402

app.include_router(query.router, prefix="/api")
app.include_router(ask.router, prefix="/api")
app.include_router(entities.router, prefix="/api")
app.include_router(graph.router, prefix="/api")
app.include_router(decisions.router, prefix="/api")
app.include_router(contributors.router, prefix="/api")
app.include_router(stats.router, prefix="/api")
