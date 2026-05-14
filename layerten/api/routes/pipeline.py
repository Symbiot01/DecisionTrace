"""Pipeline job API: start/poll GitHub → Neo4j processing."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from layerten.api.pipeline_jobs import (
    PipelineConflictError,
    PipelineJobCreate,
    PipelineJobStatus,
    PipelineValidationError,
    get_job,
    start_job,
)

router = APIRouter()


@router.post("/pipeline/jobs")
async def create_job(body: PipelineJobCreate) -> dict:
    try:
        job_id = await start_job(body)
    except PipelineValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PipelineConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.get("/pipeline/jobs/{job_id}", response_model=PipelineJobStatus)
async def read_job(job_id: str) -> PipelineJobStatus:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
