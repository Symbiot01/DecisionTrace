"""
Background pipeline jobs: fetch → merge → sort → process with live metrics.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from layerten import config

logger = logging.getLogger(__name__)

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_jobs: Dict[str, "PipelineJobStatus"] = {}
_active_job_id: Optional[str] = None
_lock = asyncio.Lock()


class PipelineValidationError(ValueError):
    pass


class PipelineConflictError(RuntimeError):
    pass


class PipelineMetrics(BaseModel):
    stage_detail: str = ""
    events_processed: int = 0
    events_skipped: int = 0
    agentic_ok: int = 0
    agentic_failed: int = 0
    rate_per_sec: float = 0.0
    elapsed_s: float = 0.0


class PipelineJobStatus(BaseModel):
    job_id: str
    repo: str
    status: str  # queued|fetching|merging|sorting|processing|completed|failed
    stage: str
    progress_pct: float = 0.0
    metrics: PipelineMetrics = Field(default_factory=PipelineMetrics)
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)


class PipelineJobCreate(BaseModel):
    repo_url: str
    full: bool = Field(
        True,
        description="If true run fetch+merge+sort+process; if false process-only",
    )
    max_events: Optional[int] = Field(None, ge=1, le=50000)
    skip_agentic: bool = False
    reset: bool = False


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    for secret in (
        config.GEMINI_API_KEY,
        config.NEO4J_PASSWORD,
        config.GITHUB_TOKEN,
        config.OPENROUTER_API_KEY,
    ):
        if secret and secret in text:
            text = text.replace(secret, "[REDACTED]")
    return text[:500]


def parse_github_repo(repo_url: str) -> Tuple[str, str]:
    raw = (repo_url or "").strip()
    if not raw:
        raise PipelineValidationError("repo_url is required")
    if _REPO_RE.match(raw):
        owner, name = raw.split("/", 1)
        return owner, name
    if "://" not in raw:
        raw = "https://" + raw.lstrip("/")
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in ("github.com", "www.github.com"):
        raise PipelineValidationError("Only github.com URLs are allowed")
    parts = [p for p in (parsed.path or "").split("/") if p]
    if len(parts) < 2:
        raise PipelineValidationError("URL must include owner/repo")
    owner, name = parts[0], parts[1]
    if name.endswith(".git"):
        name = name[:-4]
    if not _REPO_RE.match(f"{owner}/{name}"):
        raise PipelineValidationError("Invalid owner/repository")
    return owner, name


def get_job(job_id: str) -> Optional[PipelineJobStatus]:
    return _jobs.get(job_id)


def _set_progress(job: PipelineJobStatus, pct: float) -> None:
    job.progress_pct = max(0.0, min(100.0, pct))


async def start_job(body: PipelineJobCreate) -> str:
    owner, name = parse_github_repo(body.repo_url)
    if not config.GITHUB_TOKEN and body.full:
        raise PipelineValidationError("GITHUB_TOKEN is required for fetch")
    if not config.GEMINI_API_KEY and not body.skip_agentic:
        raise PipelineValidationError("GEMINI_API_KEY is required for agentic process")
    if not (config.NEO4J_URI and config.NEO4J_USERNAME and config.NEO4J_PASSWORD):
        raise PipelineValidationError("Neo4j Aura credentials are not configured")

    async with _lock:
        global _active_job_id
        if _active_job_id and _active_job_id in _jobs:
            active = _jobs[_active_job_id]
            if active.status not in ("completed", "failed"):
                raise PipelineConflictError(
                    f"Job already running: {active.job_id} ({active.repo})"
                )
        job_id = str(uuid.uuid4())
        job = PipelineJobStatus(
            job_id=job_id,
            repo=f"{owner}/{name}",
            status="queued",
            stage="queued",
            started_at=_now(),
        )
        _jobs[job_id] = job
        _active_job_id = job_id

    asyncio.create_task(_run_job(job_id, owner, name, body))
    return job_id


async def _run_job(
    job_id: str,
    owner: str,
    name: str,
    body: PipelineJobCreate,
) -> None:
    job = _jobs[job_id]
    t0 = time.monotonic()

    def elapsed() -> float:
        return round(time.monotonic() - t0, 1)

    try:
        config.set_target_repo(owner, name)

        if body.full:
            job.status = "fetching"
            job.stage = "fetch"
            _set_progress(job, 5)
            job.metrics.elapsed_s = elapsed()
            await asyncio.to_thread(_run_fetch)

            job.status = "merging"
            job.stage = "merge"
            _set_progress(job, 35)
            job.metrics.elapsed_s = elapsed()
            await asyncio.to_thread(_run_merge)

            job.status = "sorting"
            job.stage = "sort"
            _set_progress(job, 50)
            job.metrics.elapsed_s = elapsed()
            await asyncio.to_thread(_run_sort)

        job.status = "processing"
        job.stage = "process"
        _set_progress(job, 55)
        job.metrics.elapsed_s = elapsed()

        def on_progress(payload: dict) -> None:
            job.metrics.stage_detail = payload.get("stage", "process")
            job.metrics.events_processed = int(payload.get("processed") or 0)
            job.metrics.events_skipped = int(payload.get("skipped") or 0)
            job.metrics.agentic_ok = int(payload.get("agentic_ok") or 0)
            job.metrics.agentic_failed = int(payload.get("agentic_failed") or 0)
            job.metrics.rate_per_sec = float(payload.get("rate_per_sec") or 0)
            job.metrics.elapsed_s = elapsed()
            # Map process progress into 55–95%
            done = job.metrics.events_processed
            # Without known total, asymptotic approach to 95
            pct = 55 + min(40.0, done * 0.05)
            if payload.get("done"):
                pct = 95
            _set_progress(job, pct)

        result = await asyncio.to_thread(
            _run_process,
            body.max_events,
            body.skip_agentic,
            body.reset,
            on_progress,
        )
        job.result = result or {}
        job.status = "completed"
        job.stage = "done"
        _set_progress(job, 100)
        job.finished_at = _now()
        job.metrics.elapsed_s = elapsed()
        logger.info("pipeline job %s completed for %s/%s", job_id, owner, name)

    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = _sanitize(exc)
        job.finished_at = _now()
        job.metrics.elapsed_s = elapsed()
        logger.error("pipeline job %s failed: %s", job_id, job.error)


def _run_fetch() -> None:
    from layerten.fetch.bootstrap import run_bootstrap

    run_bootstrap()


def _run_merge() -> None:
    from layerten.merge.runner import run_merge

    run_merge()


def _run_sort() -> None:
    from layerten.sort.timeline import run_sort

    run_sort()


def _run_process(
    max_events: Optional[int],
    skip_agentic: bool,
    reset: bool,
    on_progress,
) -> dict:
    from layerten.process.orchestrator import run_processing

    return run_processing(
        limit=max_events,
        skip_agentic=skip_agentic,
        reset=reset,
        on_progress=on_progress,
    ) or {}
