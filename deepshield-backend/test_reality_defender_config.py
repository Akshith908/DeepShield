import pytest
from unittest import mock

from services.reality_defender import load_polling_config


class TestPollingConfigDefaults:
    def test_defaults_use_1000ms_and_preserve_five_minute_window(self, monkeypatch):
        monkeypatch.delenv("RD_POLL_INTERVAL_MS", raising=False)
        monkeypatch.delenv("RD_POLL_MAX_ATTEMPTS", raising=False)

        config = load_polling_config()
        # Measured optimization: 1000ms interval (was 2000ms) cuts median
        # end-to-end audio latency while keeping the same deadline.
        assert config["polling_interval_ms"] == 1000
        assert config["max_attempts"] == 300

    def test_default_poll_window_is_at_least_five_minutes(self, monkeypatch):
        monkeypatch.delenv("RD_POLL_INTERVAL_MS", raising=False)
        monkeypatch.delenv("RD_POLL_MAX_ATTEMPTS", raising=False)

        config = load_polling_config()
        window_ms = config["polling_interval_ms"] * config["max_attempts"]
        # Must not shorten the provider deadline (prior window was 300s).
        assert window_ms >= 300_000


class TestPollingConfigValidOverrides:
    def test_explicit_valid_values(self, monkeypatch):
        monkeypatch.setenv("RD_POLL_INTERVAL_MS", "1000")
        monkeypatch.setenv("RD_POLL_MAX_ATTEMPTS", "45")

        config = load_polling_config()
        assert config["polling_interval_ms"] == 1000
        assert config["max_attempts"] == 45


class TestPollingConfigInvalidValues:
    def test_empty_string_is_invalid(self, monkeypatch):
        monkeypatch.setenv("RD_POLL_INTERVAL_MS", "")
        with pytest.raises(RuntimeError, match=r"Invalid RD_POLL_INTERVAL_MS"):
            load_polling_config()

    def test_non_numeric_is_invalid(self, monkeypatch):
        monkeypatch.setenv("RD_POLL_MAX_ATTEMPTS", "fast")
        with pytest.raises(RuntimeError, match=r"Invalid RD_POLL_MAX_ATTEMPTS"):
            load_polling_config()

    def test_zero_is_invalid(self, monkeypatch):
        monkeypatch.setenv("RD_POLL_MAX_ATTEMPTS", "0")
        with pytest.raises(RuntimeError, match=r"Invalid RD_POLL_MAX_ATTEMPTS"):
            load_polling_config()

    def test_negative_is_invalid(self, monkeypatch):
        monkeypatch.setenv("RD_POLL_INTERVAL_MS", "-500")
        with pytest.raises(RuntimeError, match=r"Invalid RD_POLL_INTERVAL_MS"):
            load_polling_config()


class TestPollingConfigSdkPassThrough:
    """Verify the configured values are actually forwarded to the SDK call."""

    def test_get_result_received_configured_arguments(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.setenv("RD_POLL_INTERVAL_MS", "1500")
        monkeypatch.setenv("RD_POLL_MAX_ATTEMPTS", "20")

        tmp_file = tmp_path / "probe.wav"
        tmp_file.write_bytes(b"\x00" * 100)

        rd = mock.MagicMock()
        rd.upload = mock.AsyncMock(
            return_value={"request_id": "r-123", "media_id": "m-456"}
        )
        rd.get_result = mock.AsyncMock(
            return_value={"status": "AUTHENTIC", "score": 0.9}
        )
        rd.cleanup = mock.AsyncMock()

        monkeypatch.setattr(
            "services.reality_defender.RealityDefender",
            lambda api_key: rd,
        )

        from services.reality_defender import analyze_audio
        import asyncio

        asyncio.run(analyze_audio(str(tmp_file)))

        rd.upload.assert_called_once_with(file_path=str(tmp_file))
        rd.get_result.assert_called_once_with(
            "r-123",
            max_attempts=20,
            polling_interval=1500,
        )
        rd.cleanup.assert_awaited_once()

    def test_get_result_uses_defaults_when_env_unset(
        self, monkeypatch, tmp_path,
    ):
        monkeypatch.delenv("RD_POLL_INTERVAL_MS", raising=False)
        monkeypatch.delenv("RD_POLL_MAX_ATTEMPTS", raising=False)

        tmp_file = tmp_path / "probe.wav"
        tmp_file.write_bytes(b"\x00" * 100)

        rd = mock.MagicMock()
        rd.upload = mock.AsyncMock(
            return_value={"request_id": "r-999", "media_id": "m-999"}
        )
        rd.get_result = mock.AsyncMock(
            return_value={"status": "AUTHENTIC", "score": 0.5}
        )
        rd.cleanup = mock.AsyncMock()

        monkeypatch.setattr(
            "services.reality_defender.RealityDefender",
            lambda api_key: rd,
        )

        from services.reality_defender import analyze_audio
        import asyncio

        asyncio.run(analyze_audio(str(tmp_file)))

        rd.get_result.assert_called_once_with(
            "r-999",
            max_attempts=300,
            polling_interval=1000,
        )


class TestEndpointPassThrough:
    """End-to-end: the real /analyze endpoint forwards configured values."""

    def test_analyze_endpoint_passes_config_to_sdk(self, monkeypatch):
        import io
        from fastapi.testclient import TestClient

        monkeypatch.setenv("RD_POLL_INTERVAL_MS", "1234")
        monkeypatch.setenv("RD_POLL_MAX_ATTEMPTS", "17")

        captured = {}

        rd = mock.MagicMock()

        async def fake_upload(*, file_path):
            return {"request_id": "req-abc", "media_id": "med-1"}

        async def fake_get_result(request_id, max_attempts, polling_interval):
            captured["request_id"] = request_id
            captured["max_attempts"] = max_attempts
            captured["polling_interval"] = polling_interval
            return {"status": "AUTHENTIC", "score": 0.9, "models": []}

        async def fake_cleanup():
            return None

        rd.upload = fake_upload
        rd.get_result = fake_get_result
        rd.cleanup = fake_cleanup

        monkeypatch.setattr(
            "services.reality_defender.RealityDefender",
            lambda api_key: rd,
        )

        from main import app

        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"file": ("clip.wav", io.BytesIO(b"\x00" * 100), "audio/wav")},
        )

        assert response.status_code == 200
        assert captured["max_attempts"] == 17
        assert captured["polling_interval"] == 1234

    def test_analyze_endpoint_rejects_invalid_config(self, monkeypatch):
        import io
        from fastapi.testclient import TestClient

        monkeypatch.setenv("RD_POLL_MAX_ATTEMPTS", "not-a-number")

        rd = mock.MagicMock()

        async def fake_upload(*, file_path):
            return {"request_id": "req-abc", "media_id": "med-1"}

        async def fake_cleanup():
            return None

        rd.upload = fake_upload
        rd.cleanup = fake_cleanup

        monkeypatch.setattr(
            "services.reality_defender.RealityDefender",
            lambda api_key: rd,
        )

        from main import app

        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={"file": ("clip.wav", io.BytesIO(b"\x00" * 100), "audio/wav")},
        )

        # Invalid config is rejected loudly, not silently clamped or faked.
        assert response.status_code == 500
        assert "not-a-number" not in str(response.json())
