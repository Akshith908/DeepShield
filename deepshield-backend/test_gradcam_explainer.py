"""Tests for the local Grad-CAM explainer.

Three tiers are mixed here on purpose and labelled per test:

* unit tests use a tiny stub network, so they never need the 72.8 MB
  checkpoint and never claim anything about the real model's accuracy;
* contract/API tests live in ``test_explain_api.py``;
* the real-model test is skipped unless ``models/best_model.pt`` exists.

Nothing here mines the network: no provider calls, no weight downloads.
"""

import math

import pytest

torch = pytest.importorskip("torch")
np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from services import gradcam_explainer as gx  # noqa: E402


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


class StubDetector(torch.nn.Module):
    """Minimal CNN with the same ``features[-1]`` hook shape as the detector."""

    def __init__(self) -> None:
        super().__init__()

        self.features = torch.nn.Sequential(
            torch.nn.Conv2d(3, 8, 3, stride=4, padding=1),
            torch.nn.ReLU(),
            torch.nn.Conv2d(8, 16, 3, stride=4, padding=1),
            torch.nn.ReLU(),
        )
        self.classifier = torch.nn.Linear(16, 1)

    def forward(self, x):
        x = self.features(x)
        x = x.mean(dim=(2, 3))
        return self.classifier(x)


class ExplodingDetector(StubDetector):
    def forward(self, x):
        raise RuntimeError("simulated inference failure")


def _tensor(seed: int = 0):
    generator = torch.Generator().manual_seed(seed)

    return torch.randn(1, 3, gx.INPUT_SIZE, gx.INPUT_SIZE, generator=generator)


def _png_bytes(width: int = 256, height: int = 256, colour=(120, 130, 140)) -> bytes:
    buffer = __import__("io").BytesIO()
    Image.new("RGB", (width, height), colour).save(buffer, format="PNG")

    return buffer.getvalue()


# --------------------------------------------------------------------------
# Colormap
# --------------------------------------------------------------------------


def test_jet_colormap_endpoints_and_shape():
    heat = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)

    rgb = gx.jet_colormap(heat)

    assert rgb.shape == (1, 3, 3)
    assert rgb.dtype == np.uint8

    # JET runs dark blue -> green -> dark red.
    assert tuple(rgb[0, 0]) == (0, 0, 128)
    assert tuple(rgb[0, 2]) == (128, 0, 0)
    assert rgb[0, 1, 1] == 255


# --------------------------------------------------------------------------
# Grad-CAM mechanics (stub model)
# --------------------------------------------------------------------------


def test_gradcam_heatmap_shape_dtype_and_range():
    model = StubDetector().eval()

    heatmap, probability = gx.gradcam_heatmap(model, _tensor())

    assert heatmap.shape == (gx.INPUT_SIZE, gx.INPUT_SIZE)
    assert heatmap.dtype == np.float32
    assert np.all(np.isfinite(heatmap))
    assert heatmap.min() >= 0.0 and heatmap.max() <= 1.0
    assert 0.0 <= probability <= 1.0


def test_gradcam_uses_real_gradients_not_a_constant_fill():
    model = StubDetector().eval()

    first, _ = gx.gradcam_heatmap(model, _tensor(seed=1))
    second, _ = gx.gradcam_heatmap(model, _tensor(seed=2))

    # A real activation/gradient map varies spatially and depends on the input.
    assert first.max() > 0.0
    assert float(first.std()) > 0.0
    assert not np.allclose(first, second)


def test_gradcam_is_reproducible_for_the_same_input():
    model = StubDetector().eval()
    tensor = _tensor(seed=7)

    first, probability_first = gx.gradcam_heatmap(model, tensor.clone())
    second, probability_second = gx.gradcam_heatmap(model, tensor.clone())

    assert np.array_equal(first, second)
    assert probability_first == pytest.approx(probability_second)


