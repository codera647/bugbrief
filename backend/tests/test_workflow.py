import copy
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import Authenticator, DEMO_USER, DEMO_WORKSPACE, Identity
from app.config import Settings
from app.domain import Ticket
from app.errors import AppError
from app.inference import ExampleGenerator, examples
from app.main import create_app
from app.repository import SQLiteRepository

OTHER_USER = "00000000-0000-4000-8000-000000000002"
OTHER_WORKSPACE = "00000000-0000-4000-8000-000000000020"
BASE = f"/v1/workspaces/{DEMO_WORKSPACE}"
PAYLOAD = examples()[0]["ticket"]
REPORT = examples()[0]["report"]
OWNER = {"Authorization": "Bearer owner"}
VIEWER = {"Authorization": "Bearer viewer"}


class TestAuth:
    async def identify(self, request):
        token = request.headers.get("authorization")
        if token == "Bearer owner":
            return Identity(DEMO_USER)
        if token == "Bearer viewer":
            return Identity(OTHER_USER)
        raise AppError(401, "invalid_session", "Sign in to continue.")


@pytest.fixture
def client():
    repo = SQLiteRepository(":memory:")
    repo.db.execute("INSERT INTO members VALUES(?,?,?,?,1)", (OTHER_USER, DEMO_WORKSPACE, "viewer", "LedgerFlow"))
    repo.db.execute("INSERT INTO members VALUES(?,?,?,?,1)", (DEMO_USER, OTHER_WORKSPACE, "owner", "Other project"))
    repo.db.commit()
    app = create_app(Settings(mode="demo", inference_mode="examples"), repository=repo, generator=ExampleGenerator(), authenticator=TestAuth())
    with TestClient(app) as result:
        yield result


def saved(client, source=False, operation=None):
    body = {"payload": copy.deepcopy(PAYLOAD), "operation_id": operation or str(uuid4())}
    if source:
        job = client.post(BASE + "/generation-jobs", json={"report": REPORT, "operation_id": str(uuid4())}, headers=OWNER).json()
        for _ in range(100):
            current = client.get(BASE + "/generation-jobs/" + job["id"], headers=OWNER).json()
            if current["status"] == "succeeded":
                break
            time.sleep(.005)
        body.update(job_id=job["id"], save_source=True)
    response = client.post(BASE + "/tickets", json=body, headers=OWNER)
    assert response.status_code == 201, response.text
    return response.json()


def test_private_routes_require_login(client):
    assert client.get(BASE + "/tickets").status_code == 401
    assert client.post(BASE + "/tickets", json={}, headers={}).status_code == 401


def test_viewer_cannot_generate_or_save(client):
    assert client.post(BASE + "/generation-jobs", json={"report": REPORT, "operation_id": str(uuid4())}, headers=VIEWER).status_code == 403
    assert client.post(BASE + "/tickets", json={"payload": PAYLOAD, "operation_id": str(uuid4())}, headers=VIEWER).status_code == 403


def test_shared_history_and_source_opt_in(client):
    row = saved(client)
    assert row["source_report"] is None
    result = client.get(BASE + "/tickets/" + row["id"], headers=VIEWER)
    assert result.status_code == 200
    assert result.json()["payload"] == PAYLOAD
    with_source = saved(client, source=True)
    assert with_source["source_report"] == REPORT


def test_revision_conflicts_do_not_overwrite(client):
    row = saved(client)
    url = BASE + "/tickets/" + row["id"]
    changed = copy.deepcopy(PAYLOAD) | {"title": "First user's edits"}
    assert client.patch(url, json={"payload": changed, "expected_revision": 1}, headers=OWNER).status_code == 200
    stale = client.patch(url, json={"payload": PAYLOAD, "expected_revision": 1}, headers=OWNER)
    assert stale.status_code == 409
    assert client.get(url, headers=OWNER).json()["payload"]["title"] == changed["title"]


def test_review_is_invalidated_and_old_exports_blocked(client):
    row = saved(client)
    url = BASE + "/tickets/" + row["id"]
    assert client.get(url + "/export?revision=1", headers=OWNER).status_code == 409
    assert client.post(url + "/review", json={"expected_revision": 1}, headers=OWNER).status_code == 200
    exported = client.get(url + "/export?revision=1&format=json", headers=VIEWER)
    assert exported.status_code == 200 and exported.json() == PAYLOAD
    changed = copy.deepcopy(PAYLOAD) | {"title": "Edited after review"}
    updated = client.patch(url, json={"payload": changed, "expected_revision": 1}, headers=OWNER).json()
    assert updated["status"] == "draft" and updated["reviewed_revision"] is None
    assert client.get(url + "/export?revision=1", headers=OWNER).status_code == 409
    assert client.get(url + "/export?revision=2", headers=OWNER).status_code == 409


def test_other_workspace_ticket_is_not_visible(client):
    row = saved(client)
    other_url = f"/v1/workspaces/{OTHER_WORKSPACE}/tickets/{row['id']}"
    assert client.get(other_url, headers=OWNER).status_code == 404
    assert client.get(f"/v1/workspaces/{OTHER_WORKSPACE}/tickets", headers=VIEWER).status_code == 403


