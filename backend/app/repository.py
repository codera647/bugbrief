import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx

from .auth import DEMO_USER, DEMO_WORKSPACE, Identity, Membership
from .domain import Ticket
from .errors import AppError


def now():
    return datetime.now(timezone.utc).isoformat()


class SQLiteRepository:
    """Local demo persistence; never used for authenticated cloud deployment."""

    def __init__(self, filename):
        if filename != ":memory:":
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(filename, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS members(user_id TEXT, workspace_id TEXT, role TEXT, name TEXT, active INTEGER DEFAULT 1, PRIMARY KEY(user_id,workspace_id));
          CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, created_by TEXT NOT NULL, operation_id TEXT NOT NULL, payload TEXT NOT NULL, source_report TEXT, generation_metadata TEXT NOT NULL, schema_version TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'draft', reviewed_revision INTEGER, reviewed_by TEXT, reviewed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(workspace_id,created_by,operation_id));
          CREATE TABLE IF NOT EXISTS revisions(ticket_id TEXT REFERENCES tickets(id) ON DELETE CASCADE, revision INTEGER, payload TEXT, edited_by TEXT, created_at TEXT, PRIMARY KEY(ticket_id,revision));
        """)
        self.db.execute("INSERT OR IGNORE INTO members VALUES(?,?,?,?,1)", (DEMO_USER, DEMO_WORKSPACE, "owner", "LedgerFlow"))
        self.db.commit()

    async def memberships(self, identity: Identity):
        return [Membership(identity.user_id, r["workspace_id"], r["role"], r["name"]) for r in self.db.execute("SELECT * FROM members WHERE user_id=? AND active=1", (identity.user_id,))]

    def current_member(self, member):
        row = self.db.execute("SELECT * FROM members WHERE user_id=? AND workspace_id=? AND active=1", (member.user_id, member.workspace_id)).fetchone()
        if not row:
            raise AppError(403, "access_not_granted", "Your account does not have access to this workspace.")
        return Membership(member.user_id, member.workspace_id, row["role"], row["name"])

    def decode(self, row):
        if not row:
            raise AppError(404, "ticket_not_found", "This ticket is not available in your workspace.")
        result = dict(row)
        for key in ("payload", "generation_metadata"):
            result[key] = json.loads(result[key])
        return result

    async def get(self, member, ticket_id):
        self.current_member(member)
        return self.decode(self.db.execute("SELECT * FROM tickets WHERE workspace_id=? AND id=?", (member.workspace_id, ticket_id)).fetchone())

    async def list(self, member, search="", area="", status="", page=0):
        self.current_member(member)
        params = [member.workspace_id, search.lower()]
        query = "SELECT * FROM tickets WHERE workspace_id=? AND instr(lower(json_extract(payload,'$.title')),?) > 0"
        if area:
            query += " AND json_extract(payload,'$.product_area')=?"
            params.append(area)
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY updated_at DESC,id DESC LIMIT 21 OFFSET ?"
        params.append(page * 20)
        rows = [self.decode(row) for row in self.db.execute(query, params)]
        summaries = [{key: row[key] for key in ("id", "revision", "status", "updated_at", "created_by")} | {"title": row["payload"]["title"], "product_area": row["payload"]["product_area"]} for row in rows[:20]]
        return {"items": summaries, "has_more": len(rows) > 20}

    async def create(self, member, payload, operation_id, source, metadata):
        self.current_member(member).require_edit()
        existing = self.db.execute("SELECT * FROM tickets WHERE workspace_id=? AND created_by=? AND operation_id=?", (member.workspace_id, member.user_id, operation_id)).fetchone()
        if existing:
            previous = self.decode(existing)
            if previous["payload"] != payload.model_dump() or previous["source_report"] != source:
                raise AppError(409, "operation_conflict", "This save operation was already used for another ticket version.")
            return previous
        ticket_id, timestamp = str(uuid4()), now()
        with self.db:
            self.db.execute("INSERT INTO tickets(id,workspace_id,created_by,operation_id,payload,source_report,generation_metadata,schema_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", (ticket_id, member.workspace_id, member.user_id, operation_id, payload.model_dump_json(), source, json.dumps(metadata), "1.0", timestamp, timestamp))
            self.snapshot(ticket_id, 1, payload, member.user_id, timestamp)
        return await self.get(member, ticket_id)

    def snapshot(self, ticket_id, revision, payload, user_id, timestamp):
        self.db.execute("INSERT INTO revisions VALUES(?,?,?,?,?)", (ticket_id, revision, payload.model_dump_json(), user_id, timestamp))
        self.db.execute("DELETE FROM revisions WHERE ticket_id=? AND revision <= ?", (ticket_id, revision - 10))

    async def update(self, member, ticket_id, payload, expected_revision):
        self.current_member(member).require_edit()
        current = await self.get(member, ticket_id)
        payload.check_source(current["source_report"])
        timestamp = now()
        with self.db:
            cursor = self.db.execute("UPDATE tickets SET payload=?,revision=revision+1,status='draft',reviewed_revision=NULL,reviewed_by=NULL,reviewed_at=NULL,updated_at=? WHERE workspace_id=? AND id=? AND revision=?", (payload.model_dump_json(), timestamp, member.workspace_id, ticket_id, expected_revision))
            if cursor.rowcount != 1:
                raise AppError(409, "revision_conflict", "Someone updated this ticket. Your local changes have been kept.")
            self.snapshot(ticket_id, expected_revision + 1, payload, member.user_id, timestamp)
        return await self.get(member, ticket_id)

    async def review(self, member, ticket_id, expected_revision):
        self.current_member(member).require_edit()
        current = await self.get(member, ticket_id)
        Ticket.model_validate(current["payload"]).check_source(current["source_report"])
        with self.db:
            cursor = self.db.execute("UPDATE tickets SET status='reviewed',reviewed_revision=revision,reviewed_by=?,reviewed_at=? WHERE workspace_id=? AND id=? AND revision=?", (member.user_id, now(), member.workspace_id, ticket_id, expected_revision))
            if cursor.rowcount != 1:
                raise AppError(409, "revision_conflict", "The ticket changed. Review the current version.")
        return await self.get(member, ticket_id)

    async def delete(self, member, ticket_id):
        current_member = self.current_member(member)
        current_member.require_edit()
        current = await self.get(member, ticket_id)
        if current_member.role != "owner" and current["created_by"] != member.user_id:
            raise AppError(403, "role_denied", "Only the creator or a workspace owner can delete this ticket.")
        with self.db:
            self.db.execute("DELETE FROM tickets WHERE workspace_id=? AND id=?", (member.workspace_id, ticket_id))

    async def close(self):
        self.db.close()


class SupabaseRepository:
    def __init__(self, settings):
        headers = {"apikey": settings.supabase_key}
        # New sb_secret keys are not JWTs; legacy service-role keys need the bearer header.
        if not settings.supabase_key.startswith("sb_secret_"):
            headers["Authorization"] = "Bearer " + settings.supabase_key
        self.client = httpx.AsyncClient(base_url=settings.supabase_url + "/rest/v1/", headers=headers, timeout=15)

    async def request(self, method, path, **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise AppError(503, "database_unavailable", "The workspace is unavailable. Your changes have been kept.") from None
        if response.is_error:
            code = response.json().get("code", "") if response.headers.get("content-type", "").startswith("application/json") else ""
            mapping = {"P0002": (404, "ticket_not_found", "This ticket is not available in your workspace."), "BB409": (409, "revision_conflict", "Someone updated this ticket. Your local changes have been kept."), "42501": (403, "role_denied", "You do not have permission for this action.")}
            status, error, message = mapping.get(code, (503, "database_unavailable", "The workspace is unavailable. Your changes have been kept."))
            raise AppError(status, error, message)
        return response.json() if response.content else None

    async def memberships(self, identity):
        rows = await self.request("GET", "workspace_members", params={"user_id": "eq." + identity.user_id, "active": "eq.true", "select": "workspace_id,role,workspaces(name)"})
        return [Membership(identity.user_id, r["workspace_id"], r["role"], r["workspaces"]["name"]) for r in rows]

    async def rpc(self, member, action, **extra):
        return await self.request("POST", "rpc/bugbrief_ticket_action", json={"p_user": member.user_id, "p_workspace": member.workspace_id, "p_action": action, "p_data": extra})

    async def get(self, member, ticket_id):
        return await self.rpc(member, "get", ticket_id=ticket_id)

    async def list(self, member, search="", area="", status="", page=0):
        return await self.rpc(member, "list", search=search, area=area, status=status, page=page)

    async def create(self, member, payload, operation_id, source, metadata):
        return await self.rpc(member, "create", payload=payload.model_dump(), operation_id=operation_id, source_report=source, generation_metadata=metadata)

    async def update(self, member, ticket_id, payload, expected_revision):
        current = await self.get(member, ticket_id)
        payload.check_source(current["source_report"])
        return await self.rpc(member, "update", ticket_id=ticket_id, payload=payload.model_dump(), expected_revision=expected_revision)

    async def review(self, member, ticket_id, expected_revision):
        current = await self.get(member, ticket_id)
        Ticket.model_validate(current["payload"]).check_source(current["source_report"])
        return await self.rpc(member, "review", ticket_id=ticket_id, expected_revision=expected_revision)

    async def delete(self, member, ticket_id):
        await self.rpc(member, "delete", ticket_id=ticket_id)

    async def close(self):
        await self.client.aclose()
