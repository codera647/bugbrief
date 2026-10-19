# BugBrief adapter review — 15 October 2026

The adapter is saved coherently and substantially improves output formatting over the base-model prompt. It is suitable for further development with manual inspection. The saved validation outputs contain factual and semantic errors that prevent treating it as a reliable pilot model yet. The generated reference dataset also needs corrections before another training run.

## Evidence inspected

Run directory: `bugbrief-qlora-01-adapter/bugbrief-qlora-01/`.

- `run.json`, `planned-run.json`, adapter configuration, tokenizer files, and all tensor values in `adapter_model.safetensors`.
- All 100 records in `validation-20261015-104711.jsonl`: one baseline and one adapter output for each of 50 validation reports.
- Frozen dataset files, hashes, family isolation, per-example bulk approval, and correspondence between evaluation reports/references and the validation split.

This is an automated artifact inspection plus an AI review of saved outputs. No new model generation or GPU run was performed. Human-review fields in the saved evaluation are all unfilled. There is no held-out test-generation file in this export; its absence does not establish whether a test was run elsewhere.

## Run and file integrity

| Item | Result |
| --- | --- |
| Base | Qwen/Qwen2.5-1.5B-Instruct |
| Base revision | `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` |
| Saved run | Three epochs, Tesla T4, learning rate 0.0002, batch 1, accumulation 8 |
| LoRA | Rank 16, alpha 32, dropout 0.05, seven projection types |
| Adapter weights | 392 F32 tensors; 18,464,768 parameters; 73,911,112 bytes |
| Numeric check | No NaN/Inf values; all 196 LoRA B tensors contain nonzero values |
| Validation loss | 0.2098545; exponentiated loss approximately 1.2335 |
| Data | 400 train / 50 validation / 50 test; balanced areas; families isolated |
| Data provenance | User bulk-approved synthetic examples; individual review unverified |
| Reproducibility | Data hashes, current training-script hash, and current prompt hash match the saved run; planned-run fields agree with run.json |

These checks support that a nonzero adapter was trained and exported. They do not substitute for loading it with the base model in the target API. The final loss is an assistant-token prediction loss; it is not a correctness percentage. Training-loss history and checkpoint selection history are not in this export, so convergence and overfitting cannot be assessed from a learning curve.

## Validation comparison

All rates below use the same 50 reports as denominator. The two label rows require an output to pass schema and evidence validation first, matching the original evaluator. They measure usable, correctly labelled tickets rather than a separate classifier's accuracy.

| Metric | Base prompt | Adapter |
| --- | ---: | ---: |
| Raw JSON parses | 29/50 (58%) | 50/50 (100%) |
| Ticket schema passes | 19/50 (38%) | 47/50 (94%) |
| Schema and exact supporting evidence pass | 7/50 (14%) | 47/50 (94%) |
| Valid output and correct product area | 7/50 (14%) | 44/50 (88%) |
| Valid output and correct expectation basis | 3/50 (6%) | 21/50 (42%) |
| Mean saved generation time | 7.79 s | 12.53 s |
| Median saved generation time | 8.00 s | 12.21 s |

The 80 percentage-point increase in usable structured output is substantial. The adapter was slower in this saved evaluation. These are single-run Colab timings, including the evaluator's validation overhead; they are not API capacity or multi-user latency measurements.

For raw JSON outputs without the validity gate, adapter product-area labels match 46/50 references; expectation labels match 21/50. Four raw area errors are `unknown-loading-page-v01`, `unknown-loading-page-v04`, `unknown-loading-page-v08` (Unknown → Dashboard), and `authentication-account-email-v06` (Authentication → Unknown). One of those outputs also fails the schema.

### Remaining schema failures

| Example | Failure |
| --- | --- |
| `billing-invoice-draft-v01` | Four follow-up questions, exceeding the maximum of three |
| `unknown-loading-page-v08` | Four follow-up questions |
| `billing-invoice-draft-v05` | `reported_steps` is a string instead of a list/null; it also supplies a step absent from the report |

## Quality findings

### Expectation labels collapse to Reported

Across all 50 raw adapter outputs, 49 say `Reported`, one says `Unknown`, and none says `Inferred`.

