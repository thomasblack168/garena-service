import asyncio

from src.store import JobStore
from src.worker import worker_loop


def test_worker_loop_survives_process_job_exception(tmp_path, monkeypatch):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_job("ref-1", {"gameKey": "test"}, 1)

    monkeypatch.setattr("src.worker.STORE", store)

    call_count = {"n": 0}

    async def exploding_process_job(job_ref):
        call_count["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr("src.worker.process_job", exploding_process_job)

    async def run_briefly():
        try:
            await asyncio.wait_for(worker_loop(), timeout=0.3)
        except asyncio.TimeoutError:
            pass

    asyncio.run(run_briefly())

    # The loop must survive an exception from a single job instead of dying
    # silently (which would stop *all* future orders until a manual
    # service restart), and the job must be marked failed instead of
    # staying stuck in "accepted" forever.
    assert call_count["n"] >= 1
    updated = store.get_by_ref(job.ref)
    assert updated.status == "failed"
    assert "boom" in (updated.failure_reason or "")
