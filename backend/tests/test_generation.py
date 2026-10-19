"""Review decisions here are simulated test fixtures, never dataset approvals."""
import copy
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
from dataset import load_splits, read_rows, validate_row
from generate_dataset import (
    export_reviewed, generate_candidates, load_ledger, read_candidates,
    replace_candidates, review_candidates, review_status, write_jsonl,
)
from prepare_dataset import prepare


def answers(*values):
    iterator = iter(values)
    return lambda prompt: next(iterator)


@pytest.fixture
def candidates(tmp_path):
    rows = generate_candidates(10)
    source, ledger = tmp_path / "candidates.jsonl", tmp_path / "reviews.json"
    write_jsonl(source, rows)
    return rows, source, ledger


def test_500_candidates_have_grounded_schema_and_blank_reviews():
    rows = generate_candidates()
    assert rows == generate_candidates(seed=42)
    assert rows != generate_candidates(seed=43)
    assert len(rows) == len({r["id"] for r in rows}) == len({r["report"] for r in rows}) == 500
    assert Counter(r["ticket"]["product_area"] for r in rows) == dict.fromkeys(
        ["Authentication", "Billing", "Dashboard", "Integrations", "Unknown"], 100)
    assert len(Counter(r["family_id"] for r in rows)) == 50
    assert set(Counter(r["family_id"] for r in rows).values()) == {10}
    for row in rows:
        validate_row(row, require_review=False)
        assert row["reviewed_by"] == row["reviewed_at"] == ""
        with pytest.raises(ValueError, match="human review"):
            validate_row(row)
        ticket = row["ticket"]
        assert len(ticket["follow_up_questions"]) <= 3
        assert (ticket["expected_behavior"] is None) == (ticket["expected_behavior_basis"] == "Unknown")
        for step in ticket["reported_steps"] or []:
            assert step in row["report"]
        for field in ("browser", "browser_version", "operating_system", "app_version"):
            value = ticket["reported_environment"][field]
            assert value is None or value in row["report"]
        assert "severity" not in ticket and "root_cause" not in ticket


@pytest.mark.parametrize("count", [0, -5, 501, 505, 12])
def test_generation_rejects_unsupported_counts(count):
    with pytest.raises(ValueError, match="Count must"):
        generate_candidates(count)


def test_review_resume_and_export_keep_candidates_unreviewed(candidates, tmp_path):
    rows, source, ledger = candidates
    status = review_candidates(source, ledger, "TEST FIXTURE ONLY", ask=answers(
        "a", f"APPROVE {rows[0]['id']}", "", "r", "Needs a clearer target", "s", "q"))
    assert status == {"approved": 1, "rejected": 1, "pending": 8, "stale": 0}
    assert read_candidates(source) == rows
    assert len(load_ledger(ledger, rows)["events"]) == 2
    # A resumed session skips both decided rows and starts with the skipped row.
    review_candidates(source, ledger, "SECOND TEST FIXTURE", limit=1, ask=answers(
        "a", f"APPROVE {rows[2]['id']}", "Reviewed test fixture"))
    output = tmp_path / "export.jsonl"
    assert export_reviewed(source, ledger, output, require_count=2) == 2
    approved = read_rows(output)
    assert [row["id"] for row in approved] == [rows[0]["id"], rows[2]["id"]]
    for row in approved:
        validate_row(row)
    with pytest.raises(FileExistsError):
        export_reviewed(source, ledger, output)
    with pytest.raises(ValueError, match="Need 500 approved"):
        export_reviewed(source, ledger, tmp_path / "incomplete.jsonl", require_count=500)
    assert not (tmp_path / "incomplete.jsonl").exists()


def test_incorrect_confirmation_and_empty_rejection_are_not_decisions(candidates):
    rows, source, ledger = candidates
    result = review_candidates(source, ledger, "TEST FIXTURE ONLY", ask=answers(
        "a", "APPROVE WRONG-ID", "r", "", "q"))
    assert result == {"approved": 0, "rejected": 0, "pending": 10, "stale": 0}
    assert not ledger.exists()