def test_gradcam_returns_zeros_when_no_positive_attribution():
    """A constant map is returned as zeros — never as a fabricated pattern."""

    class NoGradientDetector(StubDetector):
        def forward(self, x):
            # Detached branch: activations still exist, but the logit carries no
            # gradient from the input, so every captured gradient is zero.
            features = self.features(x)
            pooled = features.mean(dim=(2, 3)).detach()

            return self.classifier(torch.zeros_like(pooled)) + 0.0 * features.sum()

    model = NoGradientDetector().eval()

    heatmap, _ = gx.gradcam_heatmap(model, _tensor(seed=3))

    assert np.array_equal(heatmap, np.zeros_like(heatmap))


def test_normalize_heatmap_sanitizes_non_finite_values():
    """NaN/inf never reach the response; they degrade to zero attribution."""

    raw = np.array(
        [[float("nan"), float("inf")], [float("-inf"), 0.0]],
        dtype=np.float32,
    )

    heatmap = gx.normalize_heatmap(raw)

    assert np.all(np.isfinite(heatmap))
    assert np.array_equal(heatmap, np.zeros_like(heatmap))


def test_normalize_heatmap_scales_to_unit_range():
    heatmap = gx.normalize_heatmap(np.array([[2.0, 4.0], [6.0, 8.0]], dtype=np.float32))

    assert heatmap.min() == pytest.approx(0.0)
    assert heatmap.max() == pytest.approx(1.0)
    assert heatmap[1, 1] == pytest.approx(1.0)


def test_gradcam_failure_raises_instead_of_returning_an_image():
    model = ExplodingDetector().eval()

    with pytest.raises(gx.ExplainError) as caught:
        gx.gradcam_heatmap(model, _tensor())

    assert caught.value.code == "inference_failed"
    assert caught.value.status_code == 500


# --------------------------------------------------------------------------
# Overlay alignment
# --------------------------------------------------------------------------


def test_build_visuals_keeps_frame_alignment():
    original = Image.new("RGB", (400, 300), (10, 20, 30))
    heatmap = np.full((gx.INPUT_SIZE, gx.INPUT_SIZE), 0.5, dtype=np.float32)
    crop = (100, 50, 120, 120)

    heat_image, overlay_image = gx.build_visuals(original, heatmap, crop)

    assert heat_image.size == (400, 300)
    assert overlay_image.size == (400, 300)

    heat_pixels = np.asarray(heat_image)
    overlay_pixels = np.asarray(overlay_image)

    # Outside the analysed crop: heatmap canvas is black, overlay is untouched.
    assert heat_pixels[0, 0].tolist() == [0, 0, 0]
    assert overlay_pixels[0, 0].tolist() == [10, 20, 30]
    assert overlay_pixels[299, 399].tolist() == [10, 20, 30]

    # Inside the crop: the overlay is a 50/50 blend, not a shifted copy.
    expected = (0.5 * np.array([10, 20, 30]) + 0.5 * gx.jet_colormap(np.array([[0.5]]))[0, 0]).astype(np.uint8)
    assert overlay_pixels[100, 150].tolist() == expected.tolist()


def test_build_visuals_downscales_large_outputs_but_keeps_aspect():
    original = Image.new("RGB", (2400, 1200), (0, 0, 0))
    heatmap = np.zeros((gx.INPUT_SIZE, gx.INPUT_SIZE), dtype=np.float32)

    heat_image, overlay_image = gx.build_visuals(original, heatmap, (0, 0, 2400, 1200))

    assert max(overlay_image.size) == gx.MAX_OUTPUT_SIDE
    assert overlay_image.size[0] / overlay_image.size[1] == pytest.approx(2.0, rel=1e-2)
    assert heat_image.size == overlay_image.size


def test_square_crop_stays_inside_the_image():
    box = (5, 5, 40, 40)

    crop = gx._square_crop(box, width=100, height=80)

    x, y, w, h = crop

    assert x >= 0 and y >= 0
    assert x + w <= 100
    assert y + h <= 80
    assert w == h or x + w == 100 or y + h == 80


# --------------------------------------------------------------------------
# Input validation and failure modes
# --------------------------------------------------------------------------


def _write(tmp_path, name, payload: bytes):
    path = tmp_path / name
    path.write_bytes(payload)

    return str(path)


