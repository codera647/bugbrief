# Vercel frontend deployment

The Vercel project deploys `frontend/`. The FastAPI process and v2 inference model need a separate host with enough RAM and one long-running worker. The current in-memory queue, transient reports, and review receipts require that process to stay available between requests. The local development backend is not a public production endpoint.

## Login

Run in your own PowerShell terminal:

```powershell
npx.cmd vercel@latest login
```

The CLI stores your login locally. Do not paste its authentication token into chat or commit it. `.vercel/`, local environment files, databases, inference artifacts, and downloaded adapter archives are excluded from Git.

## Project settings

For a GitHub import, set **Root Directory** to `frontend`, **Framework** to Vite, **Install Command** to `npm ci`, **Build Command** to `npm run build`, and **Output Directory** to `dist`. The checked-in `frontend/vercel.json` provides the SPA fallback, including `/auth/callback`.

For a CLI deployment, work from the frontend directory:

```powershell
cd F:\Bug_Brief\frontend
npx.cmd vercel@latest link
npx.cmd vercel@latest deploy
```

Before making the app available for use, configure these build-time values in Vercel and rebuild:

| Variable | Value |
| --- | --- |
| `VITE_API_BASE_URL` | Public HTTPS URL of the separately hosted FastAPI service, without a trailing `/v1` |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_PUBLISHABLE_KEY` | Browser publishable key or legacy anon key |

Keep `SUPABASE_SECRET_KEY` on the backend only. Frontend variables are public in the built JavaScript. The `/api` development proxy in `vite.config.ts` does not exist on Vercel; `127.0.0.1` would refer to each visitor's computer.

On the backend, enable production mode, configure Supabase and initial membership, and set `ALLOWED_ORIGINS` to the exact deployed frontend origin. Add the frontend `/auth/callback` URL to Supabase's redirect allowlist. Use a stable production origin for Google login; arbitrary preview URLs are not automatically allowed.

The frontend can be prepared before the backend is hosted. A frontend-only URL does not provide ticket drafting, login, or history until its API and authentication configuration are connected. Do not describe it as a working full application.

## Verify before release

Build the frontend, verify a deep-link refresh on `/auth/callback`, then test real Google login, workspace authorization, model readiness, generation, explicit save, review, export, and edit invalidation against the hosted API. A successful static build does not verify those integrations. The v2 factual limitations in [the runtime review](../doc/V2_Runtime_Review.md) still apply.

References: [Vercel CLI login](https://vercel.com/docs/cli/login), [Vite on Vercel](https://vercel.com/docs/frameworks/frontend/vite), and [Function limits](https://vercel.com/docs/functions/limitations).