| Reference basis | Predicted Reported | Predicted Inferred | Predicted Unknown |
| --- | ---: | ---: | ---: |
| Reported | 20 | 0 | 0 |
| Inferred | 20 | 0 | 0 |
| Unknown | 9 | 0 | 1 |

For example, `dashboard-dashboard-loading-v08` only reports a loading indicator and Firefox. The adapter adds “See the dashboard's content” and labels it `Reported`. That expectation was not stated by the reporter. The same mistake occurs in 29 outputs without the dataset's explicit “I expected to” statement. Regardless of how Inferred versus Unknown is resolved, assigning Reported to an unstated expectation is wrong.

### Invoice titles reverse the bug

Nine of ten invoice-draft outputs use a positive title such as “Invoice draft retains line-item descriptions.” The report says the description is lost after reopening. This changes the issue's meaning even when `actual_behavior` correctly repeats the report. A schema check cannot catch this contradiction.

### Environment details and follow-up questions need review

The four scalar environment fields match references in 47/50 outputs. Three Safari/iOS reports incorrectly put `iOS 17` into browser version and reduce the operating system to `iOS`.

Twenty-nine outputs populate `other_details`; 24 differ from the reference list. Differences alone do not prove hallucination, but inspection found unsupported entries, for example “Invoice and draft are in the same document” in `billing-invoice-draft-v05`. Other outputs put missing-information labels such as “Actions leading to the issue” into reported environment details. Follow-up questions sometimes repeat already supplied steps or ask about unrelated facts. `authentication-account-email-v05`, for example, asks which address received an invoice although the report concerns an account email change.

### Reference labels contain an inconsistency

The original generator assigns expectation basis by template variant (`ml/generate_dataset.py`, `build_candidate`), rather than consistently by the report's meaning. This is a flaw in the generated dataset supplied with the initial notebook.

For example, in the training family `integrations-sheets-stale`, v01 says that Google Sheets still shows old values after syncing and is labelled Inferred. V06 has the same symptom plus app version 0.8.2, and v08 adds Firefox; both are labelled Unknown with a null expected result. The validation dashboard-loading family has the same pattern. Browser/app-version information does not justify changing whether an expectation can be inferred.

Resolve that policy and relabel affected examples before retraining. The 42% expectation score is agreement with these inconsistent references, so it is not a clean measure of semantic quality. The separate Reported-label failure remains clear from the source reports.

## Scope and next steps

1. Keep this run as the first experimental baseline. Correct the reference policy and create a new version of the dataset with recorded review; do not rewrite the frozen files used for this run.
2. Add independently written scenarios and targeted examples for negative bug titles, unstated expectations, unknown areas, unsupported environment details, missing steps, and the three-question limit. Inspect targets for factual consistency before training.
3. Retrain a candidate and compare paired validation outputs using schema checks plus factual review. Increasing epochs alone is not justified by the evidence here.
4. Once the candidate and prompt are frozen after validation review, run the untouched held-out test split and review its outputs. The present validation set has only five underlying families, with ten variants each, so 50 reports do not represent 50 independent scenarios.
5. Test loading and latency on the API's target hardware before enabling team use. No backend configuration was changed during this review.

Actual local adapter directory: `F:/Bug_Brief/bugbrief-qlora-01-adapter/bugbrief-qlora-01/adapter`. The API must load it alongside the pinned base model; it is not a standalone model.

## Precision note for future training

The manifest records `bf16=true` and `fp16=false` on a Tesla T4. The training script currently calls `torch.cuda.is_bf16_supported()` with its default, which includes emulation. Use `including_emulation=False` when choosing native BF16, falling back to FP16 otherwise. This is a training-configuration concern, not evidence that the saved weights are invalid. See [PyTorch's API](https://docs.pytorch.org/docs/main/generated/torch.cuda.is_bf16_supported.html), [NVIDIA's compute-capability table](https://developer.nvidia.com/cuda/gpus), and [NVIDIA's BF16 capability requirements](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/mathematical-functions.html).

Evaluation file SHA-256: `9a5602afaf7ad46c3b96babd3c3c69aaa677522ffd0aace9ea8cc990518a3f8e`.
