# BugBrief

BugBrief turns short English reports about the fictional LedgerFlow product into structured tickets. A person checks the draft before copying text or exporting JSON. The interface uses charcoal surfaces, a teal accent, and a compact editor with the report alongside the ticket.

## Current implementation

- React/TypeScript interface with an editable ticket, explicit review, text/JSON export, shared ticket history, search, filters, and revision-conflict handling.
- FastAPI with the canonical Pydantic ticket schema, a bounded generation queue, per-user limits, cancellation, source opt-in, and version-specific review/export checks.
- Supabase Google OAuth integration and a PostgreSQL migration with workspace membership, roles, RLS, atomic revisions, and a service-only RPC.
- A loopback-only local workspace with SQLite persistence and development access. `INFERENCE_MODE=examples` supplies four fixed synthetic drafts; `transformers` runs the configured model.
- Pinned Transformers CPU inference with the experimental v2 profile, plus a QLoRA training/evaluation notebook for Colab or Kaggle.

Two adapters have been trained in Colab. The [first review](doc/Adapter_Review_2026-10-15.md) found reference-label inconsistencies and factual errors. The [v2 review](doc/Adapter_v2_Review_2026-10-15.md) verifies training with corrected targets: valid tickets with correct expectation labels improved from 42% to 78% on the same v2 validation references, while schema validity slipped from 94% to 92%. Factual errors remain. Individual human dataset review, hosted Google login, and cloud deployment remain incomplete. These checks do not establish production quality or 20-user inference capacity.

The [local v2 application pipeline](doc/V2_Pipeline.md) connects the downloaded adapter to the existing workspace. It verifies model identity, loads in the background, constrains JSON structure, checks source wording, and requires explicit review before export. This computer is configured for float32 CPU inference with the experimental v2 profile. Start it with `npm.cmd run dev` in PowerShell. The pinned base weights are cached locally.

The [local runtime review](doc/V2_Runtime_Review.md) records a successful training-example reproduction and a rejected fresh-worded report with factual errors. The pipeline is connected; the adapter still needs a factual release evaluation before team use.

## Run locally

Use Node.js 22.12+ and Python 3.12. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
npm.cmd ci
npm.cmd --prefix frontend ci
if (!(Test-Path backend/.env)) { Copy-Item backend/.env.example backend/.env }
if (!(Test-Path frontend/.env)) { Copy-Item frontend/.env.example frontend/.env }
npm.cmd run dev
```

Copy the examples only if your `.env` files do not already exist. The local `.env` files were created for this initial build. Keep them out of Git. On macOS/Linux, use `.venv/bin/python` and `cp` for the corresponding commands.

Open **http://127.0.0.1:5173**, choose **Open local workspace**, select a synthetic example, and draft the ticket. The example configuration uses fixed drafts; follow [the v2 pipeline guide](doc/V2_Pipeline.md) to enable the downloaded adapter. Edit a field, review it, then copy or download. Save a draft to try team history. Saving the original report is unchecked by default; extracted details and supporting excerpts still persist inside the ticket.

The runner starts one API process on port 8000 and Vite on 5173, both bound to loopback. Stop with Ctrl+C. Demo tickets live in `backend/.data/demo.sqlite3`. Unsaved reports and temporary review receipts expire on the server after 15 minutes; refreshing the browser clears the unsaved editor. Browser sessions use session storage for authentication tokens.

## Connect your Supabase project

1. In the project's SQL editor, run [database/migrations/001_initial.sql](database/migrations/001_initial.sql) once on a fresh schema. It creates the LedgerFlow workspace. Use a backup and a separate test project before adapting it to an existing populated schema.
2. Enable Google in Authentication → Providers. Create a Google OAuth web client and use the Supabase callback URL shown there (normally `https://PROJECT.supabase.co/auth/v1/callback`). Put the Google client secret in Supabase, not in the app.
3. In Authentication → URL Configuration, add `http://127.0.0.1:5173/auth/callback` and `http://localhost:5173/auth/callback` as local redirects. Use the exact published frontend URL and its `/auth/callback` route when deployed.
4. Use an **asymmetric JWT signing key** (ES256 or RS256). This API verifies signatures through Supabase JWKS, issuer, audience, and expiry; it does not accept legacy HS256 tokens.
5. Fill `frontend/.env` with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. A publishable key or legacy anon key is appropriate here. Keep `VITE_API_BASE_URL=/api` for local Vite proxying.
6. Fill `backend/.env` with `SUPABASE_URL` and `SUPABASE_SECRET_KEY` (a secret key or legacy service-role key). Set `BUGBRIEF_MODE=production` and initially `INFERENCE_MODE=disabled`. This enables real authentication and saved-ticket access while model inference is not configured. Restart both processes after changing environment files.
7. Sign in once with Google. The account sees **Access not granted** until an owner adds an active workspace membership. In the trusted SQL editor, run the following with your account's actual email:

```sql
insert into public.workspace_members(workspace_id,user_id,role)
select '00000000-0000-4000-8000-000000000010',id,'owner'
from auth.users where email='YOUR_GOOGLE_EMAIL';
```

