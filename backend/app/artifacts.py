"""Pinned local adapter identity. Loading never executes training_args.bin."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_profile(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    profile = json.loads(path.read_text(encoding="utf-8"))
    required = {"version", "name", "status", "model", "revision", "adapter_path", "adapter_sha256", "adapter_config_sha256", "run_sha256", "prompt_sha256"}
    if not isinstance(profile, dict) or set(profile) != required or profile["version"] != 1 or profile["status"] != "experimental":
        raise ValueError("Unsupported model profile")
    for field in ("revision", "adapter_sha256", "adapter_config_sha256", "run_sha256", "prompt_sha256"):
        value = profile[field]
        length = 40 if field == "revision" else 64
        if not isinstance(value, str) or len(value) != length or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"Invalid {field} in model profile")
    adapter = (ROOT / profile["adapter_path"]).resolve()
    if file_hash(adapter / "adapter_model.safetensors") != profile["adapter_sha256"]:
        raise ValueError("Adapter weights differ from the pinned profile")
    if file_hash(adapter / "adapter_config.json") != profile["adapter_config_sha256"]:
        raise ValueError("Adapter configuration differs from the pinned profile")
    if file_hash(adapter.parent / "run.json") != profile["run_sha256"]:
        raise ValueError("Training run differs from the pinned profile")
    run = json.loads((adapter.parent / "run.json").read_text(encoding="utf-8"))
    config = json.loads((adapter / "adapter_config.json").read_text(encoding="utf-8"))
    if run["model"] != profile["model"] or config["base_model_name_or_path"] != profile["model"] or run["model_revision"] != profile["revision"]:
        raise ValueError("Adapter and base-model identity do not match")
    if run["prompt_sha256"] != profile["prompt_sha256"]:
        raise ValueError("Profile prompt differs from the trained prompt")
    return profile, adapter
