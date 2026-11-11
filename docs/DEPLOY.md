# Deploy: Supabase (data), Render (API), Vercel (web)

Three pieces, each on a free plan. The API runs on the mock provider until you add a Gemini key;
nothing else changes when you do.

```
browser ── Vercel (web/, Next.js) ──HTTPS──> Render (Dockerfile, FastAPI) ──> Supabase (Postgres)
```

Why the API is not on Vercel: it keeps fitted search indexes in memory between questions, which a
serverless function would rebuild on every call.

## 1. Supabase (database)

1. Create a project at supabase.com; note the database password.
2. Project settings, Database, Connection string: copy the **Transaction pooler** URI (port
   6543). It looks like `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres`.
3. SQL editor: paste and run `src/ainma/store/postgres_schema.sql` (the API also creates it).
4. Load the synthetic corpus from your machine, once:
   ```bash
   pip install -e ".[dev,postgres]"
   ```
   ```bash
   make data
   ```
   ```bash
   STORE_BACKEND=postgres DATABASE_URL='<the URI>' python -m ainma.store.load --seed 1234
   ```
   It prints `loaded 280 documents, 523 chunks into the postgres store`.

The tables have no row level security: only the API connects, with the database password, and it
filters every query by deal membership. Never put this URI in the web client.

## 2. Render (API)

1. render.com, New, Blueprint, pick this repository: `render.yaml` creates `ainma-api` from the
   `Dockerfile` (it installs the package and generates the seed corpus at build time).
2. Environment of `ainma-api`: set `DATABASE_URL` (the Supabase URI) and `ALLOWED_ORIGINS`
   (your Vercel URL, e.g. `https://ainma.vercel.app`; several are separated by commas).
3. Deploy, then open `https://<service>.onrender.com/health`: it answers
   `{"status":"ok",...,"store_backend":"postgres"}`.

The free plan sleeps after inactivity; the first request after a pause takes about a minute.

## 3. Vercel (web)

1. vercel.com, Add New, Project, import this repository, **Root Directory: `web`**.
2. Environment variable `NEXT_PUBLIC_API_URL` = the Render URL (no trailing slash).
3. Deploy. Without `NEXT_PUBLIC_API_URL` the client runs on its built-in example payloads and says
   `mock data`.

## 4. Turning on the live services

In the Render environment, then redeploy:

| Variable | Value | Effect |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | the writer and the judge become Gemini (`LLM_MODEL`, default `gemini-2.5-flash`) |
| `GEMINI_API_KEY` | your key | required by the line above; a failed call answers 503, never a silent mock |
| `JUDGE_MODEL` | optional, e.g. `gemini-2.5-flash` | a judge distinct from the writer |
| `TAVILY_API_KEY` | your key | live news search on the Market page |

To measure the live model offline before or after, see `make live-smoke` and `make eval PROVIDER=gemini`.

## Before you share the URL

- Authentication is a demo header (`X-User-Id`, `DEMO_AUTH`): anyone who has the API URL can call it
  as any demo user. The data is synthetic, so nothing leaks, but with a Gemini or Tavily key anyone
  can spend your quota. Keep the URLs private, or add real authentication first (another
  workstream owns it).
- Every page shows `synthetic data`: no real company, figure or document is in the corpus. Live
  news fetched through Tavily is public web text and is labelled `live`.

## Checked here

The image was built and run against a local Postgres 16: the corpus loaded (280 documents, 523
chunks), `/health` answered with `store_backend: postgres`, a question returned a cited answer with
its contradiction, and the CORS preflight from an allowed origin returned 200. Render, Vercel and
Supabase themselves were not used from this environment.
