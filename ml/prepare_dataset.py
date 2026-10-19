"""Freeze configurable splits, defaulting to 300/50/50, with scenario families intact."""
import argparse
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

from dataset import COUNTS, check_unique, file_digest, load_splits, read_rows, validate_bulk_approval, validate_counts


def subset(groups, size):
    choices = {0: []}
    for family, rows in groups.items():
        for total, selected in list(choices.items()):
            candidate = total + len(rows)
            if candidate <= size and candidate not in choices:
                choices[candidate] = selected + [family]
    if size not in choices:
        raise ValueError("Scenario families cannot fit the exact split counts; adjust group sizes")
    return choices[size]


def split_rows(rows, counts):
    groups = defaultdict(list)
    for row in rows:
        groups[row["family_id"]].append(row)
    splits = {}
    for name in ("test", "validation"):
        selected = subset(groups, counts[name])
        splits[name] = [row for family in selected for row in groups.pop(family)]
    splits["train"] = [row for group in groups.values() for row in group]
    return splits


def prepare(input_path, output_path, seed=42, *, counts=None, bulk_approval=None, stratify_by_area=False):
    counts = validate_counts(counts if counts is not None else COUNTS)
    rows = read_rows(input_path)
    if len(rows) != sum(counts.values()):
        raise ValueError(f"This split requires {sum(counts.values())} examples; found {len(rows)}")
    if bulk_approval is not None:
        approval = json.loads(Path(bulk_approval).read_text(encoding="utf-8"))
        validate_bulk_approval(rows, approval, input_path)
    else:
        check_unique(rows)
    random.Random(seed).shuffle(rows)
    if stratify_by_area:
        areas = sorted({row["ticket"]["product_area"] for row in rows})
        family_areas = defaultdict(set)
        for row in rows:
            family_areas[row["family_id"]].add(row["ticket"]["product_area"])
        if any(len(values) != 1 for values in family_areas.values()):
            raise ValueError("Area stratification requires each family to belong to one product area")
        if any(count % len(areas) for count in counts.values()):
            raise ValueError("Balanced split counts must divide evenly across product areas")
        splits = {name: [] for name in counts}
        for area in areas:
            area_rows = [row for row in rows if row["ticket"]["product_area"] == area]
            area_counts = {name: count // len(areas) for name, count in counts.items()}
            if len(area_rows) != sum(area_counts.values()):
                raise ValueError("Area stratification requires balanced source area counts")
            for name, values in split_rows(area_rows, area_counts).items():
                splits[name].extend(values)
        for values in splits.values():
            random.Random(seed).shuffle(values)
    else:
        splits = split_rows(rows, counts)
    output = Path(output_path)
    if (output / "manifest.json").exists() or any((output / f"{split}.jsonl").exists() for split in COUNTS):
        raise ValueError("Output already contains frozen splits; use a new directory")
    output.mkdir(parents=True, exist_ok=True)
    if bulk_approval is not None:
        shutil.copyfile(input_path, output / "bulk-approved.jsonl")
        shutil.copyfile(bulk_approval, output / "bulk-approval.json")
    for name, values in splits.items():
        (output / f"{name}.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in values), encoding="utf-8")
    manifest = {"seed": seed, "counts": counts, "sha256": {s: file_digest(output / f"{s}.jsonl") for s in COUNTS}, "data_policy": "user_bulk_approved_synthetic" if bulk_approval is not None else "individually_reviewed", "stratified_by_area": stratify_by_area}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    load_splits(output, allow_bulk_approved=bulk_approval is not None)
    print("Dataset validated and frozen. Approval policy:", manifest["data_policy"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input"); parser.add_argument("output"); parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-count", type=int, default=COUNTS["train"])
    parser.add_argument("--validation-count", type=int, default=COUNTS["validation"])
    parser.add_argument("--test-count", type=int, default=COUNTS["test"])
    parser.add_argument("--bulk-approval", type=Path, help="Explicit recorded user batch approval; does not create individual reviews")
    parser.add_argument("--stratify-by-area", action="store_true")
    args = parser.parse_args()
    prepare(args.input, args.output, args.seed, counts={"train": args.train_count, "validation": args.validation_count, "test": args.test_count}, bulk_approval=args.bulk_approval, stratify_by_area=args.stratify_by_area)
