"""Reviewed synthetic data contract and leakage checks. No GPU dependencies."""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.domain import Ticket

COUNTS = {"train": 300, "validation": 50, "test": 50}


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def candidate_digest(row):
    content = {key: value for key, value in row.items() if key not in {"reviewed_by", "reviewed_at"}}
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def validate_bulk_approval(rows, approval, source_path):
    """Validate recorded batch acceptance without inventing individual reviews."""
    check_unique(rows, require_review=False)
    if any(row["reviewed_by"] or row["reviewed_at"] for row in rows):
        raise ValueError("Bulk-approved candidates must keep individual reviewer fields blank")
    if (approval.get("approval_type") != "user_bulk_approval"
            or approval.get("individual_human_review_verified") is not False
            or not approval.get("approved_by") or not approval.get("instruction")
            or approval.get("approved_count") != len(rows)
            or approval.get("export_sha256") != file_digest(source_path)):
        raise ValueError("Bulk approval provenance does not match the source dataset")
    if datetime.fromisoformat(approval["approved_at"]).tzinfo is None:
        raise ValueError("Bulk approval timestamp must include a timezone")
    events = approval.get("examples", [])
    if len(events) != len(rows) or len({event["id"] for event in events}) != len(rows):
        raise ValueError("Bulk approval must cover each candidate exactly once")
    decisions = {event["id"]: event for event in events}
    for row in rows:
        event = decisions.get(row["id"], {})
        if event.get("decision") != "approved" or event.get("sha256") != candidate_digest(row):
            raise ValueError("A candidate changed after user bulk approval")


def validate_row(row, *, require_review=True):
    required = {"id", "family_id", "report", "ticket", "source", "reviewed_by", "reviewed_at"}
    if set(row) != required:
        raise ValueError("Each dataset row must contain exactly: " + ", ".join(sorted(required)))
    for field in ("id", "family_id", "report"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"{row.get('id', 'row')}: {field} is missing")
    for field in ("reviewed_by", "reviewed_at"):
        if not isinstance(row[field], str) or (require_review and not row[field].strip()):
            raise ValueError(f"{row.get('id', 'row')}: {field} is missing; human review is required")
    if bool(row["reviewed_by"].strip()) != bool(row["reviewed_at"].strip()):
        raise ValueError("Supply both reviewer and review timestamp, or leave both blank")
    if row["source"] != "synthetic" or not 10 <= len(row["report"]) <= 4000:
        raise ValueError("Use synthetic reports between 10 and 4,000 characters")
    if row["reviewed_at"]:
        reviewed = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
        if reviewed.tzinfo is None:
            raise ValueError("reviewed_at must include a timezone")
    Ticket.model_validate(row["ticket"]).check_source(row["report"])


def check_unique(rows, *, require_review=True):
    ids, reports = set(), set()
    for row in rows:
        validate_row(row, require_review=require_review)
        normalized = " ".join(row["report"].casefold().split())
        if row["id"] in ids or normalized in reports:
            raise ValueError("Duplicate row ID or report; remove duplicate examples before splitting")
        ids.add(row["id"]); reports.add(normalized)


