from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.models.facts import SourceFacts
from app.models.job import Job, JobState
from app.pipeline.orchestrator import Pipeline, new_job
from app.storage.db import JobStore

router = APIRouter()


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_facts: SourceFacts
    force_regenerate: bool = False


class JobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: Job


class JobListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[Job]


def _job_store(request: Request) -> JobStore:
    return request.app.state.job_store


def _pipeline(request: Request) -> Pipeline:
    return request.app.state.pipeline


@router.post("/episodes", response_model=JobResponse)
async def start_or_retry_generation(
    body: GenerateRequest, request: Request, background_tasks: BackgroundTasks
) -> JobResponse:
    """Start generation for an episode, or return the in-flight/completed job
    for that date instead of duplicating paid work - unless force_regenerate.
    """
    job_store = _job_store(request)
    pipeline = _pipeline(request)

    if not body.force_regenerate:
        existing = await asyncio.to_thread(
            job_store.latest_for_date, body.source_facts.episode_date.isoformat()
        )
        if existing and existing.state in (JobState.pending, JobState.running, JobState.completed):
            return JobResponse(job=existing)

    job = new_job(body.source_facts, force_regenerate=body.force_regenerate)
    await asyncio.to_thread(job_store.save, job)
    background_tasks.add_task(pipeline.run, job)
    return JobResponse(job=job)


@router.get("/episodes", response_model=JobListResponse)
async def list_jobs(request: Request, limit: int = 50) -> JobListResponse:
    """List recent jobs, newest first, without triggering generation."""
    job_store = _job_store(request)
    jobs = await asyncio.to_thread(job_store.list_recent, limit)
    return JobListResponse(jobs=jobs)


@router.get("/episodes/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str, request: Request) -> JobResponse:
    job_store = _job_store(request)
    job = await asyncio.to_thread(job_store.get, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job with id {job_id!r}")
    return JobResponse(job=job)


@router.get("/episodes/by-date/{episode_date}", response_model=JobResponse)
async def get_latest_job_for_date(episode_date: str, request: Request) -> JobResponse:
    job_store = _job_store(request)
    job = await asyncio.to_thread(job_store.latest_for_date, episode_date)
    if job is None:
        raise HTTPException(status_code=404, detail=f"no job for date {episode_date!r}")
    return JobResponse(job=job)


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
