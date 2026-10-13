import json
import logging
import os
import re
import mimetypes
import requests

logger = logging.getLogger(__name__)


BITMIND_IMAGE_URL = "https://api.bitmind.ai/detect-image"
BITMIND_VIDEO_URL = "https://api.bitmind.ai/detect-video"

_MAX_PROVIDER_BODY_LOG = 1024

_MASK_RE = re.compile(
    r"(?i)authorization\s*[:=]\s*bearer\s+[^\s,;\r\n]+",
)


def _log_provider_error(method: str, url: str, status_code: int, body: str) -> None:
    """Log provider HTTP errors without leaking credentials or media bytes.

    The raw response body may contain provider error details that are useful
    for debugging a 400/401/422, but it may also be very large or contain
    unexpected content. We cap the logged size and never log the provider
    Authorization header value or the uploaded media bytes themselves.
    """
    truncated = body
    if len(truncated) > _MAX_PROVIDER_BODY_LOG:
        truncated = truncated[:_MAX_PROVIDER_BODY_LOG] + "…[truncated]"

    # Replace any embedded Authorization bearer tokens before logging.
    sanitized = _MASK_RE.sub(
        "Authorization: [REDACTED]",
        truncated,
        count=1,
    )

    logger.warning(
        "provider %s %s returned %s: %s",
        method,
        url,
        status_code,
        sanitized,
    )


def get_headers():
    api_key = os.getenv("BITMIND_API_KEY")

    if not api_key:
        raise RuntimeError("BITMIND_API_KEY is not configured")

    return {
        "Authorization": f"Bearer {api_key}"
    }


def analyze_image(file_path: str, filename: str) -> dict:
    with open(file_path, "rb") as file:
        files = {
            "image": (
                filename,
                file,
            )
        }

        response = requests.post(
            BITMIND_IMAGE_URL,
            headers=get_headers(),
            files=files,
            timeout=120,
        )

    return _handle_response(
        response,
        "POST",
        BITMIND_IMAGE_URL,
        filename,
    )


def analyze_video(file_path: str, filename: str) -> dict:
    with open(file_path, "rb") as file:
        files = {
            "video": (
                filename,
                file,
            )
        }

        response = requests.post(
            BITMIND_VIDEO_URL,
            headers=get_headers(),
            files=files,
            timeout=300,
        )

    return _handle_response(
        response,
        "POST",
        BITMIND_VIDEO_URL,
        filename,
    )


def _handle_response(
    response: requests.Response,
    method: str,
    url: str,
    filename: str,
) -> dict:
    """Normalize provider responses and convert provider failures into Python
    exceptions with sanitized context.

    We intentionally do not log or forward the uploaded media contents. The
    `filename` argument is the original uploaded filename from the HTTP
    request, used only to make error messages readable for operators and the
    frontend. We never re-read or re-emit the uploaded media bytes.
    """
    try:
        data = response.json()
    except ValueError:
        # Provider returned non-JSON (rare but possible on 4xx/5xx).
        body_text = response.text
        _log_provider_error(
            method,
            url,
            response.status_code,
            body_text,
        )
        if not response.ok:
            raise ProviderError(
                method=method,
                url=url,
                status_code=response.status_code,
                body=body_text,
                file=filename,
            ) from None
        return data if isinstance(data, dict) else {}

    if response.ok:
        return data

    # Log first so the operator has provider-provided context.
    _log_provider_error(
        method,
        url,
        response.status_code,
        response.text,
    )

    raise ProviderError(
        method=method,
        url=url,
        status_code=response.status_code,
        body=response.text,
        file=filename,
    )


class ProviderError(Exception):
    """A BitMind provider request failed with a non-2xx response.

    This is a sanitized, operator-friendly wrapper. It deliberately does not
    include the API key, the uploaded media bytes, or a raw traceback.
    """

    def __init__(
        self,
        *,
        method: str,
        url: str,
        status_code: int,
        body: str,
        file: str,
    ) -> None:
        super().__init__(
            f"{method} {url} returned {status_code} for {file}. "
            f"Provider said: {body}"
        )
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        self.file = file
