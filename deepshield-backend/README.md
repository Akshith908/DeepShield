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

## Visual explanations (`POST /explain`, optional)

Separate from `/analyze`: a local EfficientNet-B4 face classifier produces a
genuine Grad-CAM heatmap (`honi05/deepfake-detection`, MIT, Celeb-DF v2 face
crops). The provider flow is untouched — a missing checkpoint or a failed
inference only affects this endpoint.

```bash
pip install -r requirements.txt -r requirements-gradcam.txt
python3 scripts/download_model.py   # 72.8 MB, public, no token required
```

Weights are never committed (see `.gitignore`) and are loaded once per process
on the first request. Without the ML extras installed, `POST /explain` returns
`503 model_unavailable` and the rest of the API behaves exactly as before.

The model's own prediction (`FAKE`/`REAL`) is reported separately from the
provider verdict and never replaces it. Measured on 1 vCPU / 1.9 GB: ~1.0 s
torch import, ~1.4 s model load, ~0.5-2 s per image, ~750 MB peak RSS.

| Variable | Required | Purpose |
|---|---|---|
| `DEEPSHIELD_MODEL_PATH` | No | Checkpoint path (default `models/best_model.pt`) |
| `DEEPSHIELD_EXPLANATION_MAX_SIDE` | No | Max overlay/heatmap edge in px (default `1024`) |
| `DEEPSHIELD_MAX_PIXELS` / `DEEPSHIELD_MAX_IMAGE_SIDE` | No | Input guardrails (defaults 40 MP / 12000 px) |
| `EXPLAIN_RATE_LIMIT_MAX_REQUESTS` / `EXPLAIN_RATE_LIMIT_WINDOW_SECONDS` | No | Separate budget for `/explain` (default 20 / 600 s) |
| `DEEPSHIELD_GRADCAM_LOCK_TIMEOUT` | No | Seconds to wait for the inference lock (default `20`, then `429`) |

Error codes returned in `detail.code`: `model_unavailable` (503),
`no_face_detected` (422), `invalid_image` / `unsupported_format` (400),
`image_too_large` (413), `inference_failed` (500), `busy` (429).

The frontend reads its backend URL from `VITE_BACKEND_URL` (see `deepshield/README.md`).
