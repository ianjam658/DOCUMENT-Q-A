# Document Q&A — Production

Upload PDFs, ask questions grounded in their actual content (RAG). This version is built to run as a real, paid service — not a demo.

## What's different from a toy version
- **Persistent storage**: Postgres + pgvector, not a local file that disappears on redeploy.
- **Auth**: every `/upload`, `/ask`, `/reset` call requires an `X-API-Key` header.
- **Rate limiting**: per-endpoint limits to protect your Groq API budget from abuse.
- **Multi-tenant ready**: an optional `X-Tenant-ID` header keeps each client's documents separate, so you can sell this to more than one customer from one deployment.
- **Input validation**: file type, file size, question length all checked.
- **Error handling**: no unhandled exceptions reach the client; everything returns clean JSON with an appropriate status code.
- **Logging**: structured logs for every upload, query, and error.
- **Health check**: `/health` for uptime monitors and Render's own health checks.
- **Tests**: `tests/test_app.py` — run with `pytest`.

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | Yes | From console.groq.com/keys |
| `GROQ_MODEL` | No | Default `llama-3.3-70b-versatile`; `llama-3.1-8b-instant` is cheaper/faster if quality holds up for your use case |
| `DATABASE_URL` | Yes | Postgres connection string, must support pgvector |
| `API_SECRET_KEY` | Yes | Secret clients must send as `X-API-Key`. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `REDIS_URL` | No | Needed only if running >1 server instance, for shared rate-limit state |
| `MAX_FILE_SIZE_MB` | No | Default 15 |
| `ALLOWED_ORIGINS` | No | CORS allowlist, comma-separated. Default `*` — restrict this in real production |
| `RATE_LIMIT_DEFAULT` / `_UPLOAD` / `_ASK` | No | Sensible defaults included |

## Deploy to Render (recommended path)
1. Push this repo to GitHub.
2. On Render: New → Blueprint → connect the repo. `render.yaml` provisions both the web service and a managed Postgres database automatically, and its `startCommand` runs the app through `gunicorn` (not `python app.py` directly).
3. In the dashboard, set `GROQ_API_KEY` and `API_SECRET_KEY` (marked `sync: false`, so Render will prompt for them).
4. Deploy. Render runs the health check against `/health` before routing traffic to the new instance.
5. **Enable pgvector**: Render Postgres supports the extension, but you can confirm by connecting with `psql` and running `CREATE EXTENSION IF NOT EXISTS vector;` — the app also does this automatically on startup.

### Two build issues this repo already avoids
- **CPU-only PyTorch**: `sentence-transformers` pulls in PyTorch, and by default pip grabs the full GPU/CUDA build — over 2.5GB of NVIDIA libraries you don't need on a CPU-only Render instance, which alone can blow a small build's storage quota. `requirements.txt` pins `torch==2.3.1+cpu` via PyTorch's own CPU wheel index, cutting that down to roughly 200MB.
- **Python version**: `runtime.txt` pins Python to `3.11.9`. Without it, Render may build against a very new Python release before packages like `psycopg2-binary` have published compatible prebuilt wheels for it, causing an `ImportError: undefined symbol` crash at startup that has nothing to do with your code.

If you deployed this manually as a plain "Web Service" instead of via Blueprint, double check the start command is `gunicorn app:app --workers 2 --timeout 120` and not the default `python app.py` — the logs will show "Running 'python app.py'" if it's using the wrong one.


Note: `render.yaml` uses the `starter` (paid) plan for both the web service and database. Free tier Postgres on Render expires after 90 days and free web services sleep after inactivity — neither is acceptable for a paid product. Use `starter` for anything real; drop to `free` only while testing.

## Deploy with Docker (any host: Railway, Fly.io, a VPS, etc.)
```bash
docker build -t docqa .
docker run -p 8000:8000 --env-file .env docqa
```

## Run locally
```bash
git clone <your-repo-url>
cd docqa
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with real values — you need a real Postgres with pgvector even locally
# (easiest: free Supabase project, or `docker run -p 5432:5432 pgvector/pgvector:pg16`)
python app.py
```

## Run tests
```bash
pytest
```
These are smoke tests (auth enforcement, health check, input validation) that don't require a live database. Add integration tests against a real Postgres instance before you fully trust this in production.

## Security notes — read before charging money for this
- Rotate `API_SECRET_KEY` if you ever suspect it leaked, and don't hardcode it in frontend JS shipped to end users — put it behind your own backend if end users shouldn't see it.
- Set `ALLOWED_ORIGINS` to your actual frontend domain, not `*`, once you have one.
- The current auth model is a single shared secret. Fine for one or a handful of trusted clients. For self-serve signups, add a `customers` table with per-customer hashed API keys before opening this up publicly.
- Put this behind HTTPS (Render does this automatically; if you self-host, use a reverse proxy with TLS).

## Scaling notes
- Multiple instances → set `REDIS_URL` so rate limiting is shared across instances instead of per-instance.
- Gunicorn worker count: 2 is a safe starting point for Render's smallest plan; increase with more CPU/RAM.
- The embedding model loads into memory once per worker process — more workers means more RAM used, so scale workers and instance size together.
