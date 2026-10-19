# BugBrief adapter v2 review — 15 October 2026

The second adapter is a distinct, valid-looking export trained with the corrected v2 dataset. It substantially improves expectation labels, while retaining serious factual errors. It remains a development candidate requiring human review, not an established production model.

## Evidence

Directory: `bugbrief-qlora-02-adapter/bugbrief-qlora-02/`.

Inspected the run/planned-run manifests, adapter configuration, all safetensors values, corrected dataset and provenance, and all 100 saved validation records. There is exactly one baseline and one adapter result for each of the 50 validation reports. Report text and reference tickets match the frozen v2 validation split. All training, validation, and test hashes match both the run manifest and the project's v2 dataset. The current training-script and prompt hashes match the run.

The saved first-adapter outputs were rescored against the same v2 references. All original validation report texts match, so no new generation was needed for that comparison. This review did not run either model or change backend settings. Human-review fields in both exports remain blank.

## Training and artifact checks

| Item | Saved result |
| --- | --- |
| Model | Qwen/Qwen2.5-1.5B-Instruct |
| Model revision | `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` |
| Training | Three epochs, NVIDIA L4, BF16, learning rate 0.0002 |
| Dataset | 400 train / 50 validation / 50 test; AI-corrected synthetic policy |
| Final validation loss | 0.2253881 |
| Weight file | 73,911,112 bytes; 392 F32 tensors; 18,464,768 parameters |
| Numeric integrity | No NaN/Inf values; all 196 LoRA B tensors contain nonzero values; data spans are contiguous and match declared shapes |
| Distinct from v1 | Weight-file SHA-256 differs from the first adapter |

The higher saved loss than v1 (0.2098545) is not a clean regression measurement: the reference targets changed. Neither loss value is an accuracy percentage. There is no training-loss/checkpoint history in the download to assess convergence or overfitting. Structural checks do not establish that loading and inference on the API's target hardware have been tested.

## Comparison on the same v2 references

Every rate below uses 50 reports as denominator. Rows marked “valid +” require both ticket-schema and exact-source-evidence validation, matching the evaluator's usability gate.

| Metric | Adapter v1, rescored | Adapter v2 |
| --- | ---: | ---: |
| Raw JSON parses | 50/50 (100%) | 50/50 (100%) |
| Valid schema and exact evidence | 47/50 (94%) | 46/50 (92%) |
| Product-area label, before validity gate | 46/50 (92%) | 46/50 (92%) |
| Expectation label, before validity gate | 21/50 (42%) | 42/50 (84%) |
| Valid + correct product area | 44/50 (88%) | 42/50 (84%) |
| Valid + correct expectation label | 21/50 (42%) | 39/50 (78%) |

In the second run, the unadapted baseline passed schema/evidence checks on 7/50 (14%) and had valid/correct expectation labels on 3/50 (6%). The adapter therefore improves substantially over that prompt-only baseline, but the table does not establish overall factual accuracy.

V2's saved mean generation time was 10.73 seconds, versus 6.27 seconds for its same-run baseline. Do not attribute a speed improvement over v1's 12.53-second average to the new adapter: v1 ran on a T4 and v2 on an L4. These are single-run evaluation timings with validation overhead, not API or concurrent-user benchmarks.

## Remaining failures

### Expectations

| Reference | Predicted Reported | Predicted Inferred | Predicted Unknown |
| --- | ---: | ---: | ---: |
| Reported | 20 | 0 | 0 |
| Inferred | 2 | 22 | 0 |
| Unknown | 0 | 6 | 0 |

The adapter now separates Reported from Inferred much better, but never predicts Unknown. All six vague loading-page reports receive an inferred expected outcome. Some add dashboard/overview/chart content although the source never identifies that page. Two inferred reports are still labelled Reported: `billing-invoice-draft-v03` and `integrations-reconnect-v05`.

### Bug meaning

Nine of the ten invoice-draft titles still say that descriptions are retained, contradicting the report's lost-description bug. More seriously, `billing-invoice-draft-v01`, `billing-invoice-draft-v06`, and `billing-invoice-draft-v08` reverse `actual_behavior` itself, saying the draft retains its description. These are schema-valid factual errors. The supplied target titles and actual behavior were already correct in the training dataset; relabelling expectations alone did not fix this failure to generalize.

For example, `billing-invoice-draft-v06` reports “A saved invoice draft loses its line-item description after reopening.” The adapter outputs “A saved invoice draft retains its line-item descriptions after reopening.” Its exact evidence excerpt remains correct, illustrating why evidence-substring checks cannot establish factual fidelity of other fields.

### Schema

| Example | Failure |
| --- | --- |
| `dashboard-dashboard-loading-v04` | Missing `follow_up_questions` field |
| `integrations-reconnect-v07` | Missing `follow_up_questions` field |
| `unknown-loading-page-v03` | Both `reported_steps` and `missing_information` are strings instead of arrays |
| `unknown-loading-page-v07` | Both `reported_steps` and `missing_information` are strings instead of arrays |

The previous four-question overflow is absent, but the required-field and array-type errors remain unacceptable to the current API schema.

### Product area, environment, and questions

The same four raw area errors as v1 persist: three unidentified loading-page reports become Dashboard, and `authentication-account-email-v06` becomes Unknown. The four scalar environment fields match references in 45/50 raw outputs. Safari/iOS examples still confuse operating-system text with browser version.

Thirty-five raw outputs populate `other_details`. That count is not itself a hallucination score, but inspection finds unsupported entries such as “Invoice and draft are open at the same time,” along with missing-information labels incorrectly placed in reported environment details. Follow-up questions often ask again for supplied steps or onset information. Keep these fields in human factual review.

## Assessment and next action

Keep v2 as the stronger expectation-label candidate and retain v1 for comparison. V2 is not uniformly better: schema usability regressed slightly, product-area labels did not improve, and invoice negation errors persist. There is still no defensible single “overall accuracy.”

Before a release decision, review factual correctness and build targeted, independently written examples for lost-versus-retained behavior, genuinely unknown intentions/areas, empty arrays, required keys, and environment extraction. Use a schema-constrained output mechanism if implemented and verify its behavior; none was introduced in this review. Increasing epochs alone is not supported by these results.

No held-out test-generation file is included in this export. Freeze the candidate and prompt after validation work before using that test split. The validation set still contains only five underlying scenario families and AI-authored reference corrections; independent reports and human checks are needed to assess generalization. The absence of an exported test file does not establish whether a test was run elsewhere.

Actual adapter path for a later integration step: `F:/Bug_Brief/bugbrief-qlora-02-adapter/bugbrief-qlora-02/adapter`. The pinned base model is also required.

## File fingerprints

- Adapter weights: `fafedd504f56a43b713189a055244cbe487925795e2f871d32b5cd0da132b5f2`.
- Validation file `validation-20261015-162228.jsonl`: `b23c54ff0b1add7eae4458ca60f9793bba1beaf858c8497439b34d53899036cb`.
