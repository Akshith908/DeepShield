"""Tests for the request-lifecycle timing instrumentation in main.py.

Simulated-provider tests: the BitMind call is mocked with `responses`.
These verify response metadata and do not measure or assert real latency.
"""

import io
import re

import responses
from fastapi.testclient import TestClient

from main import app


def _image_bytes(size: int = 200) -> bytes:
    return b"\x00" * size


def _post_analyze(render_once=True):
    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-image",
            status=200,
            json={"isAI": True, "confidence": 0.9},
            content_type="application/json",
        )

        client = TestClient(app)
        response = client.post(
            "/analyze",
            files={
                "file": (
                    "timing_probe.png",
                    io.BytesIO(_image_bytes()),
                    "image/png",
                )
            },
        )

    return response


class TestRequestTimingMetadata:
    def test_response_includes_request_id(self):
        response = _post_analyze()

        assert response.status_code == 200
        body = response.json()
        assert re.fullmatch(r"[0-9a-f]{12}", body["request_id"])

    def test_request_id_is_unique_per_request(self):
        first = _post_analyze().json()["request_id"]
        second = _post_analyze().json()["request_id"]

        assert first != second

    def test_analysis_time_is_reported_and_finite(self):
        body = _post_analyze().json()

        assert isinstance(body["analysis_time"], (int, float))
        assert body["analysis_time"] >= 0

    def test_timing_metadata_contains_no_credentials(self):
        body = str(_post_analyze().json())

        for secret in ("Bearer", "BITMIND_API_KEY", "sk-", "eyJ"):
            assert secret not in body
