"""Verify the downloaded v2 artifact and select it without printing credentials."""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import dotenv_values, set_key
from app.artifacts import load_profile


def main():
    profile, _ = load_profile("models/v2.json")
    path = ROOT / "backend/.env"
    if not path.exists():
        shutil.copyfile(ROOT / "backend/.env.example", path)
    backup = ROOT / "backend/.env.pre-v2"
    if not backup.exists():
        shutil.copyfile(path, backup)
    current = dotenv_values(path)
    values = {"INFERENCE_MODE": "transformers", "MODEL_PROFILE_PATH": "models/v2.json",
              "MODEL_ID": profile["model"], "MODEL_REVISION": profile["revision"],
              "MODEL_DEVICE": "cpu", "MODEL_CPU_THREADS": "2", "CONSTRAINED_OUTPUT": "true",
              "MODEL_CPU_QUANTIZATION": "none",
              "GENERATION_TIMEOUT_SECONDS": "600"}
    for name, value in values.items():
        set_key(str(path), name, value)
    print("Selected BugBrief v2 with constrained JSON and float32 on CPU. Existing auth/database settings were preserved.")
    print("Access mode:", current.get("BUGBRIEF_MODE", "production"))
    print("Run npm.cmd run dev in PowerShell, then open http://127.0.0.1:5173. Wait for model readiness before drafting.")


if __name__ == "__main__":
    main()
