# DeepShield API

FastAPI backend that classifies an uploaded image / video / audio file and routes
it to the appropriate deepfake-detection provider.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Environment variables

Copy these into a local `.env` file (never commit it):

| Variable | Required | Purpose |
|---|---|---|
| `BITMIND_API_KEY` | Yes | BitMind deepfake detection for images and videos |
| `REALITY_DEFENDER_API_KEY` | Yes | Reality Defender audio deepfake detection |
| `CORS_ORIGINS` | No | Comma-separated allowed origins (defaults to localhost:5173/3000) |
| `MAX_UPLOAD_MB` | No | Upload size cap in MB (default `100`) |
| `RD_POLL_MAX_ATTEMPTS` | No | Reality Defender poll attempts (default `150` ≈ 5 min) |
| `RD_POLL_INTERVAL_MS` | No | Reality Defender poll interval in ms (default `2000`) |
| `RATE_LIMIT_MAX_REQUESTS` | No | Analyses allowed per client per window (default `30`) |
| `RATE_LIMIT_WINDOW_SECONDS` | No | Rate-limit window length (default `600`) |
| `RATE_LIMIT_MAX_CONCURRENT` | No | Analyses allowed to run at once (default `3`) |

`/analyze` returns `429` with a `Retry-After` header when a client exceeds the
request budget or when too many analyses are already running. Counters are
in-process, so they are per-worker: a multi-worker or multi-instance deployment
needs a shared store instead.

The frontend reads its backend URL from `VITE_BACKEND_URL` (see `deepshield/README.md`).
