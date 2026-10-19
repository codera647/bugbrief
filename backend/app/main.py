import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .auth import Authenticator, Identity, Membership
from .config import Settings
from .domain import DraftChecksRequest, GenerateRequest, RevisionRequest, SaveRequest, SessionExportRequest, SessionReviewRequest, Ticket, UpdateRequest, export_text, uuid_string
from .errors import AppError
from .inference import examples, make_generator
from .jobs import JobManager
from .repository import SQLiteRepository, SupabaseRepository
from .quality import review_findings


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in {"POST", "PATCH", "PUT"}:
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 16384:
                return await JSONResponse({"error": {"code": "body_too_large", "message": "Shorten this report or ticket before submitting it.", "request_id": str(uuid4())}}, status_code=413)(scope, receive, send)
            if not message.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


def create_app(settings: Settings | None = None, repository=None, generator=None, authenticator=None):
    settings = settings or Settings.load()
    repo = repository or (SQLiteRepository(settings.database) if settings.mode == "demo" else SupabaseRepository(settings))
    auth = authenticator or Authenticator(settings)
    model = generator or make_generator(settings)
    jobs = JobManager(model)

    @asynccontextmanager
    async def lifespan(app):
        async def load_model():
            try:
                await asyncio.to_thread(model.load)
            except Exception:
                # The runtime records a sanitized startup state and logs the local cause.
                logging.getLogger(__name__).error("Drafting unavailable: model initialization failed")
        loading = asyncio.create_task(load_model()) if hasattr(model, "load") and not model.ready else None
        jobs.start()
        try:
            yield
        finally:
            await jobs.close()
            if loading:
                loading.cancel()
                await asyncio.gather(loading, return_exceptions=True)
            await repo.close()

    app = FastAPI(title="BugBrief API", version="0.1.0", lifespan=lifespan, docs_url="/docs" if settings.mode == "demo" else None, redoc_url=None)
    app.state.jobs = jobs
    app.state.repository = repo
    app.state.model = model
    app.add_middleware(BodyLimit)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.origins), allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"], expose_headers=["Retry-After"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AppError)
    async def error_handler(request, error):
        headers = {"Retry-After": "30"} if error.status == 429 else None
        return JSONResponse({"error": {"code": error.code, "message": error.message, "request_id": request.state.request_id}}, status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request, error):
        problems = [{"field": ".".join(str(s) for s in e["loc"] if s != "body"), "message": e["msg"]} for e in error.errors()]
        return JSONResponse({"error": {"code": "invalid_input", "message": "Check the ticket fields and try again.", "details": problems, "request_id": request.state.request_id}}, status_code=422)

    async def identity(request: Request):
        return await auth.identify(request)

    async def member(workspace_id: str, who: Annotated[Identity, Depends(identity)]):
        try:
            wid = uuid_string(workspace_id)
        except ValueError:
            raise AppError(404, "workspace_not_found", "This workspace is not available.") from None
        memberships = await repo.memberships(who)
        found = next((m for m in memberships if m.workspace_id == wid), None)
        if not found:
            raise AppError(403, "access_not_granted", "Your account does not have access to this workspace.")
        return found

    Member = Annotated[Membership, Depends(member)]

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready():
        return JSONResponse({"status": "ready" if model.ready else "model_" + getattr(model, "state", "not_configured")}, status_code=200 if model.ready else 503)

    @app.get("/v1/config")
    async def config():
        public_metadata = {key: model.metadata[key] for key in ("provider", "trained", "schema_version", "profile", "pipeline_version", "experimental", "constrained_output") if key in model.metadata}
        public_metadata["state"] = "ready" if model.ready else getattr(model, "state", "not_configured")
        return {"mode": settings.mode, "inference": public_metadata, "drafting_available": model.ready}

    @app.get("/v1/examples")
    async def example_list():
        return [{"id": r["id"], "label": r["label"], "report": r["report"]} for r in examples()]

    @app.get("/v1/session")
    async def session(who: Annotated[Identity, Depends(identity)]):
        memberships = await repo.memberships(who)
        if not memberships:
            raise AppError(403, "access_not_granted", "Your account does not have access to this workspace.")
        return {"user_id": who.user_id, "workspaces": [{"id": m.workspace_id, "name": m.name, "role": m.role} for m in memberships]}

    prefix = "/v1/workspaces/{workspace_id}"

    @app.post(prefix + "/draft-checks")
    async def draft_checks(body: DraftChecksRequest, m: Member):
        source = jobs.result(m, body.job_id).report if body.job_id else (await repo.get(m, body.ticket_id))["source_report"]
        try:
            body.payload.check_source(source)
        except ValueError as error:
            raise AppError(422, "invalid_evidence", str(error)) from None
        return review_findings(body.payload, source)

    @app.post(prefix + "/generation-jobs", status_code=202)
    async def generate(body: GenerateRequest, m: Member):
        m.require_edit()
        return jobs.view(jobs.submit(m, body.report, body.operation_id))

    @app.get(prefix + "/generation-jobs/{job_id}")
    async def job(job_id: str, m: Member):
        return jobs.view(jobs.get(m, job_id))

    @app.delete(prefix + "/generation-jobs/{job_id}")
    async def cancel(job_id: str, m: Member):
        return jobs.view(jobs.cancel_job(m, job_id))

    @app.post(prefix + "/session-reviews")
    async def review_session(body: SessionReviewRequest, m: Member):
        m.require_edit()
        try:
            receipt_id = jobs.review(m, body.payload, body.job_id)
        except ValueError as error:
            raise AppError(422, "invalid_evidence", str(error)) from None
        return {"receipt_id": receipt_id}

    def exported(payload, fmt):
        content = payload.model_dump_json(indent=2) if fmt == "json" else export_text(payload)
        return Response(content, media_type="application/json" if fmt == "json" else "text/plain", headers={"Content-Disposition": f'attachment; filename="bugbrief-ticket.{"json" if fmt == "json" else "txt"}"'})

    @app.post(prefix + "/session-exports")
    async def export_session(body: SessionExportRequest, m: Member):
        jobs.check_receipt(m, body.receipt_id, body.payload)
        return exported(body.payload, body.format)

    @app.get(prefix + "/tickets")
    async def ticket_list(m: Member, search: str = Query("", max_length=120), area: Literal["", "Authentication", "Billing", "Dashboard", "Integrations", "Unknown"] = "", status: Literal["", "draft", "reviewed"] = "", page: int = Query(0, ge=0, le=10000)):
        return await repo.list(m, search, area, status, page)

    @app.post(prefix + "/tickets", status_code=201)
    async def save_ticket(body: SaveRequest, m: Member):
        m.require_edit()
        source, metadata = None, {"provider": "manual", "schema_version": "1.0"}
        if body.job_id:
            current_job = jobs.result(m, body.job_id)
            try:
                body.payload.check_source(current_job.report)
            except ValueError as error:
                raise AppError(422, "invalid_evidence", str(error)) from None
            source = current_job.report if body.save_source else None
            metadata = current_job.generation_metadata
        elif body.save_source:
            raise AppError(422, "source_unavailable", "The original report is not available for this ticket.")
        return await repo.create(m, body.payload, body.operation_id, source, metadata)

    @app.get(prefix + "/tickets/{ticket_id}")
    async def ticket_detail(ticket_id: str, m: Member):
        return await repo.get(m, ticket_id)

    @app.patch(prefix + "/tickets/{ticket_id}")
    async def update_ticket(ticket_id: str, body: UpdateRequest, m: Member):
        m.require_edit()
        try:
            return await repo.update(m, ticket_id, body.payload, body.expected_revision)
        except ValueError as error:
            raise AppError(422, "invalid_evidence", str(error)) from None

    @app.post(prefix + "/tickets/{ticket_id}/review")
    async def review_ticket(ticket_id: str, body: RevisionRequest, m: Member):
        m.require_edit()
        return await repo.review(m, ticket_id, body.expected_revision)

    @app.get(prefix + "/tickets/{ticket_id}/export")
    async def export_ticket(ticket_id: str, m: Member, revision: int = Query(ge=1), format: Literal["json", "text"] = "json"):
        row = await repo.get(m, ticket_id)
        if row["status"] != "reviewed" or row["reviewed_revision"] != row["revision"] or row["revision"] != revision:
            raise AppError(409, "review_required", "Review the current ticket before exporting it.")
        return exported(Ticket.model_validate(row["payload"]), format)

    @app.delete(prefix + "/tickets/{ticket_id}", status_code=204)
    async def delete_ticket(ticket_id: str, m: Member):
        await repo.delete(m, ticket_id)
        return Response(status_code=204)

    return app


# Factory loading keeps imports and tests independent of the user's secret configuration.
# Run uvicorn app.main:create_app --factory.
