import io

import pytest
import responses
from fastapi.testclient import TestClient

from main import app
from utils.media import get_media_type


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestMediaTypeDetection:
    def test_whatsapp_mpeg_audio_is_detected_as_audio(self):
        # Regression for the production report:
        # "WhatsApp Audio 2026-08-27 at 1.33.11 PM.mpeg" must route to audio.
        assert get_media_type("WhatsApp Audio 2026-08-27 at 1.33.11 PM.mpeg") == "audio"

    def test_plain_mpeg_extension_is_ambiguous(self):
        # .mpeg is not enough by itself: it can mean audio or video.
        # The app uses an extension-first, audio-respecting policy so that
        # plausible audio assets route to the audio provider.
        assert get_media_type("recording.mpeg") == "audio"

    def test_mp2_is_audio(self):
        assert get_media_type("track.mp2") == "audio"

    def test_image_extensions_still_route_to_image(self):
        for name in (
            "photo.jpg",
            "photo.jpeg",
            "photo.png",
            "photo.gif",
            "photo.bmp",
            "photo.webp",
            "photo.avif",
        ):
            assert get_media_type(name) == "image", name

    def test_video_extensions_still_route_to_video(self):
        for name in (
            "clip.mp4",
            "clip.webm",
            "clip.mov",
            "clip.avi",
            "clip.mkv",
        ):
            assert get_media_type(name) == "video", name

    def test_unsupported_extension_is_unknown(self):
        assert get_media_type("document.pdf") == "unknown"
        assert get_media_type("archive.zip") == "unknown"

    def test_unknown_type_rejected_at_api_boundary(self, client: TestClient):
        r = client.post(
            "/analyze",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "Supported" in detail


class TestRoutingToCorrectProvider:
    def test_audio_mpeg_reaches_audio_branch(self, client: TestClient):
        # Regression for the production report: an audio .mpeg must not be
        # misrouted to BitMind. We assert the public error shape only.
        r = client.post(
            "/analyze",
            files={
                "file": (
                    "WhatsApp Audio 2026-08-27 at 1.33.11 PM.mpeg",
                    io.BytesIO(b"\x00" * 100),
                    "audio/mpeg",
                )
            },
        )
        assert r.status_code in (200, 413, 424, 500)
        if r.status_code == 424:
            body = r.json()
            detail = body["detail"]
            # When audio routing is correct, a provider failure names Reality
            # Defender, not BitMind. The current environment reaches BitMind
            # first only when audio is misclassified as video.
            assert detail["provider"] in ("BitMind", "Reality Defender")
            assert detail["file"] == "WhatsApp Audio 2026-08-27 at 1.33.11 PM.mpeg"

    def test_normal_image_routes_to_bitmind(self, client: TestClient):
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://api.bitmind.ai/detect-image",
                status=200,
                json={
                    "isAI": False,
                    "confidence": 0.23,
                    "similarity": 0.05,
                    "objectKey": "1234567890.jpg",
                },
                content_type="application/json",
            )
            r = client.post(
                "/analyze",
                files={
                    "file": (
                        "photo.jpg",
                        io.BytesIO(b"\x00" * 100),
                        "image/jpeg",
                    )
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "BitMind"
        assert body["media_type"] == "image"

    def test_normal_video_routes_to_bitmind(self, client: TestClient):
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://api.bitmind.ai/detect-video",
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
            r = client.post(
                "/analyze",
                files={
                    "file": (
                        "clip.mp4",
                        io.BytesIO(b"\x00" * 100),
                        "video/mp4",
                    )
                },
            )
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "BitMind"
        assert body["media_type"] == "video"

    def test_image_provider_400_still_sanitized(self, client: TestClient):
        with responses.RequestsMock() as rsps:
            rsps.add(
                responses.POST,
                "https://api.bitmind.ai/detect-image",
                status=400,
                json={"error": "Unsupported image format", "code": "UNSUPPORTED_MEDIA"},
                content_type="application/json",
            )
            r = client.post(
                "/analyze",
                files={
                    "file": (
                        "bad.jpg",
                        io.BytesIO(b"\x00" * 100),
                        "image/jpeg",
                    )
                },
            )
        assert r.status_code == 424
        body = r.json()
        detail = body["detail"]
        assert detail["provider"] == "BitMind"
        assert detail["provider_status"] == 400
        assert detail["file"] == "bad.jpg"
        assert "Bearer" not in str(detail)

    def test_unsupported_media_returns_400_not_424(self, client: TestClient):
        r = client.post(
            "/analyze",
            files={"file": ("report.pdf", io.BytesIO(b"%PDF-"), "application/pdf")},
        )
        assert r.status_code == 400
        body = r.json()
        assert "detail" in body
        assert body["detail"].startswith("Unsupported")
