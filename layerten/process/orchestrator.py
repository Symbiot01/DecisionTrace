from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Callable, Optional

from layerten import config
from layerten.config import (
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USERNAME,
    UNIFIED_TIMELINE_PATH,
)
from layerten.gemini_pool import reset_limits
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

ProgressCb = Optional[Callable[[dict[str, Any]], None]]


def run_processing(
    limit: int | None = None,
    skip_agentic: bool = False,
    reset: bool = False,
    on_progress: ProgressCb = None,
):
    """
    Process timeline into Neo4j.

    Deterministic extraction uses batched UNWIND writes (NEO4J_BATCH_SIZE).
    Agentic Gemini calls run in a bounded thread pool after flushing batches.
    """
    reset_limits(
        concurrency=config.GEMINI_MAX_CONCURRENCY,
        rps=config.GEMINI_RPS,
    )
    batch_size = max(50, int(config.NEO4J_BATCH_SIZE))
    neo4j = Neo4jClient(
        NEO4J_URI,
        NEO4J_USERNAME,
        NEO4J_PASSWORD,
        NEO4J_DATABASE,
        batch_size=batch_size,
    )
    neo4j.enable_batching(True)
    # Flush deterministic batches every N events (and always before agentic)
    flush_every = max(50, batch_size // 5)

    def _emit(payload: dict[str, Any]) -> None:
        if on_progress:
            try:
                on_progress(payload)
            except Exception:  # noqa: BLE001
                logger.debug("on_progress failed", exc_info=True)

    try:
        if reset:
            neo4j.wipe()
            clear_checkpoint()

        neo4j.schema_init()
        ref_data = load_reference_data()
        create_repository_node(neo4j)
        neo4j.flush()
        last_index = load_checkpoint()
        ref_data.timeline_index = build_timeline_index(UNIFIED_TIMELINE_PATH)

        processed = 0
        skipped = 0
        agentic_count = 0
        agentic_failed = 0
        start_time = time.time()

        pending_agentic: list[dict] = []
        workers = max(1, int(config.GEMINI_MAX_CONCURRENCY))

        def _flush_agentic(batch: list[dict]) -> None:
            nonlocal agentic_count, agentic_failed
            if not batch:
                return
            from layerten.process.agent import agentic_extract

            neo4j.flush()
            neo4j.enable_batching(False)
            pool = ThreadPoolExecutor(max_workers=workers)
            try:
                futures = {
                    pool.submit(agentic_extract, ev, neo4j, ref_data): ev
                    for ev in batch
                }
                # An unbounded as_completed() lets a single wedged worker stall
                # the entire run. Bound the batch so progress is always made and
                # the stragglers are reported instead of hanging silently.
                budget = config.AGENTIC_BATCH_TIMEOUT_S
                try:
                    for fut in as_completed(futures, timeout=budget):
                        ev = futures[fut]
                        try:
                            fut.result()
                            agentic_count += 1
                        except Exception as e:  # noqa: BLE001
                            agentic_failed += 1
                            logger.error(
                                "Agentic extraction failed for %s: %s",
                                ev.get("natural_key"),
                                e,
                            )
                except FuturesTimeoutError:
                    unfinished = [
                        ev.get("natural_key")
                        for fut, ev in futures.items()
                        if not fut.done()
                    ]
                    agentic_failed += len(unfinished)
                    logger.error(
                        "Agentic batch exceeded %.0fs with %d unfinished events: %s",
                        budget,
                        len(unfinished),
                        unfinished[:10],
                    )
                    for fut in futures:
                        fut.cancel()
            finally:
                pool.shutdown(wait=False, cancel_futures=True)
                neo4j.enable_batching(True)

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
                pending_agentic.append(event)
                if len(pending_agentic) >= workers:
                    _flush_agentic(pending_agentic)
                    pending_agentic = []
            elif processed > 0 and processed % flush_every == 0:
                neo4j.flush()

            save_checkpoint(idx)
            processed += 1

            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            _emit(
                {
                    "stage": "process",
                    "processed": processed,
                    "skipped": skipped,
                    "agentic_ok": agentic_count,
                    "agentic_failed": agentic_failed,
                    "rate_per_sec": round(rate, 2),
                    "elapsed_s": round(elapsed, 1),
                    "last_index": idx,
                }
            )

            if processed % 100 == 0:
                logger.info(
                    "Progress: %d events processed (%.1f events/sec), %d agentic",
                    processed,
                    rate,
                    agentic_count,
                )

        neo4j.flush()
        _flush_agentic(pending_agentic)
        neo4j.flush()

        elapsed = time.time() - start_time
        logger.info(
            "Processing complete: %d events in %.1fs (skipped %d, agentic %d, failed %d)",
            processed,
            elapsed,
            skipped,
            agentic_count,
            agentic_failed,
        )
        _emit(
            {
                "stage": "process",
                "processed": processed,
                "skipped": skipped,
                "agentic_ok": agentic_count,
                "agentic_failed": agentic_failed,
                "rate_per_sec": round(processed / elapsed, 2) if elapsed else 0,
                "elapsed_s": round(elapsed, 1),
                "done": True,
            }
        )
        return {
            "processed": processed,
            "skipped": skipped,
            "agentic_ok": agentic_count,
            "agentic_failed": agentic_failed,
            "elapsed_s": round(elapsed, 1),
        }

    finally:
        try:
            neo4j.flush()
        finally:
            neo4j.close()
