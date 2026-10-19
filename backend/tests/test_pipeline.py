import copy
import json
import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.artifacts import file_hash, load_profile
from app.auth import DEMO_WORKSPACE
from app.config import Settings
from app.domain import Ticket
from app.inference import ExampleGenerator, TransformersGenerator, examples
from app.main import create_app
from app.quality import review_findings
from app.repository import SQLiteRepository


def fixture_profile(tmp_path):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapter_model.safetensors").write_bytes(b"TEST FIXTURE ONLY")
    (adapter / "training_args.bin").write_bytes(b"Never load this pickle")
    (adapter / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "test-model"}))
    run = {"model": "test-model", "model_revision": "a" * 40, "prompt_sha256": "b" * 64}
    (tmp_path / "run.json").write_text(json.dumps(run))
    profile = {"version": 1, "name": "Test profile", "status": "experimental", "model": "test-model", "revision": "a" * 40,
               "adapter_path": str(adapter), "adapter_sha256": file_hash(adapter / "adapter_model.safetensors"),
               "adapter_config_sha256": file_hash(adapter / "adapter_config.json"),
               "run_sha256": file_hash(tmp_path / "run.json"), "prompt_sha256": "b" * 64}
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(profile))
    return path, adapter


def test_profile_verifies_weights_and_base_identity_without_loading_pickle(tmp_path):
    path, adapter = fixture_profile(tmp_path)
    profile, result = load_profile(path)
    assert result == adapter and profile["name"] == "Test profile"
    (adapter / "adapter_config.json").write_text(json.dumps({"base_model_name_or_path": "different-model"}))
    profile["adapter_config_sha256"] = file_hash(adapter / "adapter_config.json")
    path.write_text(json.dumps(profile))
    with pytest.raises(ValueError, match="identity"):
        load_profile(path)


def test_profile_rejects_changed_adapter_settings(tmp_path):
    path, adapter = fixture_profile(tmp_path)
    config = adapter / "adapter_config.json"
    config.write_text(json.dumps({"base_model_name_or_path": "test-model", "lora_alpha": 64}))
    with pytest.raises(ValueError, match="Adapter configuration"):
        load_profile(path)


def test_profile_rejects_changed_weights_and_run(tmp_path):
    path, adapter = fixture_profile(tmp_path)
    (adapter / "adapter_model.safetensors").write_bytes(b"CHANGED")
    with pytest.raises(ValueError, match="Adapter weights"):
        load_profile(path)
    (adapter / "adapter_model.safetensors").write_bytes(b"TEST FIXTURE ONLY")
    (tmp_path / "run.json").write_text("{}")
    with pytest.raises(ValueError, match="Training run"):
        load_profile(path)


def test_quality_flags_known_v2_failures_without_rewriting_ticket():
    report = "A saved invoice draft loses its line-item description after reopening. I'm using Safari on iOS 17."
    payload = copy.deepcopy(examples()[0]["ticket"])
    payload.update(title="Invoice draft retains line-item descriptions", product_area="Billing",
                   product_area_evidence="A saved invoice draft loses its line-item description after reopening.",
                   actual_behavior="The draft retains its description.", expected_behavior="Keep the description.", expected_behavior_basis="Reported", reported_steps=["Clear the cache."])
    payload["reported_environment"] = {"browser": "Safari", "browser_version": "iOS 17", "operating_system": "iOS", "app_version": None, "other_details": ["Invoice and draft are open together"]}
    ticket = Ticket.model_validate(payload)
    original = ticket.model_dump()
    findings = review_findings(ticket, report)
    codes = {item["code"] for item in findings["findings"]}
    assert {"possible_reversed_meaning", "expectation_not_explicit", "os_in_browser_version", "environment_detail_not_quoted", "steps_need_comparison"} <= codes
    assert ticket.model_dump() == original
    assert sum(f["code"] == "possible_reversed_meaning" for f in findings["findings"]) == 2
    ticket.title = "Invoice draft retains no line-item description"
    assert not any(f["field"] == "title" and f["code"] == "possible_reversed_meaning" for f in review_findings(ticket, report)["findings"])


def test_quality_marks_missing_source_and_vague_expectations():
    ticket = Ticket.model_validate(examples()[0]["ticket"])
    assert review_findings(ticket, None)["source_available"] is False
    ticket.product_area = "Dashboard"
    ticket.expected_behavior = "See the dashboard content."
    ticket.expected_behavior_basis = "Inferred"
    codes = {item["code"] for item in review_findings(ticket, "The page keeps showing a loading indicator.")["findings"]}
    assert {"vague_expected_result", "area_needs_evidence"} <= codes


