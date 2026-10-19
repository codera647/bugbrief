# Pilot deployment

These are deployment instructions and a container definition, not a deployed service. The Docker image has not been built in this initial pass. Use the free hosting decisions and contingencies in `doc/Architecutr.md`.

## Frontend: Cloudflare Pages

For the requested Vercel frontend target, use [Vercel.md](Vercel.md). The API/model process stays on a separate host; the Cloudflare instructions below remain an alternative.

- Project root: `frontend`.
- Build command: `npm ci && npm run build`.
- Output directory: `dist`.
- Build variables: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, and `VITE_API_BASE_URL=https://YOUR_API_HOST`.
- Add the published frontend `/auth/callback` URL to Supabase's redirect allowlist.

`public/_redirects` provides the SPA fallback. Vite's `/api` proxy is development-only. Rebuild when public environment values change. The backend secret is never a frontend build variable.

## API: an available free CPU VM

The proposed Oracle Always Free VM needs enough RAM for the float32 model, available Arm capacity, persistent disk for model cache, and an HTTPS endpoint. Set a budget alert and verify the instance/volume labels before provisioning. Free eligibility and availability can change. No claim of measured 20-user capacity is made.

From the project root:

```bash
docker build -f deploy/Dockerfile -t bugbrief-api .
docker run --name bugbrief-api --restart unless-stopped \
  --env-file /secure/path/bugbrief.env \
  -v bugbrief-hf-cache:/home/bugbrief/.cache/huggingface \
  -v /secure/path/reviewed-adapter:/models/adapter:ro \
  -p 127.0.0.1:8000:8000 bugbrief-api
```

Set `BUGBRIEF_MODE=production`, `INFERENCE_MODE=transformers`, Supabase server credentials, a pinned `MODEL_REVISION`, `ADAPTER_PATH=/models/adapter`, and `ALLOWED_ORIGINS=https://YOUR_FRONTEND_HOST`. Provide only the approved release adapter in the mounted directory. The first model download can take several minutes. The cache volume must be writable by UID 10001; provision its ownership before startup.

Put an HTTPS reverse proxy in front of the loopback port. Keep request body limits, short header/body timeouts, and no request-body logging at the proxy. Restrict direct port 8000 exposure. Run **one API worker** because the queue and ephemeral reports are held in process memory; multiple workers would give inconsistent job polling.

Monitor `/health/live` for process liveness and `/health/ready` for model availability. Measure real generation latency and queue behavior with 10–20 pilot users before declaring capacity acceptable. Model readiness does not check the Supabase database connection; verify `/v1/session` and a complete save/review/export flow after deployment.

The core API dependencies are locked; model-library versions, including Torch 2.11.0, are pinned in the optional requirements. The container selects the CPU build explicitly. Docker compilation, a complete target-platform dependency lock, VM setup, HTTPS, account quotas, hosted OAuth, and a load check remain unverified.

## Pinned v2 profile

The local computer-first pipeline is documented in [doc/V2_Pipeline.md](../doc/V2_Pipeline.md). To use its profile in a container, mount the full exported run (including `run.json` and `adapter/`) at `/srv/bugbrief/bugbrief-qlora-02-adapter/bugbrief-qlora-02`, matching the relative path in `models/v2.json`. Set `MODEL_PROFILE_PATH=models/v2.json`. A changed adapter/run fails verification rather than silently loading a different candidate.

Set `MODEL_DEVICE=cpu`, `MODEL_CPU_THREADS` for the target host, `MODEL_CPU_QUANTIZATION=int8` if choosing the dynamic INT8 variant, and `CONSTRAINED_OUTPUT=true`. Record those settings with evaluation results: the saved Colab validation results used an unquantized, unconstrained runtime. Keep production auth settings and HTTPS as described above. No v2 container or cloud deployment has been verified yet.
