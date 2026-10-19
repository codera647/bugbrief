# Training the BugBrief adapter

## Corrected dataset v2

Use [colab/BugBrief_Training_v2.ipynb](colab/BugBrief_Training_v2.ipynb) and upload [colab/BugBrief_Colab_v2_Bundle.zip](colab/BugBrief_Colab_v2_Bundle.zip) when prompted. The v2 bundle includes corrected, frozen 400/50/50 splits. A [dataset-only ZIP](colab/BugBrief_Dataset_v2.zip) is also available.

Version 2 changes 116 ticket targets and their dependent missing-information/questions. It preserves all 500 original source reports, IDs, families, and split assignments. Expectation labels now depend on the stated goal and whether a concrete outcome can reasonably be inferred, rather than browser/app-version variants. Original factual bug titles, environment values, and reported-only steps remain intact and have automated checks.

Corrections are AI-authored; individual human review is unverified. The v2 experiment uses the explicit `--allow-corrected-synthetic` option and records the full change history and original bulk approval separately. The first adapter has not been retrained with these corrections. Use a new run name (`bugbrief-qlora-02`) starting from the base model. See [the v2 guide](colab/README-v2.md) for the policy, label counts, provenance, and commands. The original dataset and v1 workflow below remain available for reproducing the first experiment.

No trained adapter or human-reviewed dataset is bundled. `data/candidates-500.jsonl` contains 500 generated synthetic candidates with blank reviewer fields. `data/examples.json` supplies four fixed UI fixtures. The training validator rejects unreviewed rows.

The project user has bulk-approved all 500 candidates. [data/bulk-approved.jsonl](data/bulk-approved.jsonl) contains that accepted batch, and [data/bulk-approval.json](data/bulk-approval.json) records the instruction, timestamp, and hashes for each example. Individual human review remains unverified, so reviewer fields stay blank and the manual review workflow below remains available. Default training requires individual review. The Colab experiment explicitly opts into bulk-approved synthetic data and verifies its recorded provenance.

## Ready-to-run Colab package

Upload [BugBrief_Training.ipynb](BugBrief_Training.ipynb) to Google Colab, select a GPU runtime, then run its cells in order. When prompted, upload [colab/BugBrief_Colab_Bundle.zip](colab/BugBrief_Colab_Bundle.zip). This ZIP includes the required code and frozen, area-balanced 400/50/50 dataset; no project clone, `.env`, or private credentials are needed.

The notebook includes GPU checks, pinned package installation, dataset and token validation, a one-step GPU smoke run, QLoRA training, checkpoint resume, paired validation evaluation, optional final test, and adapter download. Drive persistence is on by default and can be turned off. The package has not been run on a GPU here. See [colab/README.md](colab/README.md) for settings, files, resume instructions, and limits.

Training and evaluation use `--allow-bulk-approved` for this specific experiment. It does not populate individual reviewer fields or change the stricter default. The dataset contains 50 template families; model quality still needs human evaluation and independent reports.

## Generate and review 500 examples

`generate_dataset.py` uses a fictional LedgerFlow scenario catalog and the application's canonical ticket schema. It needs the existing backend Python environment, with no model, GPU, API key, or new dependency. The included file was generated with seed 42. To generate another copy, choose an unused output filename:

```powershell
.\.venv\Scripts\python.exe ml/generate_dataset.py generate --count 500 --seed 42 --output ml/data/candidates-new.jsonl
```

There are 100 examples per product area: Authentication, Billing, Dashboard, Integrations, and Unknown. Fifty scenario families each have ten variations covering supplied or missing steps, reported/inferred/unknown expectations, environment details, timing, repeated text, and instructions inside reports. These are 50 underlying scenarios; template variations do not establish broad model quality. Review the fictional feature assumptions and add independent scenarios before making generalization claims.

Review the included candidates from an interactive terminal:

```powershell
.\.venv\Scripts\python.exe ml/generate_dataset.py review --reviewer "Your name" --limit 25
.\.venv\Scripts\python.exe ml/generate_dataset.py status
```

Read the report and proposed ticket, then check facts, exact evidence, expectation labels, environment, supplied steps, missing information, useful questions, and family assignment. Choose approve, reject, edit, skip, or quit. Approval requires typing `APPROVE` followed by the displayed example ID; rejection requires a reason. Choosing edit prints a temporary JSON file path; open it in your editor. Save it, return to the terminal, and press Enter to validate the edit. Keep the ID, synthetic source, and blank reviewer fields. The edited example still needs approval.

Each decision is saved immediately in `data/human-reviews.json`. Repeat the review command to resume; `--limit` bounds the number of candidates shown per session. Skipped examples remain pending. Previously decided examples are skipped unless their content changed or you pass `--revisit`. Run one reviewer session per ledger at a time. For a custom candidate file, pass `--candidates PATH --reviews PATH` to review, status, and export.

Reviewer names and timestamps record an explicit human attestation; they do not authenticate a person's identity or independently prove the review happened. Generation never populates them. The initial generation manifest records the seed, counts, and original file hash; it remains an initial snapshot after edits. Current review status comes from the review ledger.

