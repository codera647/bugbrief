"""Verify v2 offline, or run a real synthetic report through the temporary API workflow."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.artifacts import load_profile
from app.inference import messages_for


def write_evidence(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2); handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Load real weights and test the API using an isolated in-memory database")
    parser.add_argument("--output", type=Path, default=ROOT / "ml/artifacts/v2-pipeline-smoke.json")
    args = parser.parse_args()
    profile, _ = load_profile("models/v2.json")
    assert hashlib.sha256(json.dumps(messages_for(""), sort_keys=True).encode()).hexdigest() == profile["prompt_sha256"]
    print("Pinned v2 adapter files, training manifest, base-model identity, and serving prompt verified.", flush=True)
    if not args.live:
        return
    if args.output.exists():
        parser.error("Output already exists; use a new filename")
    from dataclasses import replace
    from importlib.metadata import version
    from fastapi.testclient import TestClient
    from app.auth import DEMO_WORKSPACE
    from app.config import Settings
    from app.domain import Ticket
    from app.inference import TransformersGenerator, examples
    from app.main import create_app
    from app.repository import SQLiteRepository
    settings = replace(Settings.load(), mode="demo", database=":memory:")
    class SyntheticDiagnosticGenerator(TransformersGenerator):
        # Only this CLI's fixed synthetic report is recorded. The API runtime
        # never retains rejected model text or returns it as a usable draft.
        raw_output = None

        def _generate_text(self, report, cancel):
            self.raw_output = super()._generate_text(report, cancel)
            return self.raw_output

    generator = SyntheticDiagnosticGenerator(settings)
    print("Loading real v2 model…", flush=True)
    load_started = time.monotonic()
    generator.load()
    load_seconds = time.monotonic() - load_started
    print(f"Model ready after {load_seconds:.1f}s. Testing the API workflow…", flush=True)
    headers = {"Authorization": "Bearer local-demo"}
    base = f"/v1/workspaces/{DEMO_WORKSPACE}"
    report = examples()[0]["report"]
    started = time.monotonic()
    app = create_app(settings, repository=SQLiteRepository(":memory:"), generator=generator)
    with TestClient(app, client=("127.0.0.1", 54321)) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get(base + "/tickets").status_code == 401
        submitted = client.post(base + "/generation-jobs", headers=headers, json={"report": report, "operation_id": str(uuid4())})
        assert submitted.status_code == 202, submitted.text
        job_id = submitted.json()["id"]
        last = None
        while time.monotonic() - started < settings.generation_timeout + 30:
            job = client.get(base + "/generation-jobs/" + job_id, headers=headers).json()
            if job["status"] != last:
                print("Generation:", job["status"], flush=True); last = job["status"]
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                break
            time.sleep(.2)
        if job["status"] != "succeeded":
            issue = None
            if generator.raw_output:
                try:
                    Ticket.model_validate_json(generator.raw_output).check_source(report)
                except ValueError as error:
                    issue = str(error)
            write_evidence(args.output, {"automated_workflow_test": True, "human_review_performed": False,
                           "report_source": "fixed synthetic UI example", "source_report": report,
                           "model_load_seconds": load_seconds, "elapsed_seconds": time.monotonic() - started,
                           "generation_metadata": generator.metadata, "status": job["status"],
                           "error": job.get("error"), "validation_issue": issue,
                           "raw_synthetic_output": generator.raw_output, "passed": []})
            raise RuntimeError(f"Synthetic workflow failed; diagnostic evidence: {args.output}")
        generation_seconds = time.monotonic() - started
        payload = job["payload"]
        checked = client.post(base + "/draft-checks", headers=headers, json={"job_id": job_id, "payload": payload})
        assert checked.status_code == 200, checked.text
        saved = client.post(base + "/tickets", headers=headers, json={"job_id": job_id, "payload": payload, "operation_id": str(uuid4()), "save_source": False})
        assert saved.status_code == 201, saved.text
        ticket = saved.json()
        assert ticket["source_report"] is None
        for field in ("adapter_sha256", "adapter_config_sha256", "run_sha256", "prompt_sha256"):
            assert ticket["generation_metadata"][field] == profile[field]
        url = base + "/tickets/" + ticket["id"]
        assert client.get(url + "/export?revision=1", headers=headers).status_code == 409
        reviewed = client.post(url + "/review", headers=headers, json={"expected_revision": 1})
        assert reviewed.status_code == 200
        exported = client.get(url + "/export?revision=1", headers=headers)
        assert exported.status_code == 200 and exported.json() == payload
        edited = payload | {"title": "Synthetic workflow test: edited ticket"}
        updated = client.patch(url, headers=headers, json={"payload": edited, "expected_revision": 1})
        assert updated.status_code == 200, updated.text
        changed = updated.json()
        assert changed["status"] == "draft" and changed["reviewed_revision"] is None
        assert client.get(url + f"/export?revision={changed['revision']}", headers=headers).status_code == 409
        result = {"automated_workflow_test": True, "human_review_performed": False, "report_source": "fixed synthetic UI example",
                  "source_report": report, "model_load_seconds": load_seconds, "generation_seconds": generation_seconds,
                  "elapsed_seconds": time.monotonic() - started, "generation_metadata": job["generation_metadata"],
                  "runtime_packages": {name: version(name) for name in ("torch", "transformers", "peft", "lm-format-enforcer", "pydantic")},
                  "payload": payload, "checks": checked.json(),
                  "passed": ["real_v2_generation", "source_checks", "private_routes", "save_without_original", "model_provenance", "review_before_export", "json_export", "edit_invalidates_review"]}
    write_evidence(args.output, result)
    print("Real-model API workflow passed. Evidence:", args.output, flush=True)


if __name__ == "__main__":
    main()
