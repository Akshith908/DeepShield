# Visual-explanation error copy — what it means and how to reproduce it

Every message below is intentional, versioned in this repo, and surfaced only by
`POST /explain`. It is built so a failed visual explanation never changes the
provider-backed analysis result.

## 1. `The visual-explanation service returned an invalid response.`

- Machine code: `invalid_response`
- Where it is raised: `deepshield/src/services/analysisService.ts`
- When it happens:
  - `/explain` returns HTTP non-200 **and** the JSON body doesn't contain a
    usable `{code, message}` detail object.
  - The response body is not valid JSON at all.
  - The response is HTTP 200 but the JSON is missing `success`, `heatmap`, or
    `overlay`, or those fields are not valid `data:image/...` data URIs.
  - The response is otherwise well-formed but `local_prediction` is neither
    `"FAKE"` nor `"REAL"`.
- What the user sees: the error alert block in `VisualExplanation.tsx`, with
  the helper line `No heatmap is shown when generation fails. The provider
  result above is unaffected.`
- How to reproduce it (false-positive friendly):
  - Point `VITE_BACKEND_URL` at a stub that returns a non-image HTTP 200 with
    JSON missing those fields.
  - Point it at a server that returns valid JSON but no `heatmap`/`overlay`.
  - Serve a non-JSON body from `/explain`.
  - Return `"local_prediction": "UNKNOWN"` from the backend.
- What it does **not** mean: the main analysis endpoint is broken. `/analyze`
  uses a different client path (`analyzeMedia`) and its own error text.

## 2. `The visual explanation took too long and was cancelled.`

- Machine code: `timeout`
- Where it is raised: `deepshield/src/services/analysisService.ts`
- Timeout value: `EXPLANATION_TIMEOUT_MS = 120_000` (2 minutes) for the local
  Grad-CAM endpoint. The main `/analyze` endpoint has a different, longer cap
  (`REQUEST_TIMEOUT_MS = 330_000`).
- When it happens: the browser aborts the `fetch` because `/explain` has not
  returned within the 2-minute local-inference timeout. This is the client-side
  timeout path, not the server raising its own error.
- What the user sees: same alert block, with the helper line about no heatmap
  being shown.
- How to reproduce it (false-positive friendly):
  - Make `/explain` stall past 2 minutes without replying.
  - Cut network between the browser and the backend during the call.
- How it is **not** triggered: a fast failed request, a 503, a 422, etc. Those
  are the `invalid_response` or HTTP-error paths above.

## 3. `Could not reach the visual-explanation service.` / network_error

- Machine code: `network_error`
- Where it is raised: `deepshield/src/services/analysisService.ts`
- When it happens: `fetch` to `/explain` throws before getting any HTTP response
  (DNS failure, connection refused, offline browser, CORS blocking the request,
  etc.).
- What the user sees: same alert block with the same helper line.
- How to reproduce it:
  - Set `VITE_BACKEND_URL` to a host that isn't running.
  - Block the request at the network / CORS layer so the browser never gets a
    response.
- Note: this is a transport failure, not a backend bug report. A 500 from the
  backend would still reach the `invalid_response` or HTTP-error path because
  the response is received; only a complete failure to reach the service becomes
  `network_error`.

## The shared helper line under every error

`No heatmap is shown when generation fails. The provider result above is unaffected.`

- This text is intentional and unchanged. It is rendered by `VisualExplanation.tsx`
  whenever `phase === 'error'`.
- The point is separation: the Grad-CAM panel is an optional local model beside
  the provider verdict, so its failure must be visually and semantically separate
  from the main result.

### Where this copy lives

- UI copy: `deepshield/src/components/VisualExplanation.tsx`
- Provider-side fail-safe copy: `deepshield-backend/main.py` and
  `deepshield-backend/services/gradcam_explainer.py` speak to the same
  separation concern for backend-generated failures (`ExplainError` or a
  wrapped exception), but they do not duplicate the exact frontend sentence.

## Backend-side mapping (for context, not user-facing copy)

`deepshield-backend/main.py` turns `ExplainError` subclasses into structured
HTTP details with `{code, message}`. Those flow back to the frontend and become
the `code` / `message` in the `VisualExplanationError` above. Common backend
codes you may see through the same UI path:

- `model_unavailable` → 503
- `invalid_image` / `unsupported_format` / `image_too_large` → 400/413
- `no_face_detected` → 422
- `inference_failed` → 500
- `busy` → 429

Those backend codes are part of `/explain` and are expected to stay separate from
the `/analyze` flow.