def test_edit_invalidates_approval_and_rereview_preserves_history(candidates, tmp_path):
    rows, source, ledger = candidates
    review_candidates(source, ledger, "TEST FIXTURE ONLY", limit=1, ask=answers(
        "a", f"APPROVE {rows[0]['id']}", ""))
    edited = copy.deepcopy(rows)
    edited[0]["report"] += " Additional synthetic context."
    edited[0]["family_id"] += "-corrected"
    replace_candidates(source, edited)
    assert review_status(edited, load_ledger(ledger, edited))["stale"] == 1
    with pytest.raises(ValueError, match="changed after approval"):
        export_reviewed(source, ledger, tmp_path / "stale.jsonl")
    review_candidates(source, ledger, "SECOND TEST FIXTURE", limit=1, ask=answers(
        "a", f"APPROVE {rows[0]['id']}", "Checked edited version"))
    events = load_ledger(ledger, edited)["events"]
    assert len(events) == 2 and events[0]["sha256"] != events[1]["sha256"]
    output = tmp_path / "current.jsonl"
    export_reviewed(source, ledger, output)
    assert read_rows(output)[0]["reviewed_by"] == "SECOND TEST FIXTURE"


def test_interactive_edit_validates_and_then_requires_approval(candidates):
    rows, source, ledger = candidates
    actions = iter(["e", "edit", "a", f"APPROVE {rows[0]['id']}", ""])

    def ask(prompt):
        action = next(actions)
        if action == "edit":
            edit_path, = source.parent.glob("review-edit-*.json")
            value = json.loads(edit_path.read_text(encoding="utf-8"))
            value["ticket"]["title"] = "Human-edited test fixture title"
            edit_path.write_text(json.dumps(value), encoding="utf-8")
            return ""
        return action

    review_candidates(source, ledger, "TEST FIXTURE ONLY", limit=1, ask=ask)
    revised = read_candidates(source)
    assert revised[0]["ticket"]["title"] == "Human-edited test fixture title"
    assert review_status(revised, load_ledger(ledger, revised))["approved"] == 1
    assert not list(source.parent.glob("review-edit-*.json"))


def test_pending_data_and_noninteractive_review_cannot_export(candidates, tmp_path):
    rows, source, ledger = candidates
    with pytest.raises(ValueError, match="No approved"):
        export_reviewed(source, ledger, tmp_path / "empty.jsonl")
    result = subprocess.run([
        sys.executable, str(Path(__file__).resolve().parents[2] / "ml/generate_dataset.py"),
        "review", "--reviewer", "TEST FIXTURE ONLY", "--candidates", str(source), "--reviews", str(ledger),
    ], input="a\n", text=True, capture_output=True)
    assert result.returncode == 2 and "interactive terminal" in result.stderr
    assert not ledger.exists() and not (tmp_path / "empty.jsonl").exists()
    with pytest.raises(FileExistsError):
        write_jsonl(source, rows)


def test_500_split_contract_family_isolation_and_frozen_hash(tmp_path):
    # Simulated reviewer metadata ONLY for validating the split machinery.
    rows = [row | {"reviewed_by": "TEST FIXTURE ONLY", "reviewed_at": "2026-01-01T00:00:00Z"}
            for row in generate_candidates()]
    source, destination = tmp_path / "reviewed.jsonl", tmp_path / "splits"
    write_jsonl(source, rows)
    prepare(source, destination, counts={"train": 400, "validation": 50, "test": 50})
    splits = load_splits(destination)
    assert [len(splits[key]) for key in ("train", "validation", "test")] == [400, 50, 50]
    families = [{row["family_id"] for row in split} for split in splits.values()]
    assert sum(len(group) for group in families) == len(set.union(*families)) == 50
    with pytest.raises(ValueError, match="already contains"):
        prepare(source, destination, counts={"train": 400, "validation": 50, "test": 50})
    test_path = destination / "test.jsonl"
    frozen = read_rows(test_path)
    frozen[0]["ticket"]["title"] = "Modified frozen test fixture"
    test_path.write_text("".join(json.dumps(row) + "\n" for row in frozen), encoding="utf-8")
    with pytest.raises(ValueError, match="changed after freezing"):
        load_splits(destination)
