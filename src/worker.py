from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import yaml
from pydantic import BaseModel, Field

from src.store import JobStore
from src.termgame.topup import execute_topup_unit


class SessionPayload(BaseModel):
    cookies: dict[str, str]
    headers: dict[str, str]
    otpSecret: str
    cookieHeader: str | None = None


class CreateOrderPayload(BaseModel):
    partnerReferenceId: str
    gameKey: str
    playerId: str
    itemId: str
    quantity: int = Field(default=1, ge=1, le=20)
    session: SessionPayload


GAMES = yaml.safe_load((Path(__file__).resolve().parents[1] / "games.yaml").read_text())
STORE = JobStore(Path(__file__).resolve().parents[1] / "data" / "jobs.db")


async def process_job(job_ref: str) -> None:
    job = STORE.get_by_ref(job_ref)
    if not job:
        return

    payload = CreateOrderPayload.model_validate(job.payload)
    game = GAMES.get(payload.gameKey)
    if not game:
        STORE.update_job(job_ref, status="failed", completed_units=0, failure_reason="unknown_game")
        return

    STORE.update_job(job_ref, status="processing", completed_units=job.completed_units)
    completed = 0
    last_display: str | None = None

    merchant_uid_raw = os.environ.get("GARENA_MERCHANT_UID", "").strip()
    merchant_uid = int(merchant_uid_raw) if merchant_uid_raw.isdigit() else None

    for _ in range(payload.quantity):
        result = await execute_topup_unit(
            app_id=int(game["app_id"]),
            channel_id=int(game["channel_id"]),
            packed_role_id=game.get("packed_role_id"),
            item_id=payload.itemId,
            player_id=payload.playerId,
            cookies=payload.session.cookies,
            headers=payload.session.headers,
            otp_secret=payload.session.otpSecret,
            needs_otp=bool(game.get("needs_otp", False)),
            garena_uid=merchant_uid,
            cookie_header=payload.session.cookieHeader,
        )
        if not result.ok:
            STORE.update_job(
                job_ref,
                status="failed",
                completed_units=completed,
                display_id=last_display,
                failure_reason=result.failure_reason,
            )
            await maybe_webhook(job_ref)
            return
        completed += 1
        last_display = result.display_id
        if completed < payload.quantity:
            await asyncio.sleep(3)

    STORE.update_job(
        job_ref,
        status="delivered",
        completed_units=completed,
        display_id=last_display,
        failure_reason=None,
    )
    await maybe_webhook(job_ref)


async def maybe_webhook(job_ref: str) -> None:
    base = os.environ.get("EROSTERZ_WEBHOOK_BASE", "").strip().rstrip("/")
    secret = os.environ.get("GARENA_WEBHOOK_SECRET", "").strip()
    if not base or not secret:
        return

    job = STORE.get_by_ref(job_ref)
    if not job:
        return

    body = {
        "ok": True,
        "ref": job.ref,
        "partnerReferenceId": job.partner_reference_id,
        "status": job.status,
        "progress": {"completedUnits": job.completed_units, "totalUnits": job.total_units},
        "displayId": job.display_id,
        "failureReason": job.failure_reason,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{base}/api/webhooks/garena",
                json=body,
                headers={"x-garena-webhook-secret": secret},
            )
    except Exception:
        pass


async def worker_loop() -> None:
    while True:
        for job in STORE.list_accepted():
            try:
                await process_job(job.ref)
            except Exception as exc:
                # A single job's unexpected failure must never take the whole
                # background loop down with it -- that would silently stop
                # *all* future orders until a manual service restart.
                STORE.update_job(
                    job.ref,
                    status="failed",
                    completed_units=0,
                    failure_reason=f"worker_error: {str(exc)[:150]}",
                )
        await asyncio.sleep(2)