def test_loading_model_keeps_api_alive_and_reports_readiness():
    class Loading(ExampleGenerator):
        ready = False
        state = "loading"

        def __init__(self):
            self.entered = threading.Event()
            self.release = threading.Event()

        def load(self):
            self.entered.set()
            assert self.release.wait(3)
            self.ready, self.state = True, "ready"

    model = Loading()
    app = create_app(Settings(mode="demo", inference_mode="examples"), repository=SQLiteRepository(":memory:"), generator=model)
    with TestClient(app) as client:
        assert model.entered.wait(2)
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').json()['status'] == 'model_loading'
        assert client.get('/v1/config').json()['inference']['state'] == 'loading'
        model.release.set()
        for _ in range(100):
            if client.get('/health/ready').status_code == 200:
                break
            time.sleep(.01)
        assert client.get('/v1/config').json()['drafting_available'] is True


def test_draft_checks_are_authorized_source_bound_and_model_identity_is_saved():
    model = ExampleGenerator()
    # This identifies a test fixture, not an actual trained runtime.
    model.metadata = {"provider": "test_fixture", "adapter_sha256": "f" * 64}
    app = create_app(Settings(mode="demo", inference_mode="examples"), repository=SQLiteRepository(":memory:"), generator=model)
    headers = {"Authorization": "Bearer local-demo"}
    base = f'/v1/workspaces/{DEMO_WORKSPACE}'
    sample = examples()[0]
    with TestClient(app, client=('127.0.0.1', 50000)) as client:
        assert client.post(base + '/draft-checks', json={}).status_code == 401
        job = client.post(base + '/generation-jobs', headers=headers, json={"report": sample['report'], "operation_id": str(uuid4())}).json()
        for _ in range(100):
            job = client.get(base + '/generation-jobs/' + job['id'], headers=headers).json()
            if job['status'] == 'succeeded': break
            time.sleep(.01)
        assert job['status'] == 'succeeded' and job['checks']['source_available']
        model.metadata = {"provider": "different_test_fixture", "adapter_sha256": "e" * 64}
        checked = client.post(base + '/draft-checks', headers=headers, json={"job_id": job['id'], "payload": job['payload']})
        assert checked.status_code == 200
        bad = job['payload'] | {"product_area_evidence": "NOT IN THE ORIGINAL REPORT"}
        assert client.post(base + '/draft-checks', headers=headers, json={"job_id": job['id'], "payload": bad}).status_code == 422
        assert client.post(base + '/draft-checks', headers=headers, json={"job_id": str(uuid4()), "payload": job['payload']}).status_code == 404
        saved = client.post(base + '/tickets', headers=headers, json={"job_id": job['id'], "payload": job['payload'], "operation_id": str(uuid4())}).json()
        assert saved['generation_metadata']['adapter_sha256'] == 'f' * 64
        no_source = client.post(base + '/draft-checks', headers=headers, json={"ticket_id": saved['id'], "payload": saved['payload']}).json()
        assert no_source['source_available'] is False


def test_runtime_rejects_generation_until_ready():
    model = TransformersGenerator(Settings(mode="demo", inference_mode="transformers", model_profile="models/v2.json"))
    from app.errors import AppError
    with pytest.raises(AppError, match="loading"):
        model.validate_input("A report with enough characters.")
    model.state = "failed"
    with pytest.raises(AppError, match="could not start"):
        model.validate_input("A report with enough characters.")


def test_missing_profile_fails_in_background_without_exposing_path(tmp_path):
    missing = str(tmp_path / 'private-profile.json')
    settings = Settings(mode='demo', inference_mode='transformers', model_profile=missing)
    model = TransformersGenerator(settings)
    app = create_app(settings, repository=SQLiteRepository(':memory:'), generator=model)
    with TestClient(app) as client:
        for _ in range(100):
            if client.get('/v1/config').json()['inference']['state'] == 'failed': break
            time.sleep(.01)
        public = client.get('/v1/config')
        assert public.json()['inference']['state'] == 'failed'
        assert 'private-profile' not in public.text
        assert client.get('/health/live').status_code == 200
        assert client.get('/health/ready').status_code == 503
