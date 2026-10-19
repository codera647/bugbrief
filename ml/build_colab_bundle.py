"""Build the Colab notebook and an allowlisted, hashed training upload archive."""
import hashlib
import argparse
import json
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "ml/colab"
MODEL_REVISION = "989aa7980e4cf806f80c7fef2b1adb7bc71aa306"


def cell(kind, text):
    result = {"cell_type": kind, "metadata": {}, "source": textwrap.dedent(text).strip().splitlines(keepends=True)}
    if kind == "code":
        result.update(execution_count=None, outputs=[])
    return result


def notebook(version=1):
    md = lambda text: cell("markdown", text)
    code = lambda text: cell("code", text)
    cells = [
        md("""
        # BugBrief: fine-tune Qwen2.5-1.5B on a Colab GPU

        This notebook trains a 4-bit QLoRA adapter for turning fictional LedgerFlow reports into structured tickets.
        It includes 500 synthetic examples: **400 train / 50 validation / 50 test**, balanced across five product areas.
        The project user bulk-approved this batch. Individual human review is unverified; that provenance stays in the data and run manifest.
        There are 50 underlying scenario families, with ten variations each. Held-out families do not establish broad real-world quality.

        1. Select **Runtime → Change runtime type → GPU** (T4 if offered).
        2. Run the cells in order. Upload **BugBrief_Colab_Bundle.zip** when asked.
        3. Training runs a one-step smoke check, then three epochs. Download the adapter and results at the end.

        No Supabase `.env`, customer tickets, Hugging Face token, or paid API is needed. The base model is public.
        Free GPU availability and session duration vary. This notebook has been checked locally, but its GPU run has not been executed by the project author.
        """),
        md("""
        ## 1. Check the runtime
        If no GPU is available, reconnect later or try a Kaggle GPU session. Do not run QLoRA training on a CPU runtime.
        """),
        code("""
        import sys
        import torch
        assert sys.version_info >= (3, 10), "Use a current Colab Python runtime."
        assert torch.cuda.is_available(), "Select Runtime → Change runtime type → GPU, then reconnect."
        assert tuple(int(x) for x in torch.__version__.split('+')[0].split('.')[:2]) >= (2, 6), "Use a current Colab runtime with PyTorch 2.6+."
        gpu = torch.cuda.get_device_properties(0)
        print(f"Python {sys.version.split()[0]} | PyTorch {torch.__version__} | CUDA {torch.version.cuda}")
        print(f"GPU: {gpu.name} | VRAM: {gpu.total_memory / 2**30:.1f} GiB")
        if gpu.total_memory < 12 * 2**30:
            print("This GPU has less than 12 GiB. The smoke check will reveal whether this configuration fits.")
        """),
        md("""
        ## 2. Upload the training bundle
        Upload the provided ZIP, without unpacking it. You can also put it in `/content` with Colab's Files sidebar first.
        Only the small allowlisted training files are included; local secrets and app data are excluded.
        """),
        code("""
        import hashlib, io, json, zipfile
        from pathlib import Path, PurePosixPath
        ROOT = Path('/content/BugBrief_Colab')
        archive = Path('/content/BugBrief_Colab_Bundle.zip')
        if archive.exists():
            uploaded_bytes = archive.read_bytes()
        else:
            from google.colab import files
            uploads = files.upload()
            matches = [value for name, value in uploads.items() if name.endswith('.zip')]
            assert len(matches) == 1, "Upload exactly one BugBrief_Colab_Bundle.zip."
            uploaded_bytes = matches[0]
        with zipfile.ZipFile(io.BytesIO(uploaded_bytes)) as bundle:
            names = bundle.namelist()
            assert len(names) == len(set(names)), "Duplicate archive paths."
            assert sum(item.file_size for item in bundle.infolist()) < 25_000_000, "Unexpected archive size."
            manifest = json.loads(bundle.read('BugBrief_Colab/BUNDLE_MANIFEST.json'))
            expected = {'BugBrief_Colab/' + name for name in manifest['sha256']}
            assert set(names) == expected | {'BugBrief_Colab/BUNDLE_MANIFEST.json'}, "Unexpected bundle files."
            for name in names:
                path = PurePosixPath(name)
                assert not path.is_absolute() and '..' not in path.parts and '\\\\' not in name
                target = Path('/content').joinpath(*path.parts)
                assert target.resolve().is_relative_to(ROOT.resolve()), "Unsafe archive path."
                data = bundle.read(name)
                if name in expected:
                    relative = name.removeprefix('BugBrief_Colab/')
                    assert hashlib.sha256(data).hexdigest() == manifest['sha256'][relative], f"Changed bundle file: {relative}"
                if target.exists():
                    assert target.read_bytes() == data, f"Existing file differs: {target}. Start a fresh runtime."
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
        del uploaded_bytes
        print('Verified bundle extracted to', ROOT)
        """),
        md("""
        ## 3. Install the pinned training libraries
        This keeps Colab's existing CUDA PyTorch. Every training/evaluation job runs in a fresh Python process.
        If installation fails, read the pip error before continuing. If Colab requests a session restart, restart and rerun from the first cell.
        """),
        code("""
        import subprocess
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', '-r', str(ROOT / 'ml/requirements-colab.txt')], check=True)
        subprocess.run([sys.executable, '-c',
            "import torch, transformers, peft, accelerate, bitsandbytes, pydantic; "
            "print('torch', torch.__version__, 'transformers', transformers.__version__, 'peft', peft.__version__, 'bitsandbytes', bitsandbytes.__version__)"], check=True)
        """),
        md("""
        ## 4. Set output storage and run settings
        `USE_GOOGLE_DRIVE=True` mounts your Drive and saves checkpoints there, so a Colab disconnect does not erase completed checkpoints.
        With `False`, outputs stay in the temporary runtime; download them before it ends.
        To resume after reconnecting, use the same run name, data, model revision, and settings, and set `RESUME=True`.
        A checkpoint is saved every 25 optimizer steps. Work before the first checkpoint cannot be resumed.
        """),
        code(f"""
        import os, re
        MODEL = 'Qwen/Qwen2.5-1.5B-Instruct'
        REVISION = '{MODEL_REVISION}'
        DATA = ROOT / 'ml/data/colab-splits-500'
        ALLOW_BULK_APPROVED = True  # Explicit experimental use of the project's bulk-approved synthetic batch.
        USE_GOOGLE_DRIVE = True
        RUN_NAME = 'bugbrief-qlora-01'
        RESUME = False
        EPOCHS = 3
        RUN_GPU_SMOKE = True
        assert re.fullmatch(r'[A-Za-z0-9_-]+', RUN_NAME), 'Use letters, digits, underscores, or hyphens in RUN_NAME.'
        if USE_GOOGLE_DRIVE:
            from google.colab import drive
            drive.mount('/content/drive')
            RUNS = Path('/content/drive/MyDrive/BugBrief/runs')
        else:
            RUNS = Path('/content/bugbrief-runs')
        RUNS.mkdir(parents=True, exist_ok=True)
        OUTPUT = RUNS / RUN_NAME
        ENV = os.environ.copy()
        ENV['TOKENIZERS_PARALLELISM'] = 'false'
        ENV['PYTORCH_CUDA_ALLOC_CONF'] = 'expandable_segments:True'
        def job(script, *arguments):
            subprocess.run([sys.executable, str(ROOT / 'ml' / script), *map(str, arguments)], cwd=ROOT, env=ENV, check=True)
        POLICY_ARGS = ['--allow-bulk-approved'] if ALLOW_BULK_APPROVED else []
        print('Model:', MODEL, 'revision:', REVISION)
        print('Outputs:', OUTPUT)
        """),
        md("""
        ## 5. Validate data, provenance, split balance, and token lengths
        This checks file hashes, per-example bulk approval, schema, evidence excerpts, duplicate reports, and family isolation.
        It rejects overlong examples rather than silently truncating facts. Only counts and token lengths are printed for the test set.
        """),
        code("""
        import textwrap
        preflight = textwrap.dedent('''
        import json, sys
        from collections import Counter
        from pathlib import Path
        sys.path.insert(0, 'ml')
        from dataset import load_splits
        from train import encode_example
        from transformers import AutoTokenizer
        data, model, revision, allow = sys.argv[1:]
        splits = load_splits(data, allow_bulk_approved=allow == 'true')
        tokenizer = AutoTokenizer.from_pretrained(model, revision=revision, trust_remote_code=False)
        for name, rows in splits.items():
            lengths = [len(encode_example(tokenizer, row)['input_ids']) for row in rows]
            print(name, len(rows), dict(Counter(r['ticket']['product_area'] for r in rows)), 'max tokens', max(lengths))
        print('Data policy:', json.loads((Path(data) / 'manifest.json').read_text())['data_policy'])
        ''')
        subprocess.run([sys.executable, '-c', preflight, str(DATA), MODEL, REVISION, str(ALLOW_BULK_APPROVED).lower()], cwd=ROOT, env=ENV, check=True)
        """),
        md("""
        ## 6. Run a one-step GPU smoke check
        This performs one optimizer update and validation loss evaluation using the real configuration, then frees that process's GPU memory.
        Its adapter is discarded for model selection; full training starts again from the pinned base weights.
        If CUDA runs out of memory, reconnect to a fresh GPU runtime and rerun. Do not remove data checks to continue.
        """),
        code("""
        from datetime import datetime, timezone
        if RUN_GPU_SMOKE and not RESUME:
            smoke = Path('/content') / ('bugbrief-smoke-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
            job('train.py', '--data', DATA, '--model', MODEL, '--revision', REVISION,
                '--output', smoke, '--max-steps', 1, '--epochs', EPOCHS, *POLICY_ARGS)
            print('GPU smoke check passed. Full training will use a separate directory.')
        else:
            print('Smoke check skipped by configuration or resume mode.')
        """),
        md("""
        ## 7. Fine-tune the adapter
        NF4 with double quantization; LoRA rank 16/alpha 32/dropout 0.05 on linear layers; batch size 1 and accumulation 8;
        learning rate 2e-4; three epochs by default; gradient checkpointing; fp16 on T4, bf16 when supported.
        Loss is computed on assistant tokens only. Validation loss selects saved checkpoints. Predictions are not retained during loss evaluation.
        The adapter is saved to `adapter/`, with tokenizer files and `run.json` recording data hashes, approval policy, packages, and GPU.
        """),
        code("""
        resume_args = ['--resume'] if RESUME else []
        job('train.py', '--data', DATA, '--model', MODEL, '--revision', REVISION,
            '--output', OUTPUT, '--epochs', EPOCHS, *POLICY_ARGS, *resume_args)
        assert (OUTPUT / 'adapter/adapter_config.json').exists()
        print('Training finished. Adapter:', OUTPUT / 'adapter')
        """),
        md("""
        ## 8. Compare the baseline and adapter on validation
        This generates paired outputs for all 50 validation reports. It can take longer than loss evaluation.
        Both variants use the same unquantized base weights (fp16 on CUDA), prompt, greedy decoding, and output budget.
        Results are appended after each completion so finished outputs survive interruption. An interrupted run is partial: rerun with a new result filename.
        Automatic scores cover schema/evidence validity and two labels. Read the paired outputs and fill their human-review fields before a release decision.
        """),
        code("""
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        VALIDATION_RESULTS = OUTPUT / f'validation-{stamp}.jsonl'
        job('evaluate.py', '--data', DATA, '--model', MODEL, '--revision', REVISION,
            '--adapter', OUTPUT / 'adapter', '--split', 'validation', '--output', VALIDATION_RESULTS, *POLICY_ARGS)
        print('Paired validation outputs:', VALIDATION_RESULTS)
        """),
        md("""
        ## 9. Inspect one validation pair
        Check unsupported claims, lost facts, question usefulness, and edit time. The validation references are synthetic and individually unverified.
        These measurements cannot prove generalization to real customer reports.
        """),
        code("""
        pairs = [json.loads(line) for line in VALIDATION_RESULTS.read_text().splitlines() if line.strip()]
        for item in pairs[:2]:
            print('\\nVARIANT:', item['variant'], '| valid:', item['valid'])
            print('REPORT:', item['report'])
            print('OUTPUT:', item['output'])
            print('REFERENCE:', json.dumps(item['reference'], indent=2))
        """),
        md("""
        ## 10. Optional final held-out test
        Keep this off until the prompt, hyperparameters, and adapter choice are frozen after validation review.
        Set `RUN_FINAL_TEST=True` for the release candidate and run the untouched test set once. Review factual fidelity separately.
        """),
        code("""
        RUN_FINAL_TEST = False
        if RUN_FINAL_TEST:
            test_path = OUTPUT / ('test-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.jsonl')
            job('evaluate.py', '--data', DATA, '--model', MODEL, '--revision', REVISION,
                '--adapter', OUTPUT / 'adapter', '--split', 'test', '--output', test_path, *POLICY_ARGS)
        else:
            print('Test set remains unused for generation and model selection.')
        """),
        md("""
        ## 11. Download the adapter and run evidence
        The download contains the LoRA adapter, tokenizer, run manifests, completed evaluation files, and dataset provenance.
        It excludes large optimizer checkpoints and base-model weights. Checkpoints remain in your chosen output storage for resume.
        The adapter needs the same Qwen base model at inference time. No model or dataset is automatically published.
        """),
        code("""
        assert (OUTPUT / 'adapter/adapter_config.json').exists(), 'Complete training before exporting an adapter.'
        export_path = Path('/content') / f'{RUN_NAME}-adapter.zip'
        with zipfile.ZipFile(export_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in (OUTPUT / 'adapter').rglob('*'):
                if path.is_file():
                    archive.write(path, str(Path(RUN_NAME) / path.relative_to(OUTPUT)))
            for path in OUTPUT.iterdir():
                if path.is_file() and path.suffix in {'.json', '.jsonl'}:
                    archive.write(path, str(Path(RUN_NAME) / path.name))
            for path in DATA.iterdir():
                if path.is_file():
                    archive.write(path, str(Path(RUN_NAME) / 'dataset' / path.name))
        print('Download:', export_path, f'({export_path.stat().st_size / 2**20:.1f} MiB)')
        from google.colab import files
        files.download(str(export_path))
        """),
        md("""
        ## 12. Connect the adapter to BugBrief after evaluation
        Unzip the download on the API machine, install `backend/requirements-model.in`, and set these locally:

        ```dotenv
        INFERENCE_MODE=transformers
        MODEL_ID=Qwen/Qwen2.5-1.5B-Instruct
        MODEL_REVISION=989aa7980e4cf806f80c7fef2b1adb7bc71aa306
        ADAPTER_PATH=/absolute/path/to/bugbrief-qlora-01/adapter
        ```

        Restart the API and test new reports. CPU serving has separate latency and RAM requirements; this notebook does not deploy an API.
        If you change the model revision, use the exact revision recorded in `run.json`.

        References: [Qwen model card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct),
        [PEFT quantization](https://huggingface.co/docs/peft/developer_guides/quantization),
        [Transformers Trainer](https://huggingface.co/docs/transformers/main_classes/trainer),
        [Colab resource limits](https://research.google.com/colaboratory/faq.html).
        """),
    ]
    if version == 2:
        replacements = {
            "BugBrief_Colab": "BugBrief_Colab_v2",
            "ml/data/colab-splits-500": "ml/data/colab-splits-500-v2",
            "bugbrief-qlora-01": "bugbrief-qlora-02",
            "ALLOW_BULK_APPROVED": "ALLOW_CORRECTED_SYNTHETIC",
            "allow_bulk_approved": "allow_corrected_synthetic",
            "--allow-bulk-approved": "--allow-corrected-synthetic",
            "The project user bulk-approved this batch. Individual human review is unverified; that provenance stays in the data and run manifest.":
                "Dataset v2 corrects 116 targets while preserving all 500 reports and the original split assignments. Corrections were authored by AI with automated checks; individual human review remains unverified. Original bulk approval and the complete correction history are included.",
            "Explicit experimental use of the project's bulk-approved synthetic batch.":
                "Explicit experimental use of AI-corrected synthetic targets; individual human review is unverified.",
            "per-example bulk approval": "the original per-example bulk approval and v2 correction history",
            "synthetic and individually unverified": "AI-corrected synthetic examples and individually unverified",
        }
        for entry in cells:
            source = "".join(entry["source"])
            for old, new in replacements.items():
                source = source.replace(old, new)
            entry["source"] = source.splitlines(keepends=True)
    for index, entry in enumerate(cells):
        entry["id"] = f"bugbrief-{index:02d}"
    return {"cells": cells, "metadata": {"colab": {"name": "BugBrief_Training.ipynb", "provenance": []}, "accelerator": "GPU", "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python", "version": "3.12"}}, "nbformat": 4, "nbformat_minor": 5}


