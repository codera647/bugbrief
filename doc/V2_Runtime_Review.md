# Local v2 runtime checks

Checked across 15–16 October 2026 on this laptop's two-core Intel CPU. These are synthetic workflow checks, not a held-out accuracy evaluation or human factual review.

The application pipeline is connected. The downloaded v2 model still produces factual errors on differently worded reports. Technical readiness must not be treated as approval for team use.

## Observations

Both runs used the same pinned base, downloaded v2 adapter, serving prompt, JSON constraints, two Torch threads, and this report:

> Since yesterday, exporting invoices gives me an empty file. It happens when I select several invoices, but exporting one works. I am using Chrome.

| Runtime | Model preparation | Request | Result |
| --- | ---: | ---: | --- |
| Dynamic INT8 | 260.7 seconds | 177.3 seconds | Structurally valid; title was “Unspecified”, area Unknown, actual behavior absent. Source-comparison hints flagged missing actual behavior. The disposable API test completed save/review/export and edit invalidation, but the content was poor. |
| Float32 | 79.0 seconds | 170.9 seconds | Rejected for an evidence quote absent from the report. Raw synthetic output also reversed the bulk/single export behavior and placed missing-information labels in environment details. |

The first float32 attempt also failed validation. The recorded diagnostic reproduces that failure. These few observations do not establish a quality percentage or prove that quantization caused every error. Float32 is selected to avoid adding quantization loss while evaluating the downloaded adapter.

The float32 output said “Selecting multiple invoices exports them successfully,” although the report says exporting one works. Replacing only the evidence excerpt would leave this factual error intact. No output repair or synthetic fallback was added.

## Evidence

Local evidence is under `ml/artifacts/` and excluded from Git:

- `v2-pipeline-smoke.json`: real INT8 generation and a successful **automated** workflow through an isolated in-memory database; no human review occurred.
- `v2-pipeline-float32-diagnostic.json`: rejected float32 output, exact validation reason, synthetic source, timings, model hashes, and runtime settings.
- `v2-checks-replay.json`: review hints replayed over the downloaded unconstrained validation outputs; this is not fresh inference.
- `v2-browser-checks.json`: successful float32 reproduction of the known training row `billing-bulk-export-v06`, original generated payload, explicit coding-agent edits, and observed UI states. This is an in-distribution integration check, not an accuracy result. Screenshots are `v2-workspace.jpg` and `v2-workspace-preview.jpg`.

The entire 3,087,467,144-byte base-weight file was verified against SHA-256 `dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee` before loading. Adapter weights, configuration, run manifest, and serving prompt have separate hashes in `models/v2.json`.

`scripts/check_v2.py --live` uses a fixed synthetic report. On failure it records the synthetic raw output for diagnosis, then exits unsuccessfully. The ordinary API does not retain or return rejected model text as an editable ticket. Existing evidence files refuse overwrites; use a new `--output` filename for another check.

## Browser integration check

After the browser bridge recovered, the real float32 adapter produced a valid draft for the exact synthetic training report `billing-bulk-export-v06`. Its evidence and actual behavior matched that source, but it added an unsupported CSV format and put missing-information labels in environment details. Source-comparison hints flagged those labels.

During the browser test, the coding agent explicitly removed those labels, replaced the CSV claim with a generic inferred result, and clarified the title. Checks refreshed for the edited payload. The review dialog required acknowledgement; keyboard Space toggled it, confirmation enabled export, and another edit invalidated the review and disabled export again. These were automated test interactions, not human factual review. No ticket was saved to the user's history.

The local API reported readiness with `provider=transformers_cpu`, `profile=BugBrief v2`, and constrained output enabled. Desktop login, loading, draft, source comparison, and review states were inspected. At a 390 px viewport, the editor had no horizontal overflow; the desktop viewport was restored afterwards. The kept browser tab contains the unsaved, edited training-example draft and requires review again.

## Before team use

Keep v2 experimental. Evaluate varied report wording, exact evidence copying, negation, bulk/single comparisons, unknown expectations, and environment extraction with independent factual review. More diverse training examples and a separately evaluated retraining run may be needed. The existing validation percentages describe the Colab evaluation protocol, not this serving runtime's overall accuracy.

The timed CPU requests took roughly three minutes. No 10–20-user capacity, hosted Google login, or cloud deployment has been established. Run instructions and runtime behavior are in [V2_Pipeline.md](V2_Pipeline.md).