def test_revoked_membership_blocks_unexpired_identity(client):
    row = saved(client)
    repo = client.app.state.repository
    repo.db.execute("UPDATE members SET active=0 WHERE user_id=? AND workspace_id=?", (OTHER_USER, DEMO_WORKSPACE))
    repo.db.commit()
    assert client.get(BASE + "/tickets/" + row["id"], headers=VIEWER).status_code == 403


def test_generation_only_accepts_known_examples_in_demo(client):
    result = client.post(BASE + "/generation-jobs", json={"report": "A new unrecognized bug report in the dashboard.", "operation_id": str(uuid4())}, headers=OWNER)
    assert result.status_code == 422 and result.json()["error"]["code"] == "example_only"


def test_session_receipt_is_bound_to_payload_and_user(client):
    response = client.post(BASE + "/generation-jobs", json={"report": REPORT, "operation_id": str(uuid4())}, headers=OWNER)
    assert response.status_code == 202
    jid = response.json()["id"]
    for _ in range(100):
        if client.get(BASE + "/generation-jobs/" + jid, headers=OWNER).json()["status"] == "succeeded": break
        time.sleep(.005)
    assert client.get(BASE + "/generation-jobs/" + jid, headers=VIEWER).status_code == 404
    receipt = client.post(BASE + "/session-reviews", json={"job_id": jid, "payload": PAYLOAD}, headers=OWNER).json()["receipt_id"]
    body = {"receipt_id": receipt, "payload": PAYLOAD, "format": "text"}
    assert client.post(BASE + "/session-exports", json=body, headers=OWNER).status_code == 200
    assert client.post(BASE + "/session-exports", json=body, headers=VIEWER).status_code == 409
    body["payload"] = copy.deepcopy(PAYLOAD) | {"title": "Changed"}
    assert client.post(BASE + "/session-exports", json=body, headers=OWNER).status_code == 409


def test_schema_rejects_inventions_in_structure(client):
    bad = copy.deepcopy(PAYLOAD) | {"root_cause": "Database broken"}
    assert client.post(BASE + "/tickets", json={"payload": bad, "operation_id": str(uuid4())}, headers=OWNER).status_code == 422
    with pytest.raises(ValidationError): Ticket.model_validate(copy.deepcopy(PAYLOAD) | {"follow_up_questions": ["One?", "Two?", "Three?", "Four?"]})
    with pytest.raises(ValidationError): Ticket.model_validate(copy.deepcopy(PAYLOAD) | {"expected_behavior": None})


def test_delete_removes_revisions_and_is_role_scoped(client):
    row = saved(client)
    assert client.delete(BASE + "/tickets/" + row["id"], headers=VIEWER).status_code == 403
    assert client.delete(BASE + "/tickets/" + row["id"], headers=OWNER).status_code == 204
    assert client.get(BASE + "/tickets/" + row["id"], headers=OWNER).status_code == 404
    assert client.app.state.repository.db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0


def test_idempotent_save_creates_one_ticket(client):
    operation = str(uuid4())
    first, second = saved(client, operation=operation), saved(client, operation=operation)
    assert first["id"] == second["id"]
    assert len(client.get(BASE + "/tickets", headers=OWNER).json()["items"]) == 1


def test_body_limit_and_validation_do_not_echo_report(client):
    result = client.post(BASE + "/generation-jobs", content=b'x'*20000, headers=OWNER | {"Content-Type": "application/json"})
    assert result.status_code == 413
    secret = "customer private content"
    result = client.post(BASE + "/generation-jobs", json={"report": secret, "operation_id": "bad!"}, headers=OWNER)
    assert result.status_code == 422 and secret not in result.text


def test_demo_auth_is_loopback_only():
    from starlette.requests import Request
    import asyncio
    auth = Authenticator(Settings(mode="demo"))
    remote = Request({"type": "http", "headers": [(b"authorization", b"Bearer local-demo")], "client": ("203.0.113.1",1234)})
    with pytest.raises(AppError): asyncio.run(auth.identify(remote))


def test_production_jwt_verification_rejects_wrong_issuer_and_expiry():
    from starlette.requests import Request
    import asyncio
    key = ec.generate_private_key(ec.SECP256R1())
    auth = Authenticator(Settings(supabase_url="https://example.supabase.co"))
    class Keys:
        def get_signing_key_from_jwt(self, token):
            return type("Key", (), {"key": key.public_key()})()
    auth.keys = Keys()
    claims = {"sub": DEMO_USER, "iss": "https://example.supabase.co/auth/v1", "aud": "authenticated", "exp": int(time.time())+300, "iat": int(time.time())}
    def request(values):
        token = jwt.encode(values,key,algorithm="ES256")
        return Request({"type":"http","headers":[(b"authorization",("Bearer "+token).encode())],"client":("127.0.0.1",1234)})
    assert asyncio.run(auth.identify(request(claims))).user_id == DEMO_USER
    with pytest.raises(AppError): asyncio.run(auth.identify(request(claims | {"iss":"https://attacker.invalid"})))
    with pytest.raises(AppError): asyncio.run(auth.identify(request(claims | {"exp":1})))
