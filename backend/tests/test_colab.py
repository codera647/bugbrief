import hashlib
import json
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ml"))
from dataset import candidate_digest, file_digest, load_splits, read_rows
from prepare_dataset import prepare


def test_bulk_approved_splits_require_explicit_opt_in_and_preserve_provenance():
    data = ROOT / "ml/data/colab-splits-500"
    with pytest.raises(ValueError, match="--allow-bulk-approved"):
        load_splits(data)
    splits = load_splits(data, allow_bulk_approved=True)
    families = set()
    for name, expected in (("train", 400), ("validation", 50), ("test", 50)):
        rows = splits[name]
        assert len(rows) == expected
        assert set(Counter(row["ticket"]["product_area"] for row in rows).values()) == {expected // 5}
        new_families = {row["family_id"] for row in rows}
        assert not families & new_families
        families |= new_families
        assert all(row["reviewed_by"] == row["reviewed_at"] == "" for row in rows)
    assert len(families) == 50


def test_bulk_approval_checks_source_and_every_row_even_if_split_hash_is_rewritten(tmp_path):
    source = ROOT / "ml/data/colab-splits-500"
    copied = tmp_path / "data"
    shutil.copytree(source, copied)
    rows = read_rows(copied / "train.jsonl")
    rows[0]["ticket"]["title"] = "Changed after acceptance"
    (copied / "train.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = json.loads((copied / "manifest.json").read_text())
    manifest["sha256"]["train"] = file_digest(copied / "train.jsonl")
    (copied / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="do not match the bulk-approved source"):
        load_splits(copied, allow_bulk_approved=True)


def test_bulk_preparation_validates_approval_and_refuses_unapproved_or_stale_data(tmp_path):
    source = ROOT / "ml/data/bulk-approved.jsonl"
    approval_path = ROOT / "ml/data/bulk-approval.json"
    counts = {"train": 400, "validation": 50, "test": 50}
    with pytest.raises(ValueError, match="human review"):
        prepare(source, tmp_path / "unapproved", counts=counts)
    output = tmp_path / "balanced"
    prepare(source, output, counts=counts, bulk_approval=approval_path, stratify_by_area=True)
    splits = load_splits(output, allow_bulk_approved=True)
    assert len(splits["train"]) == 400
    approval = json.loads((output / "bulk-approval.json").read_text())
    approval["examples"][0]["sha256"] = "0" * 64
    (output / "bulk-approval.json").write_text(json.dumps(approval))
    with pytest.raises(ValueError, match="changed after user bulk approval"):
        load_splits(output, allow_bulk_approved=True)


def test_notebook_bundle_has_only_allowlisted_files_with_matching_hashes():
    notebook = json.loads((ROOT / "ml/BugBrief_Training.ipynb").read_text(encoding="utf-8"))
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None and not cell["outputs"]
            compile("".join(cell["source"]), cell["id"], "exec")
    with zipfile.ZipFile(ROOT / "ml/colab/BugBrief_Colab_Bundle.zip") as bundle:
        manifest = json.loads(bundle.read("BugBrief_Colab/BUNDLE_MANIFEST.json"))
        assert len(bundle.namelist()) == len(manifest["sha256"]) + 1
        for name, digest in manifest["sha256"].items():
            assert not any(part.startswith('.') for part in Path(name).parts)
            # Exclude runtime artifact directories; artifacts.py is ordinary source.
            assert ".env" not in name and "artifacts" not in Path(name).parts
            content = bundle.read("BugBrief_Colab/" + name)
            assert hashlib.sha256(content).hexdigest() == digest
            assert content == (ROOT / name).read_bytes(), f"Bundle is stale: {name}"


def test_notebook_upload_cell_extracts_valid_bundle_and_refuses_changed_existing_files(tmp_path):
    notebook = json.loads((ROOT / "ml/BugBrief_Training.ipynb").read_text(encoding="utf-8"))
    upload_cell = next("".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code" and "uploaded_bytes" in "".join(cell["source"]))
    shutil.copyfile(ROOT / "ml/colab/BugBrief_Colab_Bundle.zip", tmp_path / "BugBrief_Colab_Bundle.zip")
    local_cell = upload_cell.replace('/content', tmp_path.as_posix())
    exec(compile(local_cell, 'upload-cell', 'exec'), {})
    exec(compile(local_cell, 'upload-cell-rerun', 'exec'), {})
    extracted = tmp_path / "BugBrief_Colab/ml/train.py"
    extracted.write_text("changed")
    with pytest.raises(AssertionError, match="Existing file differs"):
        exec(compile(local_cell, 'upload-cell-reject', 'exec'), {})


def test_bulk_approval_hash_is_the_same_as_review_workflow():
    rows = read_rows(ROOT / "ml/data/bulk-approved.jsonl")
    approval = json.loads((ROOT / "ml/data/bulk-approval.json").read_text())
    events = {event["id"]: event for event in approval["examples"]}
    assert all(candidate_digest(row) == events[row["id"]]["sha256"] for row in rows)
