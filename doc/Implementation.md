# BugBrief implementation status

Updated 16 October 2026. This records implemented behavior, not a production launch.

The local application now selects the downloaded v2 adapter. See [V2_Pipeline.md](V2_Pipeline.md) for configuration, artifact verification, model readiness, source comparison, and the real-model smoke test. Google/Supabase integration and cloud deployment remain separate setup work.

[V2_Runtime_Review.md](V2_Runtime_Review.md) records real CPU inference: the INT8 API workflow passed with poor ticket content; float32 correctly rejected an unsupported evidence quote, and its raw synthetic draft also reversed reported facts. Float32 is selected locally. These checks establish integration behavior, not model suitability for team use.

Dataset v2 is in `ml/data/colab-splits-500-v2`. It corrects 116 targets, preserves all 500 reports and split assignments, records every changed field and original provenance, and uses an explicit AI-corrected-synthetic policy. The v2 notebook and upload ZIP are in `ml/colab`. The user completed a second three-epoch run on an L4 and downloaded it to `bugbrief-qlora-02-adapter/bugbrief-qlora-02`; its files, hashes, and all saved validation outputs were checked in [Adapter_v2_Review_2026-10-15.md](Adapter_v2_Review_2026-10-15.md). Valid/correct expectation labels improved from 42% to 78%, but valid output fell from 94% to 92% and factual errors remain. No test-generation output is included in the download. Individual human review remains unverified. The initial implementation verification below is historical; additional correction checks are documented in the v2 guide.

## Delivered locally

| Area | Implementation |
| --- | --- |
| Frontend | React, TypeScript, Vite; charcoal/teal tokens; responsive report/editor layout, native dialogs, keyboard focus styles |
| Draft workflow | Synthetic example selector; asynchronous queued/running/cancel states; validated model output only |
| Editing | All ticket fields; Reported/Inferred/Unknown expectation labels; explicit source evidence; at most three follow-up questions |
| Review/export | Payload-bound temporary receipt or exact saved revision; edits invalidate review; copy fallback and JSON download |
| Team history | Explicit save, original-source opt-in off by default, shared list, title search, area/status filters, pagination, edit conflicts, scoped deletion |
| Authentication | Supabase Google PKCE browser client; backend asymmetric JWT validation; active workspace membership and viewer/contributor/owner roles |
| Persistence | Local demo SQLite; Supabase PostgreSQL tables, RLS, service-only RPC, atomic revision checks, last ten payload snapshots |
| Inference runtime | Pinned v2 artifact profile, background Qwen/PEFT loading, CPU INT8 option, JSON-schema token constraints, bounded queue and cancellation; CPU packages installed locally |
| Draft checks | Source-bound review hints, recomputed after edits; catches selected known v2 failures without rewriting or certifying the draft |
| ML workflow | 500 unreviewed synthetic candidates; resumable manual review/edit/reject/export; reviewed JSONL contract; family-preserving configurable splits (300/50/50 default, 400/50/50 for 500 rows); QLoRA script, paired baseline/adapter evaluation, Colab/Kaggle notebook |
| Colab package | Upload ZIP with minimal source, pinned GPU libraries, 400/50/50 balanced frozen splits, and explicit bulk-approval provenance; notebook covers smoke training, checkpoint resume, evaluation, and adapter download. No GPU run completed locally. |
| Deployment | Cloudflare Pages configuration notes and a CPU API Dockerfile; not built or deployed |

Local `.env` files were created from the examples without overwriting existing files. Their contents are ignored by Git. Authentication configuration and production mode are explained in the root README.

## Verification

- Backend/data tests: **56 passed**. Coverage includes denied access, role restrictions, workspace isolation, revoked membership, real ES256 signature/issuer/expiry checks with a local key, source opt-in, stale revisions, review invalidation, export binding, deletion, idempotency, request bounds, queue capacity/cancellation, dataset leakage checks, and assistant-only loss masking. Dataset generator checks cover balanced 500-row output, blank reviewer fields, explicit approvals, edits, resumable decisions, stale-approval rejection, export counts, noninteractive review refusal, and frozen split hashes. Colab checks cover explicit bulk-data opt-in, per-example provenance, balanced family-isolated splits, notebook syntax, bundle hashes, and the actual upload/extraction cell. V2 checks include artifact identity, source-bound draft checks, immutable generation metadata, readiness/failure states, known factual-error hints, and JSON grammar constraints. Test review decisions are simulated fixtures only.
- PostgreSQL migration: passed in PGlite's PostgreSQL engine with a minimal Supabase auth/role harness. Checked RPC permissions, viewer writes, RLS reads/revocation, workspace isolation, source-sensitive idempotency, revision conflicts, review invalidation, snapshot retention, and deletion cascade.
- Frontend TypeScript and production build: passed. The frontend schema was generated from Pydantic.
- Browser: Chrome verification covered local access, background loading/readiness, real float32 generation of a known training example, source-comparison findings, explicit field corrections, checks refreshing after edits, required acknowledgement, keyboard Space on the checkbox, reviewed/export-enabled state, and export disabling after another edit. The source pane was inspected at 390 px; the generated editor had no horizontal overflow at that width. The earlier browser bridge error recovered. The synthetic test draft was not saved to ticket history. See the runtime review for the distinction between training-example reproduction and fresh-worded reports.
- Dependency lookup: application dependencies and optional ML package names checked against their registries and official documentation. The pinned CPU model runtime is installed locally; GPU training packages remain separate.
- Colab notebook: passed nbformat validation and Python cell compilation. The actual pinned Qwen tokenizer encoded all 500 rows through the training encoder; maxima were 818 input / 212 assistant / 1,021 total tokens. Bundle extraction and file hashes passed automated checks. The user supplied completed v1/v2 GPU runs; their saved validation results are documented in the adapter reviews. No independent test-set evaluation has been completed.

The test run emits one upstream Starlette/httpx deprecation warning. Assertions are unchanged; the warning was not suppressed.

## Remaining integration work

1. Configure your Supabase environment files, Google provider, redirect URLs, asymmetric signing key, migration, and initial owner membership. Test hosted OAuth/JWKS/PostgREST and a full authenticated ticket flow. These have not been tested against your account.
2. All 500 generated candidates have user bulk approval, recorded in `ml/data/bulk-approval.json`. The Colab bundle can train an explicitly bulk-approved experiment using the frozen `ml/data/colab-splits-500` files. Individual human review remains unverified: the manual review ledger still has 500 pending, zero individually approved. The stricter individual-review workflow remains available through `ml/generate_dataset.py`.
3. Evaluate the selected serving runtime on independent reports with human factual review, then use the frozen test set for a release decision. The downloaded validation results leave known factual errors; automated source hints do not resolve them.
4. Measure local inference latency and the bounded queue with the pilot, and verify the runtime on the eventual hosting platform. No 20-user load result exists.
5. Provision the chosen free services, configure HTTPS, and verify deployment limits. No resource or hosted URL has been created.

This first implementation manages workspace membership through trusted Supabase SQL rather than an invitation/admin screen. It stores bounded revision snapshots but does not expose a revision restore interface. Attachments, Jira submission, automatic severity, and cause diagnosis remain outside scope.
