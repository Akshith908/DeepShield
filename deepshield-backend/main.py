import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the backend dir, then the repo root as fallback, so the
# app works whether keys live next to main.py or in the workspace root
# (e.g. the Freebuff workspace .env). Already-set vars are not overridden.
_BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(_BACKEND_DIR / ".env")
load_dotenv(_BACKEND_DIR.parent / ".env")

from fastapi import (
    FastAPI,
    UploadFile,
    File,
    HTTPException,
    Request,
)

from fastapi.middleware.cors import CORSMiddleware

from utils.media import get_media_type
from utils.ratelimit import (
    client_identity,
    request_limiter,
    analysis_slots,
    SlidingWindowLimiter,
)
from services.analyzer import analyze_file

# Local Grad-CAM explanations are CPU-bound rather than billable, but still
# expensive, so they get their own budget: an explanation request can never
# consume the paid /analyze allowance, and vice versa. The module is imported
# eagerly but loads no weights (and imports no PyTorch) until /explain is hit.
from services.gradcam_explainer import (
    ExplainError,
    explain_image_file,
)


logger = logging.getLogger(__name__)


app = FastAPI(
    title="DeepShield API",
    version="1.0.1",
)


# CORS: configurable via CORS_ORIGINS (comma-separated). Falls back to
# sensible local-development defaults when unset.
_cors_origins = os.getenv("CORS_ORIGINS", "")

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in _cors_origins.split(",")
    if origin.strip()
] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,

    allow_origins=ALLOWED_ORIGINS,

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"],
)


# Upload size cap (bytes). Prevents huge payloads from eating memory and
# provider bandwidth before any analysis starts.
MAX_UPLOAD_MB = float(os.getenv("MAX_UPLOAD_MB", "100"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_MB * 1024 * 1024)


explanation_limiter = SlidingWindowLimiter(
    max(1, int(os.getenv("EXPLAIN_RATE_LIMIT_MAX_REQUESTS", "20"))),
    max(1.0, float(os.getenv("EXPLAIN_RATE_LIMIT_WINDOW_SECONDS", "600"))),
)


@app.get("/")
def root():
    return {
        "service": "DeepShield API",
        "status": "online",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
    }


@app.post("/explain")
async def explain(
    request: Request,
    file: UploadFile = File(...)
):
    """Grad-CAM explanation from the local EfficientNet-B4 detector.

    Deliberately separate from /analyze: the local model has its own cost,
    latency and failure modes, and a missing checkpoint or a failed inference
    must never affect the provider-backed analysis response.
    """

    retry_after = explanation_limiter.check(
        client_identity(request)
    )

    if retry_after > 0:

        wait = int(retry_after) + 1

        raise HTTPException(
            status_code=429,
            detail=(
                "Visual-explanation rate limit reached. "
                f"Try again in about {wait} seconds."
            ),
            headers={"Retry-After": str(wait)},
        )

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file provided",
        )

    if get_media_type(file.filename) != "image":
        raise HTTPException(
            status_code=400,
            detail=(
                "Visual explanations are available for images only. "
                "Videos and audio are analysed without a heatmap."
            ),
        )

    raw_suffix = os.path.splitext(file.filename)[1]
    suffix = raw_suffix if 0 < len(raw_suffix) <= 10 else ".bin"

    temp_path = None
    request_id = uuid.uuid4().hex[:12]

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            temp_path = temp_file.name

            bytes_written = 0

            while True:

                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                bytes_written += len(chunk)

                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File too large. Maximum is "
                            f"{MAX_UPLOAD_MB:g} MB."
                        ),
                    )

                temp_file.write(chunk)

        # CPU-bound inference must not block the event loop.
        result = await asyncio.to_thread(
            explain_image_file,
            temp_path,
        )

        result["request_id"] = request_id

        logger.info(
            "explain request=%s bytes=%d time=%.2fs model=%s",
            request_id,
            bytes_written,
            result.get("processing_time", 0.0),
            result.get("model_id", "unknown"),
        )

        return result

    except ExplainError as error:

        # Structured, sanitized detail: the frontend shows `message` and uses
        # `code` to distinguish "no face" from "model unavailable".
        logger.info(
            "explain request=%s failed code=%s",
            request_id,
            error.code,
        )

        raise HTTPException(
            status_code=error.status_code,
            detail={
                "code": error.code,
                "message": error.message,
            },
        ) from error

    except HTTPException:

        raise

    except Exception as error:

        logger.exception(
            "explain request=%s failed",
            request_id,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "The visual explanation could not be generated. "
                "The provider analysis above is unaffected."
            ),
        ) from error

    finally:

        if (
            temp_path
            and os.path.exists(temp_path)
        ):
            os.remove(temp_path)