def test_rejects_non_image_bytes(tmp_path):
    path = _write(tmp_path, "not-an-image.jpg", b"definitely not an image")

    with pytest.raises(gx.ExplainError) as caught:
        gx.explain_image_file(path)

    assert caught.value.code == "invalid_image"


def test_rejects_unsupported_format(tmp_path):
    buffer = __import__("io").BytesIO()
    Image.new("RGB", (128, 128), (1, 2, 3)).save(buffer, format="TIFF")
    path = _write(tmp_path, "scan.tiff", buffer.getvalue())

    with pytest.raises(gx.ExplainError) as caught:
        gx.explain_image_file(path)

    assert caught.value.code == "unsupported_format"


def test_rejects_tiny_images(tmp_path):
    path = _write(tmp_path, "tiny.png", _png_bytes(16, 16))

    with pytest.raises(gx.ExplainError) as caught:
        gx.explain_image_file(path)

    assert caught.value.code == "invalid_image"


def test_missing_checkpoint_is_reported_not_faked(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSHIELD_MODEL_PATH", str(tmp_path / "absent.pt"))
    gx.reset_model_cache()

    try:
        with pytest.raises(gx.ExplainError) as caught:
            gx.load_model()
    finally:
        gx.reset_model_cache()

    assert caught.value.code == "model_unavailable"
    assert caught.value.status_code == 503


def test_no_face_detected_is_a_structured_error(tmp_path, monkeypatch):
    monkeypatch.setattr(gx, "_detect_face", lambda image: (None, 0, "none"))

    path = _write(tmp_path, "landscape.png", _png_bytes(320, 240))

    with pytest.raises(gx.ExplainError) as caught:
        gx.explain_image_file(path)

    assert caught.value.code == "no_face_detected"
    assert caught.value.status_code == 422


def test_inference_failure_never_returns_a_heatmap(tmp_path, monkeypatch):
    monkeypatch.setattr(gx, "_detect_face", lambda image: ((40, 40, 100, 100), 1, "ok"))
    monkeypatch.setattr(gx, "load_model", lambda: ExplodingDetector().eval())

    path = _write(tmp_path, "person.png", _png_bytes(320, 240))

    with pytest.raises(gx.ExplainError) as caught:
        gx.explain_image_file(path)

    assert caught.value.code == "inference_failed"


def test_non_finite_model_output_fails_instead_of_reporting_a_verdict(
    tmp_path, monkeypatch
):
    class NaNLogitDetector(StubDetector):
        def forward(self, x):
            return torch.full((x.shape[0], 1), float("nan"))

    monkeypatch.setattr(gx, "_detect_face", lambda image: ((40, 40, 100, 100), 1, "ok"))
    monkeypatch.setattr(gx, "load_model", lambda: NaNLogitDetector().eval())

    path = _write(tmp_path, "person.png", _png_bytes(320, 240))

    with pytest.raises(gx.ExplainError) as caught:
        gx.explain_image_file(path)

    assert caught.value.code == "inference_failed"


# --------------------------------------------------------------------------
# Real-model integration test (skipped without the checkpoint)
# --------------------------------------------------------------------------


pytestmark_real = pytest.mark.skipif(
    not gx.model_path().is_file(),
    reason="real checkpoint not downloaded (run scripts/download_model.py)",
)


@pytestmark_real
def test_real_model_produces_a_valid_explanation():
    from pathlib import Path

    sample = Path(__file__).resolve().parent / "ai_image.png"

    if not sample.is_file():
        pytest.skip("sample face image missing")

    gx.reset_model_cache()

    result = gx.explain_image_file(str(sample))

    assert result["success"] is True
    assert result["model_id"] == gx.MODEL_ID
    assert result["local_prediction"] in {"FAKE", "REAL"}
    assert 50.0 <= result["local_confidence"] <= 100.0
    assert result["heatmap"].startswith("data:image/png;base64,")
    assert result["overlay"].startswith("data:image/png;base64,")
    assert result["overlay_width"] <= gx.MAX_OUTPUT_SIDE
    assert result["image_width"] == 1402 and result["image_height"] == 1122
    assert result["processing_time"] > 0
    assert math.isfinite(result["fake_probability"])
    assert result["limitations"]
