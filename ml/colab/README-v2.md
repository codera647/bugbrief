# Corrected BugBrief dataset and Colab run

Use `BugBrief_Training_v2.ipynb` with `BugBrief_Colab_v2_Bundle.zip`. Upload the notebook to Colab, select a GPU runtime, run the cells, and upload this v2 ZIP when prompted. The default new run name is `bugbrief-qlora-02`. It starts from the original pinned Qwen base model; it does not continue the first adapter. Keep `RESUME=False` for the first run.

The ZIP includes the corrected data and all required source. No `.env` files or Supabase credentials are needed. `BugBrief_Dataset_v2.zip` is a separate dataset-only archive for inspection or another training workflow.

## What changed

Dataset directory: `ml/data/colab-splits-500-v2/`.

- 500 original report texts, IDs, family IDs, and split assignments are preserved. Counts remain 400 train / 50 validation / 50 test, with balanced product areas and no family shared across splits.
- 116 ticket targets changed. `corrections.json` records every changed field, before/after values, row hashes, original split hashes, and the correction policy.
- All explicit expectations remain Reported. A conventional outcome for an identified concrete action/feature is Inferred, independent of browser, OS, app version, timing, or repeated text.
- An unidentified page, button, list, message, or destination with no concrete intended result is Unknown, with a null expected behavior. Saving changes and downloading a file can still support an inference without knowing the product area. An explicitly reported expectation takes precedence in every family.
- Dependent missing-information lists and follow-up questions were regenerated from those labels, keeping at most three questions and avoiding requests for already supplied steps or expectations.

The original targets already had factual bug titles, null unknown environment values, and reported-only reproduction steps. These are preserved and now covered by source checks. Correcting the labels does not guarantee the next model will stop reversing titles or inventing details; the new adapter must be evaluated.

| Split | Reported | Inferred | Unknown |
| --- | ---: | ---: | ---: |
| Train | 160 | 204 | 36 |
| Validation | 20 | 24 | 6 |
| Test | 20 | 24 | 6 |

## Files and provenance

`corrected.jsonl` is the complete corrected dataset. `train.jsonl`, `validation.jsonl`, and `test.jsonl` contain the frozen split files. `manifest.json` records their hashes and the `ai_corrected_synthetic` data policy. `corrections.json` records the corrections. `parent-bulk-approved.jsonl` and `parent-bulk-approval.json` preserve the original batch and its user approval; that approval is not represented as approval of individual corrected examples.

These are AI-authored corrections with automated checks. Reviewer fields remain blank, and individual human review is unverified. The v2 notebook passes `--allow-corrected-synthetic` explicitly for an experiment; default training and the original bulk-only option reject these files. The loader verifies the parent approval, unchanged reports, corrected source, split hashes, and the full target-change history. Manual review remains useful and can be performed using the existing review workflow with the corrected candidate file and a new review ledger.

No new independent scenarios were added. The set still has 50 scenario families, and the existing validation outputs informed this correction work. Use validation for development and keep final test generation disabled until you freeze a candidate. The v2 reference labels differ from v1, so compare both adapters using the same v2 references before claiming a model improvement.

## Verification

All 46 backend/data tests passed, including checks for source and fold preservation, consistent expectation labels, original approval provenance, correction-history tampering, schema constraints, and the actual v2 notebook upload/extraction cell. The notebook passed nbformat validation. The pinned model's tokenizer encoded all 500 corrected examples with assistant-only loss masking: maxima were 818 input tokens, 212 assistant tokens, and 1,021 total tokens. `local-validation-v2.json` records the dataset manifest hash and these checks. No v2 GPU training or quality improvement is claimed.

## Rebuild

From the project root, create the dataset once:

```powershell
.\.venv\Scripts\python.exe ml/correct_dataset.py
```

This refuses to overwrite an existing version. The original dataset remains in `ml/data/colab-splits-500`. After verifying the v2 token lengths and updating `local-validation-v2.json`, rebuild the upload package:

```powershell
.\.venv\Scripts\python.exe ml/build_colab_bundle.py --version 2
```

For the CLI training/evaluation scripts, use `--data ml/data/colab-splits-500-v2 --allow-corrected-synthetic`. Use a new output directory and the same pinned base-model commit as the first experiment. GPU execution, resume, paired evaluation, final held-out test, and adapter download follow the notebook cells. No retraining has been performed as part of the dataset correction.
