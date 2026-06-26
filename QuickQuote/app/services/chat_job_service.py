import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from app.db.session import AsyncSessionLocal
from app.services.chat_stream_service import parse_bool_flag, sse_event
from app.workflow.graph import valuation_workflow

logger = logging.getLogger(__name__)


@dataclass
class QuoteJob:
    job_id: str
    payload: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    events: list[str] = field(default_factory=list)
    done: bool = False
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)


class ChatJobService:
    def __init__(self) -> None:
        self._jobs: dict[str, QuoteJob] = {}
        self._lock = asyncio.Lock()
        self._ttl_seconds = 30 * 60

    async def create_job(self, payload: dict[str, Any]) -> str:
        await self._cleanup_jobs()
        job_id = str(uuid.uuid4())
        job = QuoteJob(job_id=job_id, payload=payload)
        async with self._lock:
            self._jobs[job_id] = job
        logger.info(
            "[chat_job] JOB CREATED | job_id=%s | input_chars=%s | excel_rows_count=%s | images_count=%s | raw_files_count=%s",
            job_id,
            len(str(payload.get("input_text", "") or "")),
            len(payload.get("excel_rows", []) or []),
            len(payload.get("images", []) or []),
            len(payload.get("raw_files", []) or []),
        )
        asyncio.create_task(self._run_job(job))
        return job_id

    async def stream_job(self, job_id: str) -> AsyncGenerator[str, None]:
        job = await self.get_job(job_id)
        if job is None:
            yield sse_event("error", {"message": "job_id 不存在或已过期"})
            return

        cursor = 0
        while True:
            async with job.condition:
                while cursor >= len(job.events) and not job.done:
                    await job.condition.wait()
                batch = job.events[cursor:]
                cursor = len(job.events)
                done = job.done
            for event in batch:
                yield event
            if done:
                break

    async def get_job(self, job_id: str) -> QuoteJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def _run_job(self, job: QuoteJob) -> None:
        start_at = time.perf_counter()
        logger.info("[chat_job] JOB RUNNING | job_id=%s", job.job_id)
        await self._append(job, "job", {"job_id": job.job_id, "status": "running"})
        try:
            async with AsyncSessionLocal() as session:
                async for event in valuation_workflow.stream_multimodal_events(
                    session=session,
                    input_text=job.payload["input_text"],
                    excel_rows=job.payload["excel_rows"],
                    enable_fuzzy_code_match=parse_bool_flag(job.payload.get("enable_fuzzy_code_match", False)),
                    images=job.payload["images"],
                    raw_files=job.payload["raw_files"],
                ):
                    await self._append(job, event["event"], event["data"])
        except Exception as exc:
            detail = str(exc).strip() or repr(exc)
            logger.exception("[chat_job] JOB FAILED | job_id=%s | error=%s", job.job_id, detail)
            await self._append(job, "error", {"message": f"job 执行失败: {detail}"})
        finally:
            await self._append(job, "job", {"job_id": job.job_id, "status": "done"})
            logger.info(
                "[chat_job] JOB DONE | job_id=%s | elapsed_ms=%s | events_count=%s",
                job.job_id,
                int((time.perf_counter() - start_at) * 1000),
                len(job.events),
            )
            async with job.condition:
                job.done = True
                job.condition.notify_all()

    async def _append(self, job: QuoteJob, event: str, data: dict[str, Any]) -> None:
        async with job.condition:
            job.events.append(sse_event(event, data))
            job.condition.notify_all()

    async def _cleanup_jobs(self) -> None:
        cutoff = time.time() - self._ttl_seconds
        async with self._lock:
            expired = [job_id for job_id, job in self._jobs.items() if job.done and job.created_at < cutoff]
            for job_id in expired:
                self._jobs.pop(job_id, None)


chat_job_service = ChatJobService()
