import io

import responses
from fastapi.testclient import TestClient

from main import app


def _video_bytes(size: int = 500) -> bytes:
    return b"\x00" * size


def test_video_provider_422_returns_sanitized_error():
    client = TestClient(app)

    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-video",
            status=422,
            json={
                "error": "Validation failed",
                "code": "VALIDATION_ERROR",
                "details": ["file too large for direct upload"],
            },
            content_type="application/json",
        )

        response = client.post(
            "/analyze",
            files={
                "file": (
                    "large.mp4",
                    io.BytesIO(_video_bytes()),
                    "video/mp4",
                )
            },
        )

    # A 422 from the provider must still become a sanitized 424, not a 500.
    assert response.status_code == 424
    detail = response.json()["detail"]
    assert detail["provider"] == "BitMind"
    assert detail["provider_status"] == 422
    assert detail["file"] == "large.mp4"
    assert "Bearer" not in str(detail)


def test_video_provider_non_json_error_is_still_sanitized():
    client = TestClient(app)

    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-video",
            status=500,
            # A provider sometimes returns HTML error pages on 5xx.
            body="<html><body>500 Internal Server Error</body></html>",
            content_type="text/html",
        )

        response = client.post(
            "/analyze",
            files={
                "file": (
                    "server_error.mp4",
                    io.BytesIO(_video_bytes()),
                    "video/mp4",
                )
            },
        )

    assert response.status_code == 424
    detail = response.json()["detail"]
    assert detail["provider"] == "BitMind"
    assert detail["provider_status"] == 500
    assert detail["file"] == "server_error.mp4"
    assert "Bearer" not in str(detail)


def test_video_provider_400_body_truncation_does_not_leak_media_bytes():
    """
    Sanity check that the backend's provider-error logging path does not
    forward uploaded media bytes into the HTTP response.

    The logged `file` field is the original uploaded filename, never the
    contents of the file.
    """
    client = TestClient(app)

    large_video = _video_bytes(size=10_000)

    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-video",
            status=400,
            json={
                "error": "Unsupported file format",
                "code": "UNSUPPORTED_MEDIA",
            },
            content_type="application/json",
        )

        response = client.post(
            "/analyze",
            files={
                "file": (
                    "big.mp4",
                    io.BytesIO(large_video),
                    "video/mp4",
                )
            },
        )

    assert response.status_code == 424
    body = response.json()

    detail = body["detail"]
    assert detail["file"] == "big.mp4"

    # The response must not contain any of the uploaded blob.
    detail_text = str(detail)
    for chunk in (large_video[:64], large_video[-64:]):
        assert chunk.decode("ascii", errors="ignore") not in detail_text

    # No credential leakage.
    for secret in ("BITMIND_API_KEY", "Bearer", "sk-", "eyJ"):
        assert secret not in detail_text
