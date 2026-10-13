<div align="center">

# 🛡️ DeepShield

**Multimodal AI-manipulation detection — verify before you trust.**

Upload a suspicious image, video, or audio file and get an instant, unified
risk assessment powered by specialized deepfake-detection engines.

</div>

---

## What it does

DeepShield answers one question: **can this media be trusted?**

1. Upload any common image (`.jpg/.png/.webp/…`), video (`.mp4/.webm/.mov/…`),
   or audio (`.mp3/.wav/.ogg/…`) file — drag & drop or file picker.
2. The backend routes the file to the right detection engine automatically.
3. You get a single unified verdict: an animated 0–100 risk gauge
   (LOW / MEDIUM / HIGH), a plain-language summary, a per-model signal
   breakdown, media metadata, and risk-tiered security advice
   (e.g. *"do not make financial decisions based on this media — verify the
   source through an independent channel"*).

| Media type | Detection engine | Notes |
|---|---|---|
| Images | [BitMind](https://bitmind.ai) AI-generation detection | |
| Videos | BitMind video deepfake detection | longer timeouts |
| Audio | [Reality Defender](https://www.realitydefender.com) multi-model ensemble | per-model scores surfaced in the UI |

> DeepShield does **not** train its own models — it orchestrates
> state-of-the-art third-party detectors and translates their raw output
> into one clear, explainable assessment.

## Architecture

```
┌───────────────────────────── Freebuff / one port ─────────────────────────────┐
│                                                                              │
│  Browser ──► server.js (Express, PORT)                                       │
│                │  /analyze, /api/*  ──► proxy ──► FastAPI (uvicorn :8901)    │
│                │                                       │   deepshield-       │
│                └─ /  ──► Vite middleware               │   backend/main.py   │
│                   (React + Tailwind SPA)               │        │            │
│                                                        ▼        ▼            │
│                                              BitMind API   Reality Defender  │
└──────────────────────────────────────────────────────────────────────────────┘
```

- `deepshield/` — React 19 + Vite + Tailwind 4 frontend, plus `server.js`
  (single-port launcher: backend child process + API proxy + Vite middleware).
- `deepshield-backend/` — FastAPI backend: media-type detection, provider
  routing, response normalization (`risk_score`, `risk_level`, `prediction`,
  `signals`), upload size caps, streaming uploads.

## Quickstart

**Prerequisites:** Node.js 18+, Python 3.10+, and API keys for
[BitMind](https://bitmind.ai) and [Reality Defender](https://www.realitydefender.com).

```bash
# 1. Backend deps
pip install -r deepshield-backend/requirements.txt

# 2. Frontend deps
cd deepshield && npm install

# 3. API keys — put these in deepshield-backend/.env (never commit it)
#    BITMIND_API_KEY=...
#    REALITY_DEFENDER_API_KEY=...

# 4. Run everything (frontend + backend + proxy) on one port
npm start          # → http://localhost:3000
```

Frontend-only dev against a separately running backend:

```bash
uvicorn main:app --port 8000            # in deepshield-backend/
echo 'VITE_BACKEND_URL=http://127.0.0.1:8000' > deepshield/.env.local
npm run dev                             # in deepshield/
```

## Configuration

Frontend (`VITE_*`, set in `deepshield/.env.local`):

| Variable | Default | Purpose |
|---|---|---|
| `VITE_BACKEND_URL` | *(same origin)* | Backend base URL; leave empty when using `npm start` |

Backend (`deepshield-backend/.env`) — see
[backend README](deepshield-backend/README.md) for the full table:

| Variable | Required | Purpose |
|---|---|---|
| `BITMIND_API_KEY` | ✅ | Image/video detection |
| `REALITY_DEFENDER_API_KEY` | ✅ | Audio detection |
| `CORS_ORIGINS` | – | Extra allowed origins |
| `MAX_UPLOAD_MB` | – | Upload cap, default 100 |
| `RD_POLL_MAX_ATTEMPTS` / `RD_POLL_INTERVAL_MS` | – | Audio polling window, default ≈5 min |

## API

`POST /analyze` — multipart `file` field. Returns:

```jsonc
{
  "success": true,
  "media_type": "audio",
  "prediction": "LIKELY_MANIPULATED",   // LIKELY_AI_GENERATED | LIKELY_MANIPULATED | LIKELY_AUTHENTIC | INCONCLUSIVE
  "risk_score": 87.0,                   // 0–100, clamped
  "risk_level": "HIGH",                 // LOW <30 | MEDIUM <70 | HIGH
  "confidence": 87.0,
  "provider": "Reality Defender",
  "signals": [ { "name": "...", "value": "MANIPULATED", "score": 87.0 } ],
  "analysis_time": 4.21,
  "filename": "clip.mp3"
}
```

Also: `GET /health`, `GET /` on the backend; everything is proxied
same-origin through the frontend port when using `npm start`.

## Project layout

```
deepshield/                 React frontend
  src/App.tsx               Upload → Analyzing → Results / Error state machine
  src/components/           UploadZone, FilePreview, AnalysisLoader, RiskMeter,
                            ResultSummary, SecurityRecommendation, AnalysisDetails, …
  src/services/analysisService.ts   POST /analyze + result mapping
deepshield-backend/         FastAPI backend
  main.py                   /analyze endpoint, upload limits, temp-file handling
  services/analyzer.py      provider routing + response normalization
  services/bitmind.py       BitMind image/video client
  services/reality_defender.py  Reality Defender audio client
  utils/media.py            extension/MIME media-type detection
  test_*.py                 manual provider smoke tests
```

## Status & scope

Working MVP: single-file analysis of images, videos, and audio end-to-end.
Not implemented (yet): analysis history/persistence, accounts, batch or
URL-based scanning, report export. Results are automated risk assessments —
**not** definitive proof of authenticity or manipulation.

## Disclaimer

DeepShield provides probabilistic detection and can produce false positives
and false negatives. Treat results as one signal among several, and verify
important media through independent trusted channels.
