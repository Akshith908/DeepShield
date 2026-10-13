import io
from unittest import mock

import pytest
import responses
from fastapi.testclient import TestClient

from main import app


def _video_bytes(size: int = 500) -> bytes:
    # Deterministic "video" payload so the test is repeatable and does not
    # consume any real API credits. Content is irrelevant to the mocked path.
    return b"\x00" * size


def _image_bytes(size: int = 500) -> bytes:
    return b"\x00" * size


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _bitmind_body_for_status(status: int) -> dict:
    if status == 200:
        return {
            "isAI": True,
            "confidence": 0.87,
            "similarity": 0.0,
            "objectKey": "1234567890.mp4",
            "thumbnailObjectKey": "thumbnails/1234567890/main.jpg",
        }
    return {
        "error": "Unsupported file format",
        "code": "UNSUPPORTED_MEDIA",
    }


def _mock_video_post(status: int, body: dict | None = None) -> None:
    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-video",
            status=status,
            json=_bitmind_body_for_status(status)
            if body is None
            else body,
            content_type="application/json",
        )
        yield rsps


def _mock_image_post(status: int, body: dict | None = None) -> None:
    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-image",
            status=status,
            json=_bitmind_body_for_status(status)
            if body is None
            else body,
            content_type="application/json",
        )
        yield rsps


class TestBitMindVideoSuccess:
    def test_video_analysis_returns_normalized_result(self, client: TestClient):
        video = _video_bytes()
        with responses.RequestsMock() as rsps:
            rsps.add(
                method=responses.POST,
                url="https://api.bitmind.ai/detect-video",
                status=200,
                json={
                    "isAI": True,
                    "confidence": 0.87,
                    "similarity": 0.0,
                    "objectKey": "1234567890.mp4",
                    "thumbnailObjectKey": "thumbnails/1234567890/main.jpg",
                },
                content_type="application/json",
            )

            response = client.post(
                "/analyze",
                files={
                    "file": (
                        "test.mp4",
                        io.BytesIO(video),
                        "video/mp4",
                    )
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["media_type"] == "video"
        assert body["provider"] == "BitMind"
        assert body["prediction"] == "LIKELY_AI_GENERATED"
        # confidence 0.87 -> risk_score ~87
        assert body["risk_score"] == 87.0
        assert body["risk_level"] == "HIGH"
        assert body["confidence"] == 87.0
        assert len(body["signals"]) == 1
        assert body["signals"][0]["name"] == "AI Generation Detection"

    def test_video_file_extension_drives_media_type(self, client: TestClient):
        with responses.RequestsMock() as rsps:
            rsps.add(
                method=responses.POST,
                url="https://api.bitmind.ai/detect-video",
                status=200,
                json={
                    "isAI": False,
                    "confidence": 0.12,
                    "similarity": 0.0,
                    "objectKey": "1234567890.webm",
                    "thumbnailObjectKey": "thumbnails/1234567890/main.jpg",
                },
                content_type="application/json",
            )

            response = client.post(
                "/analyze",
                files={
                    "file": (
                        "recording.webm",
                        io.BytesIO(_video_bytes()),
                        "video/webm",
                    )
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["media_type"] == "video"
        assert body["provider"] == "BitMind"
        assert body["prediction"] == "LIKELY_AUTHENTIC"


class TestBitMindImageSuccess:
    def test_image_analysis_returns_normalized_result(self, client: TestClient):
        with responses.RequestsMock() as rsps:
            rsps.add(
                method=responses.POST,
                url="https://api.bitmind.ai/detect-image",
                status=200,
                json={
                    "isAI": False,
                    "confidence": 0.23,
                    "similarity": 0.05,
                    "objectKey": "1234567890.jpg",
                },
                content_type="application/json",
            )

            response = client.post(
                "/analyze",
                files={
                    "file": (
                        "photo.jpg",
                        io.BytesIO(_image_bytes()),
                        "image/jpeg",
                    )
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["media_type"] == "image"
        assert body["provider"] == "BitMind"
        assert body["prediction"] == "LIKELY_AUTHENTIC"
        assert body["risk_score"] == 77.0
        # 77 falls in the HIGH band under the current get_risk_level() rules.
        assert body["risk_level"] == "HIGH"


class TestBitMindProviderHttp400:
    def test_video_provider_400_returns_sanitized_error(self, client: TestClient):
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
                        "bad_video.mp4",
                        io.BytesIO(_video_bytes()),
                        "video/mp4",
                    )
                },
            )

        # Provider 400 must NOT surface as a generic 500.
        assert response.status_code == 424
        body = response.json()
        detail = body["detail"]
        assert detail["provider"] == "BitMind"
        assert detail["provider_status"] == 400
        assert detail["file"] == "bad_video.mp4"

        # No credentials, no raw request body, no stack trace in the response.
        detail_text = str(detail)
        assert "Bearer" not in detail_text
        assert "BITMIND_API_KEY" not in detail_text
        assert "sk-" not in detail_text
        assert "Traceback" not in detail_text

    def test_image_provider_400_returns_sanitized_error(self, client: TestClient):
        with responses.RequestsMock() as rsps:
            rsps.add(
                method=responses.POST,
                url="https://api.bitmind.ai/detect-image",
                status=400,
                json={
                    "error": "Unsupported image format",
                    "code": "UNSUPPORTED_MEDIA",
                },
                content_type="application/json",
            )

            response = client.post(
                "/analyze",
                files={
                    "file": (
                        "bad_photo.png",
                        io.BytesIO(_image_bytes()),
                        "image/png",
                    )
                },
            )

        assert response.status_code == 424
        body = response.json()
        detail = body["detail"]
        assert detail["provider"] == "BitMind"
        assert detail["provider_status"] == 400
        assert detail["file"] == "bad_photo.png"

    def test_video_provider_401_returns_sanitized_error(self, client: TestClient):
        # A provider 401 must not leak the configured API key to the frontend.
        # We patch the backend's get_headers so the configured key is not present
        # in os.environ for this test, then verify the sanitized response still
        # never contains a Bearer value.
        with mock.patch(
            "services.bitmind.get_headers",
            return_value={"Authorization": "Bearer SANITY_CHECK_KEY"},
        ), responses.RequestsMock() as rsps:
            rsps.add(
                method=responses.POST,
                url="https://api.bitmind.ai/detect-video",
                status=401,
                json={
                    "error": "Invalid API key",
                    "code": "UNAUTHORIZED",
                },
                content_type="application/json",
            )

            response = client.post(
                "/analyze",
                files={
                    "file": (
                        "auth_fail.mp4",
                        io.BytesIO(_video_bytes()),
                        "video/mp4",
                    )
                },
            )

        assert response.status_code == 424
        detail = response.json()["detail"]
        assert detail["provider_status"] == 401
        assert "Bearer" not in str(detail)
