from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from src.store import DuplicateJobError, JobStore
from src.termgame.http import summarize_raw
from src.termgame.session import probe_termgame_session
from src.worker import CreateOrderPayload, SessionPayload, worker_loop

GAMES = yaml.safe_load((Path(__file__).resolve().parents[1] / "games.yaml").read_text())
STORE = JobStore(Path(__file__).resolve().parents[1] / "data" / "jobs.db")


def require_bearer(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("GARENA_SERVICE_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="Service API key not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


class HealthBody(BaseModel):
    session: SessionPayload | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    task = asyncio.create_task(worker_loop())
    yield
    task.cancel()


app = FastAPI(title="Garena Service", lifespan=lifespan)


@app.get("/v1/health")
async def health_get(_: None = Depends(require_bearer)):
    return {"ok": True, "sessionProvided": False, "shellBalance": None}


@app.post("/v1/health")
async def health_post(body: HealthBody, _: None = Depends(require_bearer)):
    if body.session is None:
        return {
            "ok": True,
            "sessionProvided": False,
            "sessionValid": None,
            "sessionExpired": None,
            "shellBalance": None,
        }

    probe = await probe_termgame_session(
        cookies=body.session.cookies,
        headers=body.session.headers,
        cookie_header=body.session.cookieHeader,
        otp_secret=body.session.otpSecret,
    )
    return {
        "ok": True,
        "sessionProvided": True,
        "sessionValid": probe.session_valid,
        "sessionExpired": probe.session_expired,
        "shellBalance": probe.shell_balance,
        "probeDetail": summarize_raw(probe.raw),
    }


@app.post("/v1/orders", status_code=202)
async def create_order(body: CreateOrderPayload, _: None = Depends(require_bearer)):
    if body.gameKey not in GAMES:
        raise HTTPException(status_code=400, detail=f"Unknown gameKey: {body.gameKey}")

    try:
        job = STORE.create_job(
            body.partnerReferenceId,
            body.model_dump(),
            body.quantity,
        )
    except DuplicateJobError as exc:
        raise HTTPException(status_code=409, detail={"ref": exc.ref}) from exc

    return {
        "ok": True,
        "ref": job.ref,
        "status": job.status,
        "partnerReferenceId": job.partner_reference_id,
    }


@app.get("/v1/orders/{ref}")
async def get_order(ref: str, _: None = Depends(require_bearer)):
    job = STORE.get_by_ref(ref)
    if not job:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "ok": True,
        "ref": job.ref,
        "partnerReferenceId": job.partner_reference_id,
        "status": job.status,
        "progress": {"completedUnits": job.completed_units, "totalUnits": job.total_units},
        "displayId": job.display_id,
        "failureReason": job.failure_reason,
    }
