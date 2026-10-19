"""Compare greedy base-model and adapter outputs on the same frozen split."""
import argparse
import json
import re
import time
from pathlib import Path

from dataset import ROOT, load_splits
from app.domain import Ticket
from app.inference import messages_for


def main(args):
    rows = load_splits(args.data, allow_bulk_approved=args.allow_bulk_approved, allow_corrected_synthetic=args.allow_corrected_synthetic)[args.split]
    if args.limit is not None:
        if args.split == "test" or args.limit <= 0:
            raise ValueError("--limit must be positive and is only supported on validation")
        rows = rows[:args.limit]
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("Pin the base model to a 40-character commit")
    path = Path(args.output)
    if path.exists():
        raise ValueError("Results already exist; use a new output filename")
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=args.revision, torch_dtype=dtype, device_map="auto", trust_remote_code=False)
    # Evaluating the adapter and baseline on the same weights/dtype avoids quantization confounds.
    model = PeftModel.from_pretrained(model, args.adapter)
    model.eval(); results = []
    path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the filename and retain each completed comparison if Colab stops.
    with path.open("x", encoding="utf-8"):
        pass
    for row in rows:
        inputs = tokenizer.apply_chat_template(messages_for(row["report"]), tokenize=True, add_generation_prompt=True, return_tensors="pt", return_dict=True).to(model.device)
        if inputs["input_ids"].shape[-1] > 2048:
            raise ValueError(f"Input too long: {row['id']}")
        for variant in ("baseline", "adapter"):
            started = time.monotonic()
            with torch.inference_mode():
                if variant == "baseline":
                    with model.disable_adapter(): output = model.generate(**inputs, do_sample=False, max_new_tokens=768, pad_token_id=tokenizer.eos_token_id)
                else: output = model.generate(**inputs, do_sample=False, max_new_tokens=768, pad_token_id=tokenizer.eos_token_id)
            text = tokenizer.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True).strip()
            valid, area_correct, basis_correct, issue = False, None, None, None
            try:
                candidate = Ticket.model_validate_json(text); candidate.check_source(row["report"])
                valid = True
                area_correct = candidate.product_area == row["ticket"]["product_area"]
                basis_correct = candidate.expected_behavior_basis == row["ticket"]["expected_behavior_basis"]
            except ValueError:
                issue = "invalid_schema_or_evidence"
            results.append({"id": row["id"], "variant": variant, "report": row["report"], "reference": row["ticket"], "output": text, "seconds": time.monotonic()-started, "valid": valid, "area_correct": area_correct, "basis_correct": basis_correct, "issue": issue, "human_review": {"unsupported_claims": None, "missing_facts": None, "question_quality": None, "edit_minutes": None, "reviewer": None}})
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(results[-1], ensure_ascii=False) + "\n")
            print(f"{len(results)}/{2 * len(rows)} {row['id']} {variant}: valid={valid}", flush=True)
    for variant in ("baseline", "adapter"):
        selected = [r for r in results if r["variant"] == variant]
        print(variant, "valid:", sum(r["valid"] for r in selected), "/",len(selected), "area correct:",sum(r["area_correct"] is True for r in selected), "basis correct:",sum(r["basis_correct"] is True for r in selected))
    print("Automatic scores do not measure factual fidelity. Complete the human review fields.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True); parser.add_argument("--revision", required=True); parser.add_argument("--adapter", required=True)
    parser.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct"); parser.add_argument("--split", choices=["validation", "test"], default="validation"); parser.add_argument("--output", required=True)
    parser.add_argument("--allow-bulk-approved", action="store_true")
    parser.add_argument("--allow-corrected-synthetic", action="store_true")
    parser.add_argument("--limit", type=int, help="Optional validation subset for a quick smoke check")
    main(parser.parse_args())
