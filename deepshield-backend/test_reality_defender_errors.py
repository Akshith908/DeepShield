import io

import pytest
from fastapi.testclient import TestClient
from realitydefender.errors import RealityDefenderError

from main import app
from services import analyzer


def _wav_bytes(size: int = 2000) -> bytes:
    # Not a valid audio file, but enough for the mocked SDK path.
    return b"\x00" * size


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def failing_reality_defender(monkeypatch):
    """Replace analyze_audio with an SDK 'unauthorized' failure."""

    async def _fail(file_path: str):
        raise RealityDefenderError("Invalid API key", "unauthorized")

    monkeypatch.setattr(analyzer, "analyze_audio", _fail)


def test_reality_defender_unauthorized_returns_sanitized_424(
    client, failing_reality_defender
):
    response = client.post(
        "/analyze",
        files={
            "file": (
                "voice_ai.wav",
                io.BytesIO(_wav_bytes()),
                "audio/wav",
            )
        },
    )

    # Provider auth failure must become a sanitized 424, not a 500.
    assert response.status_code == 424
    detail = response.json()["detail"]
    assert detail["provider"] == "Reality Defender"
    assert detail["file"] == "voice_ai.wav"
    assert detail["message"].startswith("The external analysis provider")

    # No credential or SDK error detail may leak into the response.
    detail_text = str(detail)
    assert "unauthorized" not in detail_text
    assert "Invalid API key" not in detail_text
    assert "Bearer" not in detail_text
    assert "ey" not in detail_text.split("voice_ai.wav")[0]


def test_reality_defender_failure_response_matches_bitmind_shape(
    client, failing_reality_defender
):
    response = client.post(
        "/analyze",
        files={
            "file": (
                "clip.wav",
                io.BytesIO(_wav_bytes()),
                "audio/wav",
            )
        },
    )

    detail = response.json()["detail"]
    assert set(detail.keys()) == {"provider", "file", "message"}


def test_reality_defender_non_sdk_error_is_not_swallowed_as_424(
    client, monkeypatch
):
    async def _fail_runtime(file_path: str):
        raise RuntimeError("REALITY_DEFENDER_API_KEY is not configured")

    monkeypatch.setattr(analyzer, "analyze_audio", _fail_runtime)

    response = client.post(
        "/analyze",
        files={
            "file": (
                "unconfigured.wav",
                io.BytesIO(_wav_bytes()),
                "audio/wav",
            )
        },
    )

    # A missing API key is a configuration problem, not a provider 4xx:
    # it must not pretend to be a provider rejection (stays a 5xx).
    assert response.status_code >= 500