For each pilot teammate, let them authenticate once, then add their exact user ID/email with role `contributor` or `viewer` using the same trusted procedure. Avoid duplicate inserts; inspect existing membership first. Revoke access by setting `active=false`. New OAuth identities alone do not receive workspace data access. This first version uses owner-managed membership; it does not send invitations or have an admin UI. Supabase may allow identities to register while application access stays invite-only.

The backend uses a privileged database key, so every route derives user identity from a verified JWT and checks membership. The SQL RPC rechecks membership and role within each transaction. Browser database writes and browser RPC execution are denied. Never put the backend secret in a `VITE_` variable.

See the official [Supabase Google setup](https://supabase.com/docs/guides/auth/social-login/auth-google), [JWT signing keys](https://supabase.com/docs/guides/auth/signing-keys), and [API key documentation](https://supabase.com/docs/guides/api/api-keys).

## Model training and inference

For the corrected Colab experiment, upload [BugBrief_Training_v2.ipynb](ml/colab/BugBrief_Training_v2.ipynb), select a GPU runtime, and upload [BugBrief_Colab_v2_Bundle.zip](ml/colab/BugBrief_Colab_v2_Bundle.zip) when prompted. The bundle includes all required code and frozen, balanced 400/50/50 splits. Dataset v2 corrects 116 targets while preserving the 500 original reports and split assignments. Corrections are AI-authored and individual human review remains unverified; that experimental data policy and the original bulk approval are recorded separately. The notebook includes a GPU smoke check, training, checkpoint resume, paired validation evaluation, and adapter download. The user's completed v2 run is saved in `bugbrief-qlora-02-adapter/bugbrief-qlora-02`; its review is linked above. Follow [the v2 Colab guide](ml/colab/README-v2.md) to reproduce the experiment with a fresh output directory.

Read [ml/README.md](ml/README.md) for the separate individual review/export workflow. The default individually reviewed split is 300/50/50 for 400 pairs; use `--train-count 400` for 500 pairs. Both workflows keep scenario families together, mask prompt tokens from the training loss, and compare the adapter against the same base model and prompt.

For CPU serving, install the additional dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-model.in
```

For the downloaded v2 export, run `.\.venv\Scripts\python.exe scripts/configure_v2.py`; it selects `MODEL_PROFILE_PATH=models/v2.json` and verifies the adapter/run hashes before loading. For a custom runtime, set `INFERENCE_MODE=transformers`, a full Hugging Face commit in `MODEL_REVISION`, and the adapter directory in `ADAPTER_PATH`. A remote adapter also needs `ADAPTER_REVISION`. With no profile or adapter, the runtime serves the **untrained base-model prompt baseline**. The app reports the active provider and never falls back to synthetic drafting for arbitrary input. See the pipeline guide for constraints, source checks, and live verification commands.

CPU loading uses float32 and needs several GB of temporary RAM plus model cache space. `MODEL_CPU_QUANTIZATION=int8` merges the adapter in RAM and quantizes CPU linear layers to reduce steady memory use; `none` preserves float32 inference. Quantization and constrained decoding change the runtime and require their own factual evaluation. One request runs at a time and four wait in the queue. No sustained-load capacity has been measured yet.

## Free deployment path

For Vercel frontend setup, see [deploy/Vercel.md](deploy/Vercel.md). Backend/model hosting and Supabase configuration are separate steps; the local development API is not exposed publicly by those frontend instructions.

The proposed pilot uses **Cloudflare Pages** for the static frontend and **Supabase Free** for Google authentication and PostgreSQL. For a business/team deployment, check each service's current usage limits. Colab and Kaggle are training environments, not reliable API hosts.

The architecture's CPU API option is an **Oracle Always Free Arm VM**, conditional on account eligibility, available capacity, and a measured CPU latency test. [deploy/README.md](deploy/README.md) includes the API container and frontend settings. No cloud resources have been created.

Your eligible Hugging Face account can also try **ZeroGPU** for a Gradio model demo. It has user quotas and hosting requirements; a shared backend caller does not grant each Supabase user an independent Hugging Face allowance. A production ZeroGPU bridge is not implemented. See [Hugging Face ZeroGPU](https://huggingface.co/docs/hub/spaces-zerogpu) and the architecture decision in [doc/Architecutr.md](doc/Architecutr.md).

## Checks

```powershell
npm.cmd run build
npm.cmd run test:database
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

The database check uses PGlite's PostgreSQL engine with a minimal Supabase auth/role harness. Hosted OAuth, JWKS retrieval, and PostgREST still require a live Supabase integration check. Regenerate the frontend contract after changing the Pydantic schema:

```powershell
.\.venv\Scripts\python.exe scripts/generate_contract.py
```

Architecture and diagrams: [doc/Architecutr.md](doc/Architecutr.md). Design tokens, UX, and component behavior: [doc/Design.md](doc/Design.md). Implementation status and verification: [doc/Implementation.md](doc/Implementation.md).
