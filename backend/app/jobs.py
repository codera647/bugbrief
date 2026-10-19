import asyncio
import hashlib
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from uuid import uuid4

from pydantic import ValidationError

from .domain import Ticket, digest
from .errors import AppError
from .quality import review_findings


@dataclass
class Job:
    id: str
    user_id: str
    workspace_id: str
    report: str
    operation_id: str
    status: str = "queued"
    created: float = field(default_factory=time.monotonic)
    finished: float | None = None
    payload: Ticket | None = None
    error: dict | None = None
    checks: dict | None = None
    generation_metadata: dict = field(default_factory=dict)
    cancel: threading.Event = field(default_factory=threading.Event)
    report_digest: str = field(init=False)

    def __post_init__(self):
        self.report_digest = hashlib.sha256(self.report.encode()).hexdigest()


class JobManager:
    def __init__(self, generator):
        self.generator = generator
        self.jobs: dict[str, Job] = {}
        self.queue = asyncio.Queue(maxsize=4)
        self.rates = defaultdict(deque)
        self.receipts: dict[str, tuple[str, str, str, float]] = {}
        self.worker = None
        self.cleaner = None

    def start(self):
        self.worker = asyncio.create_task(self.run())
        self.cleaner = asyncio.create_task(self.sweep())

    def clean(self):
        current = time.monotonic()
        for key, job in list(self.jobs.items()):
            if job.finished is not None and current - job.finished > 900:
                del self.jobs[key]
        for key, receipt in list(self.receipts.items()):
            if receipt[3] < current:
                del self.receipts[key]
        for key, values in list(self.rates.items()):
            while values and current - values[0] > 600:
                values.popleft()
            if not values:
                del self.rates[key]

    async def sweep(self):
        while True:
            await asyncio.sleep(30)
            self.clean()

    def submit(self, member, report, operation_id):
        self.clean()
        for job in self.jobs.values():
            if (job.user_id, job.workspace_id, job.operation_id) == (member.user_id, member.workspace_id, operation_id):
                if job.report_digest != hashlib.sha256(report.encode()).hexdigest():
                    raise AppError(409, "operation_conflict", "This operation was already used for another report.")
                return job
        self.generator.validate_input(report)
        if any(j.user_id == member.user_id and j.status in {"queued", "running", "cancel_requested"} for j in self.jobs.values()):
            raise AppError(429, "job_in_progress", "You already have a report being prepared.")
        if self.queue.full():
            raise AppError(429, "queue_full", "The pilot is busy. Try again shortly.")
        if len(self.rates[member.user_id]) >= 5:
            raise AppError(429, "rate_limited", "You have drafted several reports recently. Try again in a few minutes.")
        self.rates[member.user_id].append(time.monotonic())
        job = Job(str(uuid4()), member.user_id, member.workspace_id, report, operation_id)
        self.jobs[job.id] = job
        self.queue.put_nowait(job)
        return job

    def get(self, member, job_id):
        self.clean()
        job = self.jobs.get(job_id)
        if not job or (job.user_id, job.workspace_id) != (member.user_id, member.workspace_id):
            raise AppError(404, "job_not_found", "This draft session is no longer available. Paste the report again.")
        return job

    def result(self, member, job_id):
        job = self.get(member, job_id)
        if job.status != "succeeded" or job.payload is None:
            raise AppError(409, "draft_not_ready", "Wait for a valid draft before saving or reviewing.")
        return job

    def cancel_job(self, member, job_id):
        job = self.get(member, job_id)
        if job.status in {"queued", "running"}:
            job.cancel.set()
            if job.status == "queued":
                job.status, job.finished, job.report = "cancelled", time.monotonic(), ""
                pending = []
                while not self.queue.empty():
                    item = self.queue.get_nowait()
                    self.queue.task_done()
                    if item.id != job.id:
                        pending.append(item)
                for item in pending:
                    self.queue.put_nowait(item)
            else:
                job.status = "cancel_requested"
        return job

    def review(self, member, payload, job_id):
        job = self.result(member, job_id)
        payload.check_source(job.report)
        receipt_id = str(uuid4())
        expiry = min(time.monotonic() + 900, job.finished + 900)
        self.receipts[receipt_id] = (member.user_id, member.workspace_id, digest(payload), expiry)
        return receipt_id

    def check_receipt(self, member, receipt_id, payload):
        self.clean()
        receipt = self.receipts.get(receipt_id)
        if not receipt or receipt[:3] != (member.user_id, member.workspace_id, digest(payload)):
            raise AppError(409, "review_required", "Review the current ticket before exporting it.")

    def view(self, job):
        return {"id": job.id, "status": job.status, "payload": job.payload.model_dump() if job.payload else None, "error": job.error, "checks": job.checks, "generation_metadata": job.generation_metadata or self.generator.metadata}

    async def run(self):
        while True:
            job = await self.queue.get()
            try:
                if job.cancel.is_set():
                    continue
                if time.monotonic() - job.created > 720:
                    raise AppError(504, "queue_expired", "The waiting limit was reached. Your report is still in the editor.")
                job.status = "running"
                candidate = await asyncio.to_thread(self.generator.generate, job.report, job.cancel)
                candidate.check_source(job.report)
                if job.cancel.is_set():
                    job.status, job.report = "cancelled", ""
                else:
                    job.payload, job.status = candidate, "succeeded"
                    job.checks = review_findings(candidate, job.report)
                    job.generation_metadata = dict(self.generator.metadata)
            except AppError as error:
                job.status = "cancelled" if error.code == "cancelled" else "failed"
                job.error = {"code": error.code, "message": error.message}
                job.report = ""
            except (ValidationError, ValueError):
                job.status, job.report = "failed", ""
                job.error = {"code": "invalid_model_output", "message": "We couldn't produce a valid ticket. Your report is still here."}
            except Exception as error:
                # Never return provider traces, model text, or a usable placeholder on failure.
                logging.getLogger(__name__).error("Generation failed: %s", type(error).__name__)
                job.status, job.report = "failed", ""
                job.error = {"code": "generation_failed", "message": "Ticket drafting failed. Your report is still here."}
            finally:
                job.finished = time.monotonic()
                self.queue.task_done()

    async def close(self):
        for job in self.jobs.values():
            job.cancel.set()
        for task in (self.worker, self.cleaner):
            if task:
                task.cancel()
        await asyncio.gather(*(t for t in (self.worker, self.cleaner) if t), return_exceptions=True)
