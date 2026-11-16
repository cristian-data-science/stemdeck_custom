"""Settings › Storage: what the songs take on disk, cleaning up the Pianoteq
renders (they are made again from the notes), and what is rendered in the
background for every score (app/score/storage.py).

GET  /storage              every song's size by kind, totals, the folder, the disk
POST /storage/clean        delete what is made again: {"what": cache|slow|hands|old|pianoteq, "jobs": [...] | null}
PUT  /storage/background   {"value": all|hands|main|off}
"""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.config import JOB_ID_RE
from app.core.settings import get_pianoteq_background, set_pianoteq_background
from app.score import storage

router = APIRouter()


def _jobs(ids: list[str] | None = None):
    from app.core.registry import all_jobs

    out = []
    for job_id, job in all_jobs().items():
        if job.status != "done" or not JOB_ID_RE.match(job_id):
            continue
        if ids is not None and job_id not in ids:
            continue
        out.append(job)
    return out


def _current(job, stem, keys=True):
    from app.api.score import pt_current

    return pt_current(job, stem, keys)


@router.get("")
async def get_storage() -> JSONResponse:
    data = await asyncio.to_thread(storage.usage, _jobs(), _current)
    data["background"] = get_pianoteq_background()
    return JSONResponse(data)


class CleanBody(BaseModel):
    what: Literal["cache", "slow", "hands", "old", "pianoteq"]
    jobs: list[str] | None = Field(default=None, max_length=10000)


@router.post("/clean")
async def clean_storage(body: CleanBody) -> JSONResponse:
    jobs = _jobs(body.jobs)
    if body.jobs is not None and not jobs:
        raise HTTPException(status_code=404, detail="no such songs")
    return JSONResponse(await asyncio.to_thread(storage.clean, jobs, body.what, _current))


class BackgroundBody(BaseModel):
    value: Literal["all", "hands", "main", "off"]


@router.put("/background")
async def put_background(body: BackgroundBody) -> JSONResponse:
    value = set_pianoteq_background(body.value)
    # More asked for than before: what is missing is made now, in the background.
    if value != "off":
        from app.api.score import pianoteq_sweep

        await asyncio.to_thread(pianoteq_sweep)
    return JSONResponse({"background": value})
