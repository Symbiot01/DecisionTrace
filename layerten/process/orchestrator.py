from __future__ import annotations

import logging
import time

from layerten.config import (
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    UNIFIED_TIMELINE_PATH,
)
from layerten.process.bootstrap import (
    build_timeline_index,
    clear_checkpoint,
    create_repository_node,
    load_checkpoint,
    load_reference_data,
    save_checkpoint,
    stream_timeline,
)
from layerten.process.deterministic import deterministic_extract
from layerten.process.neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


def run_processing(
    limit: int | None = None,
    skip_agentic: bool = False,
    reset: bool = False,
):
    neo4j = Neo4jClient(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE)

    try:
        if reset:
            neo4j.wipe()
            clear_checkpoint()

        neo4j.schema_init()
        ref_data = load_reference_data()
        create_repository_node(neo4j)
        last_index = load_checkpoint()
        ref_data.timeline_index = build_timeline_index(UNIFIED_TIMELINE_PATH)

        processed = 0
        skipped = 0
        agentic_count = 0
        start_time = time.time()

        for event in stream_timeline(UNIFIED_TIMELINE_PATH):
            idx = event.get("timeline_index", -1)
            if idx <= last_index:
                skipped += 1
                continue
            if limit is not None and processed >= limit:
                break

            deterministic_extract(event, ref_data, neo4j)

            if (
                not skip_agentic
                and event.get("processing_hints", {}).get("needs_agentic", False)
            ):
                try:
                    from layerten.process.agent import agentic_extract

                    agentic_extract(event, neo4j, ref_data)
                    agentic_count += 1
                except ImportError:
                    logger.debug("Agentic module not yet available, skipping")
                except Exception as e:
                    logger.error(
                        "Agentic extraction failed for %s: %s",
                        event.get("natural_key"), e,
                    )

            save_checkpoint(idx)
            processed += 1

            if processed % 100 == 0:
                elapsed = time.time() - start_time
                rate = processed / elapsed if elapsed > 0 else 0
                logger.info(
                    "Progress: %d events processed (%.1f events/sec), %d agentic",
                    processed,
                    rate,
                    agentic_count,
                )

        elapsed = time.time() - start_time
        logger.info(
            "Processing complete: %d events in %.1fs (skipped %d, agentic %d)",
            processed,
            elapsed,
            skipped,
            agentic_count,
        )

    finally:
        neo4j.close()
