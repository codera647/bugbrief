# Run BugBrief fine-tuning on Colab

Open `ml/BugBrief_Training.ipynb` using **File → Upload notebook** at https://colab.research.google.com/. Select **Runtime → Change runtime type → GPU**. Run the cells in order and upload `BugBrief_Colab_Bundle.zip` when prompted. Everything required from this project is in that ZIP; no repository clone or `.env` upload is needed.

The notebook checks the GPU, installs pinned libraries, verifies the data and token lengths, performs a one-step GPU smoke run, trains QLoRA, compares the adapter against the base model on validation reports, and downloads the adapter with run evidence. The final test cell is off until you freeze your candidate after validation review. Free GPU availability is controlled by Colab; a specific GPU or continuous session is not guaranteed.

The default model is `Qwen/Qwen2.5-1.5B-Instruct`, pinned to commit `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`. Settings target a 16 GB T4: 4-bit NF4/double quantization, LoRA rank 16, batch size 1, accumulation 8, and gradient checkpointing. Actual GPU memory use and duration must be established by running the notebook; no successful GPU training run is claimed here.

## Dataset files

`ml/data/colab-splits-500/` contains:

- `train.jsonl`: 400 examples, 80 per product area.
- `validation.jsonl`: 50 examples, 10 per area.
- `test.jsonl`: 50 examples, 10 per area.
- `manifest.json`: counts, file hashes, approval policy, and split settings.
- `bulk-approved.jsonl` and `bulk-approval.json`: the original accepted batch and its approval provenance.

The examples are synthetic, based on 50 fictional LedgerFlow scenarios with ten variations per family. Related examples stay in the same split. The user bulk-approved all 500; individual human review remains unverified, and reviewer fields stay blank. The notebook passes `--allow-bulk-approved` explicitly to use this dataset as an experiment. Default individually reviewed workflows continue to reject it. A training result on these template families alone does not establish real-world factual accuracy.

## Save, resume, and download

`USE_GOOGLE_DRIVE=True` stores run artifacts and checkpoints in `MyDrive/BugBrief/runs/RUN_NAME`. Colab asks you to mount Drive. Set it to `False` to use temporary `/content` storage instead. No Hub token is required for this public model, and nothing is automatically published.

Checkpoints are saved every 25 optimizer steps. After a disconnect, reupload the bundle, mount the same Drive, keep the same run name and settings, and set `RESUME=True`. Resume rejects a changed model revision, prompt, dataset, epoch count, or max-step setting. There must be a completed checkpoint. For a fresh run, choose a new `RUN_NAME`. Resume loads only your own trusted checkpoint files.

The final download contains `adapter/`, `run.json`, `planned-run.json`, paired evaluation results, and dataset evidence. The archive excludes optimizer checkpoints and base weights. If evaluation is interrupted, partial results are retained; rerun evaluation with its new timestamped filename. Download completed artifacts even if you have not yet run every evaluation cell.

After checking quality, use the notebook's final settings to connect the adapter to the local BugBrief API. Keep Supabase credentials on your machine. Colab training does not deploy the application.

## Rebuild or verify locally

From the project root:

```powershell
.\.venv\Scripts\python.exe ml/build_colab_bundle.py
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

To prepare a new split version from a recorded bulk approval, use a fresh directory:

```powershell
.\.venv\Scripts\python.exe ml/prepare_dataset.py ml/data/bulk-approved.jsonl ml/data/NEW-SPLITS --train-count 400 --bulk-approval ml/data/bulk-approval.json --stratify-by-area
```

For individually reviewed data, use the review/export workflow in `ml/README.md`, omit `--bulk-approval`, and turn off `ALLOW_BULK_APPROVED`. Update the bundle's dataset path if you replace its files. Do not relabel bulk acceptance as individual review.

References: [Colab FAQ](https://research.google.com/colaboratory/faq.html), [model card](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct), [PEFT quantization](https://huggingface.co/docs/peft/developer_guides/quantization), [Transformers Trainer](https://huggingface.co/docs/transformers/main_classes/trainer). Package pins were checked against PyPI; runtime package versions are also captured in every completed training run.

## Local verification

The notebook passed nbformat validation, and every Python cell compiled. The pinned model's actual tokenizer encoded all 500 examples through the training encoder, including assistant-only loss masking. Maximum lengths across the batch were 818 input tokens, 212 assistant tokens, and 1,021 total tokens, within the 2,048/768 serving budgets. Details are in `local-validation.json`. Project tests also verify archive extraction, file hashes, approval provenance, balanced split counts, and family isolation. CUDA training, peak VRAM, checkpoint resume on a GPU, and model quality still need the Colab run.