After all 500 examples have been checked and approved, export:

```powershell
.\.venv\Scripts\python.exe ml/generate_dataset.py export --require-count 500
```

This writes `data/reviewed.jsonl` with reviewer names and UTC timestamps. Pending or rejected examples are excluded; the command fails if fewer than 500 are approved. Revise rejected candidates with `review --revisit` and review them again. Editing an approved report, ticket, or family invalidates its approval; export refuses stale approvals until re-review. Existing candidate and export files are never silently overwritten. For a later export, pass a new `--output` filename.

For the 500-example dataset, freeze **400 train / 50 validation / 50 test**:

```powershell
.\.venv\Scripts\python.exe ml/prepare_dataset.py ml/data/reviewed.jsonl ml/data/splits-500 --train-count 400
```

Use `ml/data/splits-500` in the training and evaluation commands below, and set the notebook's `DATA` path accordingly. Families stay together, but splits are not automatically stratified by product area. Check label coverage before training; freeze a new dataset version if you need to change the split.

## Original 400-example split

Write 400 synthetic report/ticket pairs in JSONL with exactly these keys:

```json
{"id":"billing-001","family_id":"bulk-export","report":"Customer report here…","ticket":{},"source":"synthetic","reviewed_by":"actual reviewer","reviewed_at":"2026-10-13T12:00:00+05:00"}
```

`ticket` must match `frontend/src/generated/ticket.schema.json`. Give paraphrases or variants of the same scenario the same `family_id`. A human checks all facts, quoted evidence, expectation labels, missing details, and the usefulness of the questions. Record who reviewed the final pair and when; filling reviewer fields alone does not prove review took place.

Include clear and ambiguous reports across all five product areas, unknown environment values, explicit/inferred/unknown expectations, repeated details, irrelevant instructions inside reports, and reports with no reproduction steps. Do not copy real private reports into the synthetic dataset.

From the project root:

```powershell
.\.venv\Scripts\python.exe ml/prepare_dataset.py ml/data/reviewed.jsonl ml/data/splits
```

The default command requires exactly 400 reviewed rows. This validates the schema and evidence, rejects duplicate reports, keeps scenario families in one split, and freezes **300 train / 50 validation / 50 test** rows with file hashes. If family group sizes cannot fit those counts, adjust the dataset groups. It refuses to overwrite frozen splits; training and evaluation reject changed split files using the recorded hashes. It cannot automatically detect every semantic paraphrase; inspect families during review.

## Train on a free GPU

For the packaged Colab experiment, use the notebook workflow above. For a separate individually reviewed dataset, copy the required source into a GPU environment, excluding environment files, saved tickets, and dependencies. Install `ml/requirements-colab.txt` on Colab (keeping its CUDA PyTorch) or `ml/requirements.in` for another GPU environment. Select and record the full base-model commit before training. No Hub login is needed to download this public base model.

```bash
python ml/train.py --data ml/data/splits --revision FULL_40_CHARACTER_COMMIT --output ml/artifacts/run-01
```

The starting configuration is Qwen2.5-1.5B-Instruct, 4-bit NF4 QLoRA, rank 16, alpha 32, dropout 0.05, all linear layers, three epochs, learning rate 2e-4, batch size 1, and gradient accumulation 8. CUDA precision follows the GPU's bf16 support. The script trains on assistant tokens only, evaluates loss and saves checkpoints every 25 optimizer steps, uses validation loss for checkpoint selection, rejects truncation, and records packages, data hashes, approval policy, settings, and GPU details. Add `--resume` only for a matching existing run with a saved checkpoint.

Free runtimes can stop. Download `adapter/`, `run.json`, and your evaluation output before the runtime expires. There is no automatic publishing step. The scripts and notebook have only been checked without a GPU in this initial build; actual VRAM usage, training time, and model quality need a real run.

## Compare before release

```bash
python ml/evaluate.py --data ml/data/splits --revision FULL_40_CHARACTER_COMMIT --adapter ml/artifacts/run-01/adapter --split validation --output ml/artifacts/run-01/validation-results.jsonl
```

The comparison uses the same prompt, schema, base weights, precision, greedy generation, 2,048 input-token limit, and 768 output-token limit. Run it on a GPU if possible; a CPU run is substantially slower. The baseline disables the adapter on the same loaded model.

Review both outputs for unsupported claims, missing facts, question quality, and edit time. Automatic schema validity, product-area accuracy, and expectation-label accuracy do not establish factual fidelity. Freeze the prompt, configuration, and chosen adapter before running the untouched test set. Evaluate the test split once for the release decision, with a new output filename. No model improvement is claimed until the paired results and human checks support it.

Training follows the official [Transformers Trainer](https://huggingface.co/docs/transformers/main_classes/trainer) and [PEFT quantization](https://huggingface.co/docs/peft/developer_guides/quantization) APIs. Keep the run's package manifest with the adapter so results can be reproduced.
