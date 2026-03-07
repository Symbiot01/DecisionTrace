from __future__ import annotations

import logging
import time
from typing import Any

import neo4j

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5


class Neo4jClient:
    def __init__(self, uri: str, username: str, password: str, database: str):
        self.driver = neo4j.GraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_lifetime=300,
            connection_acquisition_timeout=60,
        )
        self.database = database

    def close(self):
        self.driver.close()

    def run(self, query: str, **params: Any) -> list[dict]:
        for attempt in range(MAX_RETRIES):
            try:
                with self.driver.session(database=self.database) as session:
                    result = session.run(query, **params)
                    return [record.data() for record in result]
            except (neo4j.exceptions.ServiceUnavailable, neo4j.exceptions.SessionExpired, OSError) as e:
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        "Neo4j connection error (attempt %d/%d): %s",
                        attempt + 1, MAX_RETRIES, e,
                    )
                    time.sleep(RETRY_DELAY * (attempt + 1))
                else:
                    raise

    def schema_init(self):
        """Create uniqueness constraints and indexes. Pure Cypher, no APOC."""
        constraints = [
            ("Person", "natural_key"),
            ("FileNode", "natural_key"),
            ("Commit", "natural_key"),
            ("PullRequest", "natural_key"),
            ("Issue", "natural_key"),
            ("Discussion", "natural_key"),
            ("Branch", "natural_key"),
            ("Label", "natural_key"),
            ("Tag", "natural_key"),
            ("Component", "natural_key"),
            ("DesignDecision", "natural_key"),
            ("Repository", "natural_key"),
        ]
        for label, prop in constraints:
            self.run(
                f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.{prop} IS UNIQUE"
            )
        logger.info("Schema initialized: %d uniqueness constraints", len(constraints))

        fulltext_indexes = [
            (
                "search_nodes",
                ["PullRequest", "Issue", "Discussion", "DesignDecision", "Component", "Commit"],
                ["title", "body", "message", "evidence_excerpt", "natural_key"],
            ),
        ]
        for idx_name, labels, props in fulltext_indexes:
            label_str = "|".join(labels)
            prop_str = ", ".join(f"n.{p}" for p in props)
            self.run(
                f"CREATE FULLTEXT INDEX {idx_name} IF NOT EXISTS "
                f"FOR (n:{label_str}) ON EACH [{prop_str}]"
            )
        logger.info("Full-text indexes initialized")

    def upsert_node(self, label: str, natural_key: str, properties: dict):
        props = {k: v for k, v in properties.items() if v is not None}
        query = f"""
        MERGE (n:{label} {{natural_key: $nk}})
        ON CREATE SET n += $props, n.created_at = datetime()
        ON MATCH SET n += $props, n.updated_at = datetime()
        """
        self.run(query, nk=natural_key, props=props)

    def upsert_relationship(
        self, subj_key: str, predicate: str, obj_key: str, properties: dict
    ):
        props = {k: v for k, v in properties.items() if v is not None}
        query = f"""
        MATCH (s {{natural_key: $sk}})
        MATCH (o {{natural_key: $ok}})
        MERGE (s)-[r:{predicate}]->(o)
        ON CREATE SET r += $props, r.processing_time = datetime()
        """
        self.run(query, sk=subj_key, ok=obj_key, props=props)

    def node_exists(self, natural_key: str) -> bool:
        result = self.run(
            "MATCH (n {natural_key: $nk}) RETURN count(n) AS c", nk=natural_key
        )
        return result[0]["c"] > 0 if result else False

    def update_node_aliases(self, natural_key: str, new_aliases: list[str]):
        """Merge alias arrays without APOC — pure Cypher list filtering."""
        query = """
        MATCH (n {natural_key: $key})
        SET n.aliases = n.aliases + [x IN $new WHERE NOT x IN n.aliases]
        """
        self.run(query, key=natural_key, new=new_aliases)

    def wipe(self):
        """Delete all nodes and relationships in batches (for --reset)."""
        logger.warning("Wiping entire graph database")
        while True:
            result = self.run(
                "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS deleted"
            )
            if not result or result[0]["deleted"] == 0:
                break

    def read_query(self, cypher: str, **params: Any) -> list[dict]:
        """Execute a read-only query. Used by the agent's query_graph tool."""
        return self.run(cypher, **params)
