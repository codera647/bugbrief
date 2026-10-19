import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ml"))
from dataset import load_splits, validate_row
from prepare_dataset import prepare
from train import encode_example
from app.inference import examples


def row(index=0):
    sample = examples()[0]
    return {"id": str(index), "family_id": str(index//2), "report": sample["report"] + f" Synthetic scenario {index}.", "ticket": copy.deepcopy(sample["ticket"]), "source": "synthetic", "reviewed_by": "TEST FIXTURE ONLY", "reviewed_at": "2026-01-01T00:00:00Z"}


def test_dataset_rejects_unreviewed_rows_and_freezes_families(tmp_path):
    with pytest.raises(ValueError, match="human review"):
        validate_row(row() | {"reviewed_by": ""})
    source = tmp_path / "input.jsonl"
    source.write_text("".join(json.dumps(row(i)) + "\n" for i in range(400)), encoding="utf-8")
    prepare(source, tmp_path / "splits")
    splits = load_splits(tmp_path / "splits")
    assert [len(splits[s]) for s in ("train", "validation", "test")] == [300,50,50]
    assert len({r["family_id"] for rows in splits.values() for r in rows}) == 200
    with pytest.raises(ValueError, match="already contains"): prepare(source, tmp_path / "splits")


def test_training_loss_masks_prompt_and_rejects_truncation():
    class Tokenizer:
        def apply_chat_template(self, messages, **options):
            return [1,2,3] if len(messages) == 2 else [1,2,3,4,5,6]
    result = encode_example(Tokenizer(), row())
    assert result["labels"] == [-100,-100,-100,4,5,6]
    with pytest.raises(ValueError, match="token budget"): encode_example(Tokenizer(), row(), max_length=5)