def load_splits(directory, *, allow_bulk_approved=False, allow_corrected_synthetic=False):
    counts = COUNTS
    manifest_path = Path(directory) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    if "counts" in manifest:
        counts = validate_counts(manifest["counts"])
    policy = manifest.get("data_policy", "individually_reviewed")
    if policy not in {"individually_reviewed", "user_bulk_approved_synthetic", "ai_corrected_synthetic"}:
        raise ValueError("Unsupported dataset approval policy")
    bulk = policy == "user_bulk_approved_synthetic"
    corrected = policy == "ai_corrected_synthetic"
    if bulk and not allow_bulk_approved:
        raise ValueError("This dataset has user bulk approval, not individual review; pass --allow-bulk-approved for this experiment")
    if corrected and not allow_corrected_synthetic:
        raise ValueError("This dataset has AI corrections, not individual human review; pass --allow-corrected-synthetic for this experiment")
    result, seen_families, all_rows = {}, set(), []
    for split, count in counts.items():
        path = Path(directory) / f"{split}.jsonl"
        rows = read_rows(path)
        if len(rows) != count:
            raise ValueError(f"{split} requires {count} examples; found {len(rows)}")
        if (bulk or corrected) and split not in manifest.get("sha256", {}):
            raise ValueError("Synthetic experimental splits require frozen file hashes")
        if split in manifest.get("sha256", {}) and file_digest(path) != manifest["sha256"][split]:
            raise ValueError(f"{split} changed after freezing; prepare a new dataset version")
        families = {r["family_id"] for r in rows}
        if families & seen_families:
            raise ValueError("A scenario family appears in more than one split")
        seen_families |= families; all_rows.extend(rows); result[split] = rows
    check_unique(all_rows, require_review=not (bulk or corrected))
    if bulk:
        source_path = Path(directory) / "bulk-approved.jsonl"
        approval_path = Path(directory) / "bulk-approval.json"
        source = read_rows(source_path)
        validate_bulk_approval(source, json.loads(approval_path.read_text(encoding="utf-8")), source_path)
        if {r["id"]: r for r in source} != {r["id"]: r for r in all_rows}:
            raise ValueError("Frozen splits do not match the bulk-approved source")
    if corrected:
        validate_corrections(Path(directory), all_rows, manifest)
    return result


def validate_corrections(directory, rows, manifest):
    path = directory / "corrections.json"
    if file_digest(path) != manifest.get("corrections_sha256"):
        raise ValueError("Correction history changed after freezing")
    correction = json.loads(path.read_text(encoding="utf-8"))
    split_ids = correction.get("split_ids", {})
    if set(split_ids) != set(COUNTS) or any(
            split_ids[name] != [row["id"] for row in read_rows(directory / f"{name}.jsonl")]
            for name in COUNTS):
        raise ValueError("Corrected split membership differs from the recorded parent assignment")
    source_path = directory / "corrected.jsonl"
    parent_path = directory / "parent-bulk-approved.jsonl"
    parent_approval = directory / "parent-bulk-approval.json"
    if (correction.get("version") != 2 or correction.get("individual_human_review_verified") is not False
            or file_digest(source_path) != correction.get("corrected_source_sha256")
            or file_digest(parent_path) != correction.get("parent_source_sha256")
            or file_digest(parent_approval) != correction.get("parent_approval_sha256")):
        raise ValueError("Corrected dataset provenance does not match its files")
    source, parent = read_rows(source_path), read_rows(parent_path)
    validate_bulk_approval(parent, json.loads(parent_approval.read_text(encoding="utf-8")), parent_path)
    check_unique(source, require_review=False)
    if any(row["reviewed_by"] or row["reviewed_at"] for row in source):
        raise ValueError("AI corrections must not invent individual reviewer metadata")
    if {r["id"]: r for r in source} != {r["id"]: r for r in rows}:
        raise ValueError("Frozen splits do not match the corrected source")
    parents = {row["id"]: row for row in parent}
    if set(parents) != {row["id"] for row in source}:
        raise ValueError("Corrected dataset IDs differ from the parent")
    expected_changes = {}
    for row in source:
        old = parents[row["id"]]
        if any(row[k] != old[k] for k in ("report", "family_id", "source", "reviewed_by", "reviewed_at")):
            raise ValueError("Correction changed original source reports or review metadata")
        fields = {key: {"before": old["ticket"][key], "after": row["ticket"][key]}
                  for key in row["ticket"] if row["ticket"][key] != old["ticket"][key]}
        if fields:
            expected_changes[row["id"]] = {"id": row["id"], "before_sha256": candidate_digest(old), "after_sha256": candidate_digest(row), "fields": fields}
    changes = correction.get("changes", [])
    if (len(changes) != len(expected_changes) or correction.get("changed_rows") != len(expected_changes)
            or {item["id"]: item for item in changes} != expected_changes):
        raise ValueError("Correction history does not describe the actual target changes")


def validate_counts(counts):
    if not isinstance(counts, dict) or set(counts) != set(COUNTS):
        raise ValueError("Split counts must specify train, validation, and test")
    if any(type(value) is not int or value <= 0 for value in counts.values()):
        raise ValueError("Each split count must be a positive integer")
    return {split: counts[split] for split in COUNTS}


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