def build(version=2):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = ROOT / ("ml/BugBrief_Training.ipynb" if version == 1 else "ml/colab/BugBrief_Training_v2.ipynb")
    data_directory = ROOT / ("ml/data/colab-splits-500" if version == 1 else "ml/data/colab-splits-500-v2")
    prefix = "BugBrief_Colab" if version == 1 else "BugBrief_Colab_v2"
    document = notebook(version)
    # Fail packaging on invalid Python, including escaped newlines in cell strings.
    for entry in document["cells"]:
        if entry["cell_type"] == "code":
            compile("".join(entry["source"]), f"notebook:{entry['id']}", "exec")
    target.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    paths = ["backend/app/__init__.py", "backend/app/domain.py", "backend/app/errors.py", "backend/app/inference.py", "backend/app/quality.py", "backend/app/artifacts.py",
             "ml/dataset.py", "ml/train.py", "ml/evaluate.py", "ml/requirements-colab.txt", target.relative_to(ROOT).as_posix()]
    paths += [path.relative_to(ROOT).as_posix() for path in sorted(data_directory.iterdir()) if path.is_file()]
    paths += ["ml/colab/README.md", "ml/colab/local-validation.json"] if version == 1 else ["ml/colab/README-v2.md", "ml/colab/local-validation-v2.json"]
    contents = {name: (ROOT / name).read_bytes() for name in paths}
    manifest = {"version": version, "model": "Qwen/Qwen2.5-1.5B-Instruct", "revision": MODEL_REVISION,
                "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    archive_path = OUTPUT / f"{prefix}_Bundle.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(prefix + "/" + name, data)
        archive.writestr(prefix + "/BUNDLE_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    if version == 2:
        with zipfile.ZipFile(OUTPUT / "BugBrief_Dataset_v2.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(data_directory.iterdir()):
                if path.is_file():
                    archive.write(path, data_directory.name + "/" + path.name)
    print(target)
    print(archive_path, archive_path.stat().st_size, "bytes")
    return archive_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=int, choices=[1, 2], default=2)
    build(parser.parse_args().version)
