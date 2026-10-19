"""QLoRA SFT on validated synthetic data; run on a Colab/Kaggle CUDA GPU."""
import argparse
import json
import re
import subprocess
from pathlib import Path

from dataset import COUNTS, ROOT, file_digest, load_splits
from app.inference import messages_for


def encode_example(tokenizer, row, max_length=2816):
    prompt = messages_for(row["report"])
    prefix = tokenizer.apply_chat_template(prompt, tokenize=True, add_generation_prompt=True, return_dict=False)
    full = tokenizer.apply_chat_template(prompt + [{"role": "assistant", "content": json.dumps(row["ticket"], ensure_ascii=False, separators=(",", ":"))}], tokenize=True, add_generation_prompt=False, return_dict=False)
    if full[:len(prefix)] != prefix:
        raise ValueError("The chat template changed; verify assistant-only loss boundaries")
    if len(prefix) > 2048 or len(full)-len(prefix) > 768 or len(full) > max_length:
        raise ValueError(f"Example {row['id']} exceeds the serving token budget; shorten it without dropping facts")
    return {"input_ids": full, "attention_mask": [1] * len(full), "labels": [-100] * len(prefix) + full[len(prefix):]}


def main(args):
    if args.epochs <= 0 or args.max_steps == 0 or args.max_steps < -1:
        raise ValueError("Epochs must be positive; max steps must be -1 or a positive integer")
    splits = load_splits(args.data, allow_bulk_approved=args.allow_bulk_approved, allow_corrected_synthetic=args.allow_corrected_synthetic)
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        raise ValueError("--revision must be the exact 40-character Hugging Face model commit")
    output = Path(args.output)
    if output.exists() and any(output.iterdir()) and not args.resume:
        raise ValueError("Use an empty output directory for this run")
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, Trainer, TrainingArguments, set_seed
    from transformers.trainer_utils import get_last_checkpoint

    if not torch.cuda.is_available():
        raise RuntimeError("QLoRA training needs a CUDA GPU; select a GPU runtime in Colab or Kaggle")
    dataset_manifest = json.loads((Path(args.data) / "manifest.json").read_text(encoding="utf-8"))
    config = {"model": args.model, "model_revision": args.revision, "epochs": args.epochs, "max_steps": args.max_steps,
              "dataset_sha256": {s: file_digest(Path(args.data) / f"{s}.jsonl") for s in COUNTS},
              "data_policy": dataset_manifest.get("data_policy", "individually_reviewed"),
              "training_code_sha256": file_digest(__file__),
              "prompt_sha256": __import__('hashlib').sha256(json.dumps(messages_for(""), sort_keys=True).encode()).hexdigest()}
    checkpoint = None
    if args.resume:
        if not (output / "planned-run.json").exists() or json.loads((output / "planned-run.json").read_text()) != config:
            raise ValueError("Resume requires the same model, data, prompt, and training configuration")
        checkpoint = get_last_checkpoint(str(output))
        if checkpoint is None:
            raise ValueError("No checkpoint found to resume; use a new empty run directory")
    output.mkdir(parents=True, exist_ok=True)
    (output / "planned-run.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    set_seed(42)
    bf16 = torch.cuda.is_bf16_supported()
    dtype = torch.bfloat16 if bf16 else torch.float16
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision, trust_remote_code=False)
    tokenizer.pad_token = tokenizer.eos_token
    train = [encode_example(tokenizer, row) for row in splits["train"]]
    validation = [encode_example(tokenizer, row) for row in splits["validation"]]
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=dtype)
    model = AutoModelForCausalLM.from_pretrained(args.model, revision=args.revision, quantization_config=quantization, device_map={"": 0}, torch_dtype=dtype, attn_implementation="sdpa", trust_remote_code=False)
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=.05, target_modules="all-linear", bias="none", task_type="CAUSAL_LM"))

    def collate(features):
        width = max(len(f["input_ids"]) for f in features)
        return {key: torch.tensor([f[key] + [tokenizer.pad_token_id if key == "input_ids" else -100 if key == "labels" else 0] * (width-len(f[key])) for f in features]) for key in ("input_ids", "attention_mask", "labels")}

    settings = TrainingArguments(output_dir=str(output), num_train_epochs=args.epochs, max_steps=args.max_steps, learning_rate=2e-4, per_device_train_batch_size=1, per_device_eval_batch_size=1, gradient_accumulation_steps=8, gradient_checkpointing=True, gradient_checkpointing_kwargs={"use_reentrant": False}, bf16=bf16, fp16=not bf16, eval_strategy="steps", eval_steps=25, save_strategy="steps", save_steps=25, save_total_limit=2, load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False, prediction_loss_only=True, label_names=["labels"], logging_steps=5, report_to="none", seed=42, data_seed=42, optim="paged_adamw_8bit", warmup_ratio=.05, weight_decay=.01, remove_unused_columns=False)
    trainer = Trainer(model=model, args=settings, train_dataset=train, eval_dataset=validation, data_collator=collate, processing_class=tokenizer)
    trainer.train(resume_from_checkpoint=checkpoint)
    adapter = output / "adapter"
    trainer.save_model(str(adapter)); tokenizer.save_pretrained(str(adapter))
    manifest = {**config, "prompt_version": "1.0", "schema_version": "1.0", "dataset_counts": {s: len(rows) for s, rows in splits.items()}, "training": settings.to_dict(), "gpu": torch.cuda.get_device_name(0), "evaluation": trainer.evaluate(), "packages": subprocess.check_output([__import__('sys').executable, "-m", "pip", "freeze"], text=True).splitlines()}
    (output / "run.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print("Adapter saved locally. Compare it with the base-model prompt before release.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True); parser.add_argument("--revision", required=True)
    parser.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct"); parser.add_argument("--output", default=str(ROOT / "ml/artifacts/run-01"))
    parser.add_argument("--allow-bulk-approved", action="store_true", help="Train the explicitly bulk-approved synthetic experiment; no individual review is claimed")
    parser.add_argument("--allow-corrected-synthetic", action="store_true", help="Use the traceable AI-corrected dataset; no individual human review is claimed")
    parser.add_argument("--resume", action="store_true", help="Resume the most recent saved checkpoint with matching configuration")
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--max-steps", type=int, default=-1, help="Positive value for a short GPU smoke run; -1 uses epochs")
    main(parser.parse_args())
