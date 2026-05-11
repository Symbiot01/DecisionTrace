from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any

import neo4j

from layerten import config

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 5

# Predicates / labels we batch (must be known identifiers — never user-concat untrusted)
_ALLOWED_LABELS = frozenset({
    "Person", "FileNode", "Commit", "PullRequest", "Issue", "Discussion",
    "Branch", "Label", "Tag", "Component", "DesignDecision", "Repository",
})
_ALLOWED_PREDICATES = frozenset({
    "MODIFIES", "CLOSES", "REFERENCES", "AUTHORED_BY", "REVIEWED_BY",
    "ASSIGNED_TO", "INTRODUCES", "REVERTS", "DEPRECATES", "DEPENDS_ON",
    "BELONGS_TO", "DECISION_FOR", "SUPERSEDES", "RENAMES", "MERGED_INTO",
    "CHERRY_PICKED_FROM", "REBASE_OF", "ON_BRANCH", "STATE_CHANGED_TO",
    "HAS_ENTITY",
})


class Neo4jClient:
    def __init__(
        self,
        uri: str,
        username: str,
        password: str,
        database: str,
        batch_size: int | None = None,
    ):
        self.driver = neo4j.GraphDatabase.driver(
            uri,
            auth=(username, password),
            max_connection_lifetime=300,
            connection_acquisition_timeout=60,
        )
        self.database = database or None
        self.batch_size = max(1, int(batch_size or getattr(config, "NEO4J_BATCH_SIZE", 500)))
        self._node_buf: dict[str, dict[str, dict]] = defaultdict(dict)  # label -> nk -> props
        self._rel_buf: dict[str, list[dict]] = defaultdict(list)  # predicate -> rows
        self._known_keys: set[str] = set()
        self._batching = False  # enable explicitly in process orchestrator

    def close(self):
        try:
            self.flush()
        finally:
            self.driver.close()

    def enable_batching(self, enabled: bool = True) -> None:
        if not enabled:
            self.flush()
        self._batching = enabled

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
            try:
                self.run(
                    f"CREATE FULLTEXT INDEX {idx_name} IF NOT EXISTS "
                    f"FOR (n:{label_str}) ON EACH [{prop_str}]"
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("fulltext index skipped: %s", exc)
        logger.info("Full-text indexes initialized")

    def upsert_node(self, label: str, natural_key: str, properties: dict):
        if label not in _ALLOWED_LABELS:
            raise ValueError(f"Unsupported label: {label}")
        props = {k: v for k, v in properties.items() if v is not None}
        self._known_keys.add(natural_key)
        if not self._batching:
            self._flush_nodes(label, {natural_key: props})
            return
        # Later props win for same key in batch
        self._node_buf[label][natural_key] = props
        if sum(len(v) for v in self._node_buf.values()) >= self.batch_size:
            self.flush_nodes()

    def upsert_relationship(
        self, subj_key: str, predicate: str, obj_key: str, properties: dict
    ):
        if predicate not in _ALLOWED_PREDICATES:
            raise ValueError(f"Unsupported predicate: {predicate}")
        props = {k: v for k, v in properties.items() if v is not None}
        if not self._batching:
            self.flush_nodes()
            self._flush_rels(predicate, [{"sk": subj_key, "ok": obj_key, "props": props}])
            return
        self._rel_buf[predicate].append({"sk": subj_key, "ok": obj_key, "props": props})
        if sum(len(v) for v in self._rel_buf.values()) >= self.batch_size:
            # Nodes must exist before relationships
            self.flush_nodes()
            self.flush_relationships()

    def flush_nodes(self) -> int:
        total = 0
        for label, by_key in list(self._node_buf.items()):
            if not by_key:
                continue
            rows = [{"nk": nk, "props": props} for nk, props in by_key.items()]
            self._flush_nodes(label, {r["nk"]: r["props"] for r in rows})
            total += len(rows)
            by_key.clear()
        return total

    def flush_relationships(self) -> int:
        total = 0
        for predicate, rows in list(self._rel_buf.items()):
            if not rows:
                continue
            # Chunk large buffers
            for i in range(0, len(rows), self.batch_size):
                chunk = rows[i : i + self.batch_size]
                self._flush_rels(predicate, chunk)
                total += len(chunk)
            rows.clear()
        return total

    def flush(self) -> None:
        """Flush buffered nodes then relationships (order matters)."""
        n = self.flush_nodes()
        r = self.flush_relationships()
        if n or r:
            logger.debug("Neo4j batch flush: %d nodes, %d rels", n, r)

    def _flush_nodes(self, label: str, by_key: dict[str, dict]) -> None:
        if not by_key:
            return
        rows = [{"nk": nk, "props": props} for nk, props in by_key.items()]
        for i in range(0, len(rows), self.batch_size):
            chunk = rows[i : i + self.batch_size]
            query = f"""
            UNWIND $rows AS row
            MERGE (n:{label} {{natural_key: row.nk}})
            ON CREATE SET n += row.props, n.created_at = datetime()
            ON MATCH SET n += row.props, n.updated_at = datetime()
            """
            self.run(query, rows=chunk)

    def _flush_rels(self, predicate: str, rows: list[dict]) -> None:
        if not rows:
            return
        query = f"""
        UNWIND $rows AS row
        MATCH (s {{natural_key: row.sk}})
        MATCH (o {{natural_key: row.ok}})
        MERGE (s)-[r:{predicate}]->(o)
        ON CREATE SET r += row.props, r.processing_time = datetime()
        ON MATCH SET r += row.props
        """
        self.run(query, rows=rows)

    def node_exists(self, natural_key: str) -> bool:
        if natural_key in self._known_keys:
            return True
        if natural_key in self._node_buf.get("Person", {}):
            return True
        # Check any buffered label
        for by_key in self._node_buf.values():
            if natural_key in by_key:
                return True
        result = self.run(
            "MATCH (n {natural_key: $nk}) RETURN count(n) AS c", nk=natural_key
        )
        exists = result[0]["c"] > 0 if result else False
        if exists:
            self._known_keys.add(natural_key)
        return exists

    def update_node_aliases(self, natural_key: str, new_aliases: list[str]):
        """Merge alias arrays without APOC — pure Cypher list filtering."""
        self.flush()
        query = """
        MATCH (n {natural_key: $key})
        SET n.aliases = coalesce(n.aliases, []) + [x IN $new WHERE NOT x IN coalesce(n.aliases, [])]
        """
        self.run(query, key=natural_key, new=new_aliases)

    def wipe(self):
        """Delete all nodes and relationships in batches (for --reset)."""
        self._node_buf.clear()
        self._rel_buf.clear()
        self._known_keys.clear()
        logger.warning("Wiping entire graph database")
        while True:
            result = self.run(
                "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(*) AS deleted"
            )
            if not result or result[0]["deleted"] == 0:
                break

    def read_query(self, cypher: str, **params: Any) -> list[dict]:
        """Execute a read-only query. Used by the agent's query_graph tool."""
        self.flush()
        return self.run(cypher, **params)
