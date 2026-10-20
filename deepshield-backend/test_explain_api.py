"""Contract tests for ``POST /explain`` and its isolation from ``/analyze``.

These use a patched ``main.explain_image_file`` plus mocked BitMind responses:
no PyTorch, no checkpoint and no network are required, and none of this proves
anything about real-model accuracy (see test_gradcam_explainer.py for the
real-model test).
"""

import io
import subprocess
import sys
from pathlib import Path

import pytest
import responses
from fastapi.testclient import TestClient

import main
from services import gradcam_explainer
from services.gradcam_explainer import ExplainError

BACKEND_DIR = Path(__file__).resolve().parent

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)

FAKE_RESULT = {
    "success": True,
    "model_id": "honi05/deepfake-detection:efficientnet-b4-celebdf",
    "model_source": "https://huggingface.co/honi05/deepfake-detection",
    "model_license": "MIT",
    "gradcam_layer": "features[-1]",
    "local_prediction": "FAKE",
    "local_confidence": 87.4,
    "fake_probability": 87.4,
    "heatmap": "data:image/png;base64,AAAA",
    "overlay": "data:image/png;base64,BBBB",
    "image_width": 800,
    "image_height": 600,
    "overlay_width": 800,
    "overlay_height": 600,
    "analysed_crop": {"x": 10, "y": 10, "width": 200, "height": 200},
    "faces_detected": 1,
    "processing_time": 0.42,
    "limitations": ["coarse localisation map"],
}


@pytest.fixture
def client():
    return TestClient(main.app)


def _post_file(client, name="face.png", payload=PNG_BYTES, content_type="image/png"):
    return client.post(
        "/explain",
        files={"file": (name, io.BytesIO(payload), content_type)},
    )


def test_explain_returns_documented_fields(client, monkeypatch):
    monkeypatch.setattr(main, "explain_image_file", lambda path: dict(FAKE_RESULT))

    response = _post_file(client)

    assert response.status_code == 200

    body = response.json()

    for field in (
        "success",
        "model_id",
        "local_prediction",
        "local_confidence",
        "heatmap",
        "overlay",
        "image_width",
        "image_height",
        "processing_time",
        "limitations",
    ):
        assert field in body, field

    assert body["success"] is True
    assert body["heatmap"].startswith("data:image/png;base64,")
    assert body["request_id"]


def test_explain_rejects_non_image_uploads(client):
    response = _post_file(client, name="clip.mp4", content_type="video/mp4")

    assert response.status_code == 400
    assert "images only" in response.json()["detail"]


def test_explain_requires_a_file_field(client):
    # No `file` part at all: rejected by request validation before inference.
    assert client.post("/explain").status_code == 422


def test_no_face_maps_to_422_with_machine_readable_code(client, monkeypatch):
    def raiser(path):
        raise ExplainError(
            "no_face_detected",
            "No face was detected in this image.",
            422,
        )

    monkeypatch.setattr(main, "explain_image_file", raiser)

    response = _post_file(client)

    assert response.status_code == 422

    detail = response.json()["detail"]

    assert detail["code"] == "no_face_detected"
    assert "no face" in detail["message"].lower()


def test_missing_model_maps_to_sanitized_503(client, monkeypatch):
    def raiser(path):
        raise ExplainError("model_unavailable", "Model weights are not available.", 503)

    monkeypatch.setattr(main, "explain_image_file", raiser)

    response = _post_file(client)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "model_unavailable"


def test_unexpected_explainer_crash_is_sanitized(client, monkeypatch):
    def raiser(path):
        raise RuntimeError("CUDA out of memory at /home/dataset/faces")

    monkeypatch.setattr(main, "explain_image_file", raiser)

    response = _post_file(client)

    assert response.status_code == 500

    body = response.text

    assert "RuntimeError" not in body
    assert "faces" not in body


def test_explain_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(main, "explain_image_file", lambda path: dict(FAKE_RESULT))
    monkeypatch.setattr(main.explanation_limiter, "check", lambda key: 30.0)

    response = _post_file(client)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "31"


def test_app_boots_without_the_ml_extras_installed():
    """Deployments that skip requirements-gradcam.txt must still start up."""

    code = (
        "import sys\n"
        "for name in ('torch', 'torchvision', 'numpy', 'PIL', 'cv2'):\n"
        "    sys.modules[name] = None\n"
        "import main\n"
        "print('ok')\n"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_DIR),
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


@pytest.mark.skipif(
    not gradcam_explainer.model_path().is_file(),
    reason="real checkpoint not downloaded (run scripts/download_model.py)",
)
def test_explain_endpoint_end_to_end_with_real_model(client):
    """Real-model HTTP test: JSON-serialisable response with real PNG data URIs."""

    sample = BACKEND_DIR / "ai_image.png"

    if not sample.is_file():
        pytest.skip("sample face image missing")

    response = _post_file(client, name="portrait.png", payload=sample.read_bytes())

    assert response.status_code == 200

    body = response.json()

    assert body["success"] is True
    assert body["local_prediction"] in {"FAKE", "REAL"}
    assert body["heatmap"].startswith("data:image/png;base64,")
    assert body["overlay"].startswith("data:image/png;base64,")
    assert body["image_width"] == 1402
    assert body["processing_time"] > 0
    assert body["request_id"]
    assert 0 <= body["fake_probability"] <= 100


def test_analyze_still_works_when_the_explainer_is_broken(client, monkeypatch):
    """A Grad-CAM failure must never touch the provider-backed analysis path."""

    def raiser(path):
        raise ExplainError("model_unavailable", "Model weights are not available.", 503)

    monkeypatch.setattr(main, "explain_image_file", raiser)

    with responses.RequestsMock() as rsps:
        rsps.add(
            method=responses.POST,
            url="https://api.bitmind.ai/detect-image",
            json={
                "isAI": True,
                "confidence": 0.91,
            },
            status=200,
            content_type="application/json",
        )

        analyze = client.post(
            "/analyze",
            files={"file": ("photo.jpg", io.BytesIO(b"\xff\xd8\xff" + b"0" * 400), "image/jpeg")},
        )

    explain = _post_file(client)

    assert explain.status_code == 503
    assert analyze.status_code == 200
    assert analyze.json()["success"] is True
    assert analyze.json()["provider"] == "BitMind"
    assert analyze.json()["prediction"] == "LIKELY_AI_GENERATED"