@app.post("/analyze")
async def analyze(
    request: Request,
    file: UploadFile = File(...)
):

    # Each analysis spends real money at a third-party detector, so throttle
    # per client before doing any other work.
    retry_after = request_limiter.check(
        client_identity(request)
    )

    if retry_after > 0:
        wait = int(retry_after) + 1

        raise HTTPException(
            status_code=429,
            detail=(
                "Rate limit reached. DeepShield analysis uses "
                "paid detection providers, so uploads are "
                f"throttled. Try again in about {wait} seconds."
            ),
            headers={"Retry-After": str(wait)},
        )

    if not file.filename:
        raise HTTPException(
            status_code=400,
            detail="No file provided",
        )

    media_type = get_media_type(
        file.filename
    )

    if media_type == "unknown":
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported file type. "
                "Supported: image, video, audio."
            ),
        )

    # Bound how many expensive provider calls run at once, so a burst of
    # uploads cannot exhaust memory or provider concurrency limits.
    if not analysis_slots.acquire():

        raise HTTPException(
            status_code=429,
            detail=(
                "DeepShield is already analyzing the maximum "
                "number of files at once. Please retry in a moment."
            ),
            headers={"Retry-After": "5"},
        )

    start_time = time.perf_counter()

    # Keep only a short, safe extension for the temp file so odd or
    # malicious filenames can never escape the temp directory.
    raw_suffix = os.path.splitext(file.filename)[1]
    suffix = raw_suffix if 0 < len(raw_suffix) <= 10 else ".bin"

    temp_path = None
    request_id = uuid.uuid4().hex[:12]

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
        ) as temp_file:

            temp_path = temp_file.name

            bytes_written = 0

            while True:
                chunk = await file.read(1024 * 1024)

                if not chunk:
                    break

                bytes_written += len(chunk)

                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File too large. Maximum is "
                            f"{MAX_UPLOAD_MB:g} MB."
                        ),
                    )

                temp_file.write(chunk)

        spool_done = time.perf_counter()

        result = await analyze_file(
            file_path=temp_path,
            filename=file.filename,
            media_type=media_type,
        )

        analyze_done = time.perf_counter()

        analysis_time = (
            analyze_done - start_time
        )

        logger.info(
            "request=%s media_type=%s bytes=%d spool=%.3fs analyze=%.3fs server_total=%.3fs",
            request_id,
            media_type,
            bytes_written,
            spool_done - start_time,
            analysis_time,
            analysis_time,
        )

        result["filename"] = file.filename

        result["analysis_time"] = round(
            analysis_time,
            2,
        )

        # Correlation id so a browser-side console timing can be matched
        # with its server-side entry in the logs.
        result["request_id"] = request_id

        return result

    except HTTPException:

        # Client errors (4xx) must reach the browser as-is, not be
        # repackaged as a generic 500.
        raise

    except Exception as error:

        # The most likely visible failure right now is a BitMind provider 400,
        # which we convert to a sanitized HTTP 424 in services.analyzer.
        # Catch-all here is for anything else (runtime, IO, etc.).

        import logging as _logging

        _logging.getLogger(__name__).exception(
            "analysis request failed for %s",
            getattr(file, "filename", "unknown"),
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Analysis failed. Please try again later."
            ),
        ) from error

    finally:

        analysis_slots.release()

        if (
            temp_path
            and os.path.exists(temp_path)
        ):
            os.remove(temp_path)
