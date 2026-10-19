import copy
import json
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from correct_dataset import audit_candidates, correct_dataset
from dataset import file_digest, load_splits
from generate_dataset import generate_candidates

V2 = ROOT / "ml/data/colab-splits-500-v2"


def test_expectation_labels_follow_report_content_and_ignore_environment():
    rows = generate_candidates()
    families = {}
    for row in rows:
        families.setdefault(row["family_id"], []).append(row)
    # Concrete named feature: implied success does not depend on app/browser fields.
    sheets = families["integrations-sheets-stale"]
    assert {r["ticket"]["expected_behavior_basis"] for r in sheets if "I expected to" not in r["report"]} == {"Inferred"}
    # Vague unidentified page: browser information does not establish the intended result.
    loading = families["unknown-loading-page"]
    assert {r["ticket"]["expected_behavior_basis"] for r in loading if "I expected to" not in r["report"]} == {"Unknown"}
    # Unknown product area does not prevent a concrete save operation from supporting inference.
    saved = families["unknown-unsaved-changes"]
    assert {r["ticket"]["expected_behavior_basis"] for r in saved if "I expected to" not in r["report"]} == {"Inferred"}
    for row in rows:
        explicit = "I expected to" in row["report"]
        assert (row["ticket"]["expected_behavior_basis"] == "Reported") == explicit
        if row["ticket"]["expected_behavior_basis"] == "Unknown":
            assert row["ticket"]["expected_behavior"] is None
            assert "Expected result" in row["ticket"]["missing_information"]
    assert Counter(r["ticket"]["expected_behavior_basis"] for r in rows) == {"Reported": 200, "Inferred": 252, "Unknown": 48}
    audit_candidates(rows)


@pytest.mark.parametrize("mistake", ["label", "title", "environment", "steps", "question_count"])
def test_source_audit_catches_observed_adapter_failure_patterns(mistake):
    rows = generate_candidates()
    row = next(r for r in rows if r["id"] == "billing-invoice-draft-v01")
    if mistake == "label":
        row["ticket"]["expected_behavior_basis"] = "Reported"
    elif mistake == "title":
        row["ticket"]["title"] = "Invoice draft retains line-item descriptions"
    elif mistake == "environment":
        row["ticket"]["reported_environment"]["other_details"] = ["Actions leading to the issue"]
    elif mistake == "steps":
        row["ticket"]["reported_steps"] = ["Open an invoice draft."]
    else:
        row["ticket"]["follow_up_questions"] += ["Which additional detail is missing?"]
    with pytest.raises(ValueError):
        audit_candidates(rows)


def test_corrected_dataset_preserves_sources_folds_and_full_change_history():
    parent = load_splits(ROOT / "ml/data/colab-splits-500", allow_bulk_approved=True)
    with pytest.raises(ValueError, match="--allow-corrected-synthetic"):
        load_splits(V2)
    with pytest.raises(ValueError, match="--allow-corrected-synthetic"):
        load_splits(V2, allow_bulk_approved=True)
    corrected = load_splits(V2, allow_corrected_synthetic=True)
    for name in parent:
        assert [r["id"] for r in parent[name]] == [r["id"] for r in corrected[name]]
        assert {r["family_id"] for r in parent[name]} == {r["family_id"] for r in corrected[name]}
        assert set(Counter(r["ticket"]["product_area"] for r in corrected[name]).values()) == {len(parent[name]) // 5}
        assert {r["ticket"]["expected_behavior_basis"] for r in corrected[name]} == {"Reported", "Inferred", "Unknown"}
        for before, after in zip(parent[name], corrected[name]):
            for field in ("id", "report", "family_id", "source", "reviewed_by", "reviewed_at"):
                assert before[field] == after[field]
            # The original authored targets already guard these model failure cases.
            for field in ("title", "actual_behavior", "product_area", "product_area_evidence", "reported_environment", "reported_steps"):
                assert before["ticket"][field] == after["ticket"][field]
    log = json.loads((V2 / "corrections.json").read_text())
    assert log["changed_rows"] == len(log["changes"]) == 116
    audit_candidates([r for rows in corrected.values() for r in rows])


def test_correction_build_is_reproducible_and_does_not_overwrite(tmp_path):
    generated = correct_dataset(tmp_path / "v2")
    result = load_splits(generated, allow_corrected_synthetic=True)
    original = load_splits(V2, allow_corrected_synthetic=True)
    assert result == original
    with pytest.raises(ValueError, match="already exists"):
        correct_dataset(generated)


def test_changed_correction_history_is_rejected(tmp_path):
    destination = tmp_path / "v2"
    shutil.copytree(V2, destination)
    log_path = destination / "corrections.json"
    value = json.loads(log_path.read_text())
    value["changes"][0]["fields"]["expected_behavior_basis"]["after"] = "Reported"
    log_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="Correction history changed"):
        load_splits(destination, allow_corrected_synthetic=True)
    # Even refreshing the outer checksum cannot conceal an inaccurate change log.
    manifest_path = destination / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["corrections_sha256"] = file_digest(log_path)
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="actual target changes"):
        load_splits(destination, allow_corrected_synthetic=True)


def test_v2_bundle_and_notebook_are_consistent_and_extract(tmp_path):
    path = ROOT / "ml/colab/BugBrief_Training_v2.ipynb"
    document = json.loads(path.read_text(encoding="utf-8"))
    codes = ["".join(cell["source"]) for cell in document["cells"] if cell["cell_type"] == "code"]
    for source in codes:
        compile(source, 'v2-cell', 'exec')
    assert any('--allow-corrected-synthetic' in source for source in codes)
    assert any("bugbrief-qlora-02" in source for source in codes)
    assert any("allow_corrected_synthetic=allow" in source for source in codes)
    filename = "BugBrief_Colab_v2_Bundle.zip"
    bundle_path = ROOT / "ml/colab" / filename
    with zipfile.ZipFile(bundle_path) as archive:
        manifest = json.loads(archive.read('BugBrief_Colab_v2/BUNDLE_MANIFEST.json'))
        assert manifest['version'] == 2
        for name, sha in manifest['sha256'].items():
            assert archive.read('BugBrief_Colab_v2/' + name) == (ROOT / name).read_bytes()
            assert file_digest(ROOT / name) == sha
        assert not any('/.env' in name for name in archive.namelist())
    shutil.copyfile(bundle_path, tmp_path / filename)
    upload = next(source for source in codes if 'uploaded_bytes' in source)
    exec(compile(upload.replace('/content', tmp_path.as_posix()), 'v2-extract', 'exec'), {})
    assert load_splits(tmp_path / 'BugBrief_Colab_v2/ml/data/colab-splits-500-v2', allow_corrected_synthetic=True)
