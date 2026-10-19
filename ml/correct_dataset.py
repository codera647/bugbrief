"""Create a traceable v2 of the original 500 reports without changing split membership."""
import argparse
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dataset import ROOT, candidate_digest, file_digest, load_splits, read_rows, check_unique
from generate_dataset import GENERATOR_VERSION, expectation_basis, generate_candidates, write_jsonl
from scenarios import SCENARIOS

DEFAULT_OUTPUT = ROOT / "ml/data/colab-splits-500-v2"
POLICY = "Reported requires an explicitly stated expectation. Infer only a concrete conventional outcome supported by the identified action or feature. For an unspecified page/button/list/message without a concrete intended result, use Unknown and null. Browser, OS, app version, and timing do not determine the label."


def audit_candidates(rows):
    """Check authored targets against their source and catalog; not a human review."""
    check_unique(rows, require_review=False)
    catalog = {f"{area.lower()}-{s.key}": (area, s) for area, scenarios in SCENARIOS.items() for s in scenarios}
    for row in rows:
        area, scenario = catalog[row["family_id"]]
        report, ticket = row["report"], row["ticket"]
        explicitly_reported = "I expected to " in report
        expected_basis = expectation_basis(scenario, explicitly_reported=explicitly_reported)
        if ticket["expected_behavior_basis"] != expected_basis:
            raise ValueError(f"{row['id']}: expectation label contradicts the report/policy")
        if ticket["title"] != scenario.title or ticket["product_area"] != area:
            raise ValueError(f"{row['id']}: title or product area differs from authored source scenario")
        actual = scenario.symptom
        for clause in ("I first noticed this today.", "I first noticed this yesterday.",
                       "I tried three times, and it happened on each attempt.",
                       "It happened once; I have not tried again.", "It happened on two of five attempts."):
            if clause in report:
                actual += " " + clause
        if scenario.symptom not in report or ticket["actual_behavior"] != actual:
            raise ValueError(f"{row['id']}: actual behavior contains unsupported facts")
        supplied_steps = "Here is what I did: " in report
        if supplied_steps != (ticket["reported_steps"] is not None):
            raise ValueError(f"{row['id']}: steps were invented or omitted")
        if any(step not in report for step in ticket["reported_steps"] or []):
            raise ValueError(f"{row['id']}: step not present in source")
        environment = ticket["reported_environment"]
        for field in ("browser", "browser_version", "operating_system", "app_version"):
            if environment[field] is not None and environment[field] not in report:
                raise ValueError(f"{row['id']}: unsupported environment field")
        allowed_other = ["Test workspace"] if "This is a test workspace." in report else []
        if environment["other_details"] != allowed_other:
            raise ValueError(f"{row['id']}: unsupported other environment details")
        if explicitly_reported and "Expected result" in ticket["missing_information"]:
            raise ValueError(f"{row['id']}: asks for an already reported expectation")
        if supplied_steps and "Actions leading to the issue" in ticket["missing_information"]:
            raise ValueError(f"{row['id']}: asks for already supplied steps")


def correct_dataset(output=DEFAULT_OUTPUT, parent=ROOT / "ml/data/colab-splits-500"):
    output, parent = Path(output), Path(parent)
    if output.exists():
        raise ValueError("Correction output already exists; choose a new dataset version")
    original = load_splits(parent, allow_bulk_approved=True)
    rows = generate_candidates(500, seed=42)
    audit_candidates(rows)
    by_id = {row["id"]: row for row in rows}
    originals = {row["id"]: row for group in original.values() for row in group}
    if set(by_id) != set(originals):
        raise ValueError("The correction must cover exactly the original example IDs")
    edits = []
    for row in rows:
        before = originals[row["id"]]
        if any(row[field] != before[field] for field in ("report", "family_id", "source", "reviewed_by", "reviewed_at")):
            raise ValueError("Only ticket targets may change in this dataset correction")
        changes = {field: {"before": before["ticket"][field], "after": row["ticket"][field]}
                   for field in row["ticket"] if row["ticket"][field] != before["ticket"][field]}
        if changes:
            edits.append({"id": row["id"], "before_sha256": candidate_digest(before), "after_sha256": candidate_digest(row), "fields": changes})
    output.mkdir(parents=True)
    write_jsonl(output / "corrected.jsonl", rows)
    shutil.copyfile(parent / "bulk-approved.jsonl", output / "parent-bulk-approved.jsonl")
    shutil.copyfile(parent / "bulk-approval.json", output / "parent-bulk-approval.json")
    correction = {"version": 2, "generator": GENERATOR_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                  "method": "AI-authored corrections with automated source and schema checks",
                  "user_instruction": "correct the dataset", "individual_human_review_verified": False,
                  "policy": POLICY, "source_reports_unchanged": True, "split_membership_unchanged": True,
                  "parent_source_sha256": file_digest(output / "parent-bulk-approved.jsonl"),
                  "parent_approval_sha256": file_digest(output / "parent-bulk-approval.json"),
                  "parent_split_sha256": {name: file_digest(parent / f"{name}.jsonl") for name in original},
                  "split_ids": {name: [row["id"] for row in group] for name, group in original.items()},
                  "corrected_source_sha256": file_digest(output / "corrected.jsonl"),
                  "changed_rows": len(edits), "changes": edits}
    (output / "corrections.json").write_text(json.dumps(correction, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    basis_counts = {}
    for name, old_rows in original.items():
        values = [by_id[row["id"]] for row in old_rows]
        write_jsonl(output / f"{name}.jsonl", values)
        basis_counts[name] = dict(Counter(row["ticket"]["expected_behavior_basis"] for row in values))
    manifest = {"seed": 42, "version": 2, "counts": {name: len(group) for name, group in original.items()},
                "data_policy": "ai_corrected_synthetic", "stratified_by_area": True,
                "sha256": {name: file_digest(output / f"{name}.jsonl") for name in original},
                "corrections_sha256": file_digest(output / "corrections.json"), "basis_counts": basis_counts}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    load_splits(output, allow_corrected_synthetic=True)
    print(json.dumps({"output": str(output), "changed_rows": len(edits), "basis_counts": basis_counts}, indent=2))
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--parent", type=Path, default=ROOT / "ml/data/colab-splits-500")
    args = parser.parse_args()
    correct_dataset(args.output, args.parent)
