import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mode: str = "production"
    inference_mode: str = "disabled"
    database: str = ".data/demo.sqlite3"
    supabase_url: str = ""
    supabase_key: str = ""
    origins: tuple[str, ...] = ("http://127.0.0.1:5173", "http://localhost:5173")
    model_id: str = "Qwen/Qwen2.5-1.5B-Instruct"
    model_revision: str = ""
    adapter_path: str = ""
    adapter_revision: str = ""
    generation_timeout: int = 180
    model_profile: str = ""
    model_device: str = "cpu"
    model_cpu_threads: int = 2
    constrained_output: bool = True
    model_cpu_quantization: str = "none"

    @classmethod
    def load(cls):
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        constrained = os.getenv("CONSTRAINED_OUTPUT", "true").lower()
        if constrained not in {"true", "false"}:
            raise ValueError("CONSTRAINED_OUTPUT must be true or false")
        result = cls(
            mode=os.getenv("BUGBRIEF_MODE", "production"),
            inference_mode=os.getenv("INFERENCE_MODE", "disabled"),
            database=os.getenv("DEMO_DATABASE", ".data/demo.sqlite3"),
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_key=os.getenv("SUPABASE_SECRET_KEY", ""),
            origins=tuple(x.strip() for x in os.getenv("ALLOWED_ORIGINS", ",".join(cls.origins)).split(",") if x.strip()),
            model_id=os.getenv("MODEL_ID", cls.model_id),
            model_revision=os.getenv("MODEL_REVISION", ""),
            adapter_path=os.getenv("ADAPTER_PATH", ""),
            adapter_revision=os.getenv("ADAPTER_REVISION", ""),
            generation_timeout=int(os.getenv("GENERATION_TIMEOUT_SECONDS", "180")),
            model_profile=os.getenv("MODEL_PROFILE_PATH", ""),
            model_device=os.getenv("MODEL_DEVICE", "cpu"),
            model_cpu_threads=int(os.getenv("MODEL_CPU_THREADS", "2")),
            constrained_output=constrained == "true",
            model_cpu_quantization=os.getenv("MODEL_CPU_QUANTIZATION", "none"),
        )
        if result.mode not in {"demo", "production"}:
            raise ValueError("BUGBRIEF_MODE must be demo or production")
        if result.inference_mode not in {"disabled", "examples", "transformers"}:
            raise ValueError("INFERENCE_MODE must be disabled, examples, or transformers")
        if result.mode == "production":
            if not result.supabase_url.startswith("https://") or not result.supabase_key:
                raise ValueError("Configure SUPABASE_URL and SUPABASE_SECRET_KEY in backend/.env")
            if result.inference_mode == "examples":
                raise ValueError("Synthetic example inference is only available in local demo mode")
        if "*" in result.origins:
            raise ValueError("ALLOWED_ORIGINS must list explicit origins")
        if result.model_device not in {"cpu", "cuda", "auto"} or not 1 <= result.model_cpu_threads <= 64:
            raise ValueError("Choose MODEL_DEVICE cpu/cuda/auto and MODEL_CPU_THREADS between 1 and 64")
        if not 10 <= result.generation_timeout <= 1800:
            raise ValueError("GENERATION_TIMEOUT_SECONDS must be between 10 and 1800")
        if result.model_cpu_quantization not in {"none", "int8"}:
            raise ValueError("MODEL_CPU_QUANTIZATION must be none or int8")
        return result
