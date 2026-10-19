import asyncio
import threading
from dataclasses import replace
from uuid import uuid4

import pytest

from app.auth import DEMO_WORKSPACE, Membership
from app.domain import Ticket
from app.errors import AppError
from app.inference import examples
from app.jobs import JobManager


def test_bounded_queue_cancellation_and_operation_binding():
    class BlockingGenerator:
        metadata = {"provider": "test"}
        entered = threading.Event()
        release = threading.Event()

        def validate_input(self, report): pass

        def generate(self, report, cancel):
            self.entered.set()
            assert self.release.wait(2), "test generator was not released"
            return Ticket.model_validate(examples()[0]["ticket"])

    async def scenario():
        model = BlockingGenerator(); manager = JobManager(model); manager.start()
        members = [Membership(str(uuid4()), DEMO_WORKSPACE, "contributor", "LedgerFlow") for _ in range(7)]
        report = examples()[0]["report"]
        first = manager.submit(members[0], report, str(uuid4()))
        assert await asyncio.to_thread(model.entered.wait, 2)
        with pytest.raises(AppError, match="already have"):
            manager.submit(members[0], report, str(uuid4()))
        waiting = [manager.submit(member, report, str(uuid4())) for member in members[1:5]]
        with pytest.raises(AppError, match="busy"):
            manager.submit(members[5], report, str(uuid4()))
        manager.cancel_job(members[1], waiting[0].id)
        assert manager.queue.qsize() == 3 and waiting[0].report == ""
        # Even after source deletion, an operation cannot be reused for a different report.
        with pytest.raises(AppError, match="another report"):
            manager.submit(members[1], report + " Different.", waiting[0].operation_id)
        replacement = manager.submit(members[5], report, str(uuid4()))
        assert manager.submit(members[5], report, replacement.operation_id).id == replacement.id
        with pytest.raises(AppError): manager.get(replace(members[5], workspace_id=str(uuid4())), replacement.id)
        manager.cancel_job(members[0], first.id)
        model.release.set()
        await asyncio.wait_for(manager.queue.join(), 3)
        assert first.status == "cancelled" and first.payload is None and first.report == ""
        assert replacement.status == "succeeded"
        assert all(job.status in {"succeeded", "cancelled"} for job in manager.jobs.values())
        await manager.close()

    asyncio.run(scenario())
