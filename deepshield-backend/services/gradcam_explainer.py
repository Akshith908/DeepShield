"""Local Grad-CAM visual explanations for images.

Model provenance
----------------
* Weights: ``best_model.pt`` from https://huggingface.co/honi05/deepfake-detection
  (72.8 MB, MIT licence, not committed to this repository).
* Training / demo source: https://github.com/Honi05/DeepFakeDetector (MIT).
  The architecture below mirrors ``src/model.py`` and the preprocessing
  mirrors ``src/dataset.py`` (``VAL_TRANSFORMS``) so the published
  ``state_dict`` loads unchanged.
* Training data reported by the model card: Celeb-DF v2 face crops, so the
  detector is a real-vs-fake *face* classifier — not a general image
  authenticity model.

Why this module is standalone
-----------------------------
Nothing here is imported by ``services/analyzer.py`` or by the BitMind /
Reality Defender clients. A failure in this file can only fail ``POST
/explain``; ``POST /analyze`` keeps its existing behaviour. Heavy imports
(``torch``, ``numpy``, ``PIL``, ``cv2``) are optional at import time so the
API still boots on a host where the ML extras are not installed — the
endpoint then reports ``model_unavailable`` instead of crashing the app.

Grad-CAM
--------
Activations and gradients are captured from ``model.features[-1]`` (the last
EfficientNet block, stride 32 -> 7x7 spatial grid at 224px) for the model's
own FAKE logit. They are weighted by spatially averaged gradients, ReLU'd and
normalised, exactly as described in Selvaraju et al. (2016) and as the source
repository's ``src/gradcam.py`` does. No heatmap is ever derived from a
provider risk score, from pixel statistics, or from random data: if inference
cannot run, this module raises and the API returns an error with no image.
"""

from __future__ import annotations

import base64
import io
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

try:  # Optional at import time: see module docstring.
    import numpy as np
except Exception:  # pragma: no cover - exercised only on ML-less hosts
    np = None  # type: ignore[assignment]

try:
    from PIL import Image, UnidentifiedImageError
except Exception:  # pragma: no cover - exercised only on ML-less hosts
    Image = None  # type: ignore[assignment]

    class UnidentifiedImageError(Exception):  # type: ignore[no-redef]
        """Placeholder so ``except`` clauses stay importable without Pillow."""


# --------------------------------------------------------------------------
# Model / preprocessing constants (mirror github.com/Honi05/DeepFakeDetector)
# --------------------------------------------------------------------------

logger = logging.getLogger(__name__)

MODEL_ID = "honi05/deepfake-detection:efficientnet-b4-celebdf"
MODEL_SOURCE = "https://huggingface.co/honi05/deepfake-detection"
MODEL_LICENSE = "MIT"
GRADCAM_LAYER = "features[-1]"

INPUT_SIZE = 224

# torchvision ImageNet statistics, used by the checkpoint's VAL_TRANSFORMS.
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

# The checkpoint's classifier head: Dropout -> 1792 -> 256 -> ReLU -> 1 logit.
FEATURE_DIM = 1792
HIDDEN_DIM = 256
DROPOUT = 0.4

ACCEPTED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "GIF"}

# Guardrails: refuse absurd decodes instead of allocating unbounded arrays.
MAX_PIXELS = int(os.getenv("DEEPSHIELD_MAX_PIXELS", str(40_000_000)))  # 40 MP
MAX_INPUT_SIDE = int(os.getenv("DEEPSHIELD_MAX_IMAGE_SIDE", "12000"))

# Overlay/heatmap payload cap. PNGs are returned inline as data URIs, so a
# 12000px original would otherwise mean a multi-megabyte response.
MAX_OUTPUT_SIDE = int(os.getenv("DEEPSHIELD_EXPLANATION_MAX_SIDE", "1024"))

# Face gating: Haar cascade on a downscaled copy keeps detection cheap.
_FACE_DETECT_MAX_SIDE = 640
_FACE_MIN_SIZE = 48
_CROP_MARGIN = 0.2

# Inference is serialised: the shared model instance holds hook state while a
# Grad-CAM pass runs, so concurrent passes would corrupt each other's maps.
_INFERENCE_LOCK = threading.Lock()
_INFERENCE_WAIT_SECONDS = float(
    os.getenv("DEEPSHIELD_GRADCAM_LOCK_TIMEOUT", "20")
)

_MODEL_LOCK = threading.Lock()
_model: Optional[Any] = None
_model_meta: Dict[str, Any] = {}

_cascade_lock = threading.Lock()
_cascade: Optional[Any] = None
_cascade_import_failed = False

_torch_bundle: Optional[Dict[str, Any]] = None
_torch_import_error: Optional[str] = None


# --------------------------------------------------------------------------
# Errors -> mapped to HTTP statuses by main.py
# --------------------------------------------------------------------------


class ExplainError(Exception):
    """A visual explanation could not be produced.

    ``code`` is a stable machine-readable identifier for the frontend;
    ``message`` is safe to show to a user and never contains image bytes.
    """

    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# --------------------------------------------------------------------------
# Lazy heavy imports
# --------------------------------------------------------------------------


def _torch():
    """Import torch/torchvision once, or raise ``model_unavailable``."""

    global _torch_bundle, _torch_import_error

    if _torch_bundle is not None:
        return _torch_bundle

    if _torch_import_error is not None:
        raise ExplainError(
            "model_unavailable",
            "The local visual-explanation model is not installed on this "
            "server (PyTorch is missing).",
            503,
        )

    try:
        import torch  # noqa: PLC0415 - deliberate lazy import
        import torch.nn as nn  # noqa: PLC0415
        from torchvision.models import efficientnet_b4  # noqa: PLC0415

        _torch_bundle = {
            "torch": torch,
            "nn": nn,
            "efficientnet_b4": efficientnet_b4,
        }

        # One analysis at a time on a small instance; extra threads just fight
        # for the same cores.
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))

        return _torch_bundle

    except Exception as error:  # pragma: no cover - depends on host packages
        _torch_import_error = f"{type(error).__name__}"
        raise ExplainError(
            "model_unavailable",
            "The local visual-explanation model is not installed on this "
            "server (PyTorch is missing).",
            503,
        ) from error


def _require_numpy():
    if np is None:  # pragma: no cover - depends on host packages
        raise ExplainError(
            "model_unavailable",
            "The local visual-explanation model is not installed on this "
            "server (NumPy/Pillow are missing).",
            503,
        )

    return np


def model_path() -> Path:
    """Checkpoint location: ``DEEPSHIELD_MODEL_PATH`` or ``models/best_model.pt``."""

    configured = os.getenv("DEEPSHIELD_MODEL_PATH")

    if configured:
        return Path(configured).expanduser()

    return Path(__file__).resolve().parent.parent / "models" / "best_model.pt"


# --------------------------------------------------------------------------
# Model loading (once per process, never per request)
# --------------------------------------------------------------------------


def _build_classifier(bundle: Dict[str, Any]):
    """torchvision EfficientNet-B4 trunk + the checkpoint's 1-logit head."""

    nn = bundle["nn"]
    efficientnet_b4 = bundle["efficientnet_b4"]

    class DeepfakeClassifier(nn.Module):
        """Mirror of ``DeepfakeClassifier`` in the model repository."""

        def __init__(self) -> None:
            super().__init__()

            # weights=None: the checkpoint supplies every parameter. Passing
            # DEFAULT here would download ImageNet weights on every cold start.
            base = efficientnet_b4(weights=None)

            self.features = base.features
            self.avgpool = base.avgpool

            self.classifier = nn.Sequential(
                nn.Dropout(p=DROPOUT),
                nn.Linear(FEATURE_DIM, HIDDEN_DIM),
                nn.ReLU(),
                nn.Dropout(p=0.2),
                nn.Linear(HIDDEN_DIM, 1),
            )

        def forward(self, x):
            x = self.features(x)
            x = self.avgpool(x)
            x = x.flatten(1)
            return self.classifier(x)  # raw logit; sigmoid gives P(FAKE)

    return DeepfakeClassifier()


def load_model():
    """Load and cache the detector. Raises ``model_unavailable`` if absent."""

    global _model, _model_meta

    if _model is not None:
        return _model

    bundle = _torch()

    with _MODEL_LOCK:
        if _model is not None:
            return _model

        path = model_path()

        if not path.is_file():
            raise ExplainError(
                "model_unavailable",
                "The local visual-explanation model weights are not "
                "available on this server.",
                503,
            )

        started = time.perf_counter()

        try:
            model = _build_classifier(bundle)
            state = bundle["torch"].load(
                str(path),
                map_location="cpu",
                weights_only=True,
            )
            model.load_state_dict(state, strict=True)
            model.eval()

            # Parameters stay frozen: inference is read-only and we never step
            # an optimizer. Grad-CAM still gets a gradient graph because the
            # input tensor requires grad (see gradcam_heatmap).

        except ExplainError:
            raise

        except Exception as error:
            # Never log weights or tensors; the exception type is enough to
            # distinguish a corrupt checkpoint from a library mismatch.
            raise ExplainError(
                "model_unavailable",
                "The local visual-explanation model could not be loaded.",
                503,
            ) from error

        _model_meta = {
            "model_id": MODEL_ID,
            "checkpoint": path.name,
            "checkpoint_bytes": path.stat().st_size,
            "load_seconds": round(time.perf_counter() - started, 3),
        }

        _model = model

        return _model


def model_metadata() -> Dict[str, Any]:
    """Cached metadata about the loaded checkpoint (no weights, no paths)."""

    return dict(_model_meta)


def reset_model_cache() -> None:
    """Drop the cached model. Used by tests; never called by request handling."""

    global _model, _model_meta

    with _MODEL_LOCK:
        _model = None
        _model_meta = {}


# --------------------------------------------------------------------------
# Image validation and preprocessing
# --------------------------------------------------------------------------


def _load_image(data: bytes):
    """Decode bytes into an RGB PIL image or raise ``invalid_image``."""

    if Image is None:  # pragma: no cover - depends on host packages
        raise ExplainError(
            "model_unavailable",
            "Image support (Pillow) is not installed on this server.",
            503,
        )

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as error:
        raise ExplainError(
            "invalid_image",
            "The uploaded file is not a readable image.",
            400,
        ) from error
    except Exception as error:
        raise ExplainError(
            "invalid_image",
            "The uploaded image could not be decoded.",
            400,
        ) from error

    if image.format not in ACCEPTED_FORMATS:
        raise ExplainError(
            "unsupported_format",
            "Unsupported image format for visual explanation. "
            "Use JPEG, PNG, WEBP, BMP or GIF.",
            400,
        )

    width, height = image.size

    if width < 32 or height < 32:
        raise ExplainError(
            "invalid_image",
            "The image is too small for a visual explanation (minimum 32x32).",
            400,
        )

    if width > MAX_INPUT_SIDE or height > MAX_INPUT_SIDE or width * height > MAX_PIXELS:
        raise ExplainError(
            "image_too_large",
            "The image dimensions are too large for visual explanation.",
            413,
        )

    return image.convert("RGB")


def _detect_face(image):
    """Return ``(box, face_count, status)`` for the largest detected face.

    ``box`` is ``(x, y, w, h)`` in original-image coordinates or ``None``.
    ``status`` is ``"ok"``, ``"none"`` or ``"unavailable"`` when OpenCV (and
    therefore its bundled Haar cascade) is not installed.
    """

    global _cascade, _cascade_import_failed

    try:
        import cv2  # noqa: PLC0415 - optional dependency
    except Exception:  # pragma: no cover - depends on host packages
        _cascade_import_failed = True
        return None, 0, "unavailable"

    with _cascade_lock:
        if _cascade is None:
            cascade_path = os.path.join(
                cv2.data.haarcascades,
                "haarcascade_frontalface_default.xml",
            )
            cascade = cv2.CascadeClassifier(cascade_path)

            if cascade.empty():  # pragma: no cover - broken OpenCV install
                _cascade_import_failed = True
                return None, 0, "unavailable"

            _cascade = cascade

    array = _require_numpy().asarray(image.convert("L"))

    # Detecting on a downscaled copy keeps latency flat for large uploads.
    longest = max(array.shape[0], array.shape[1])
    scale = min(1.0, _FACE_DETECT_MAX_SIDE / float(longest))

    detect_input = array

    if scale < 1.0:
        resized = image.convert("L").resize(
            (max(1, int(array.shape[1] * scale)), max(1, int(array.shape[0] * scale)))
        )
        detect_input = _require_numpy().asarray(resized)

    faces = _cascade.detectMultiScale(
        detect_input,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(_FACE_MIN_SIZE, _FACE_MIN_SIZE),
    )

    if faces is None or len(faces) == 0:
        return None, 0, "none"

    inverse = 1.0 / scale if scale > 0 else 1.0

    boxes = [
        (
            int(round(x * inverse)),
            int(round(y * inverse)),
            int(round(w * inverse)),
            int(round(h * inverse)),
        )
        for (x, y, w, h) in faces
    ]

    boxes.sort(key=lambda box: box[2] * box[3], reverse=True)

    return boxes[0], len(boxes), "ok"


def _square_crop(box: Tuple[int, int, int, int], width: int, height: int):
    """Expand a face box by a margin and square it, clipped to the image."""

    x, y, w, h = box
    side = int(max(w, h) * (1 + _CROP_MARGIN * 2))

    centre_x = x + w / 2.0
    centre_y = y + h / 2.0

    left = int(round(centre_x - side / 2.0))
    top = int(round(centre_y - side / 2.0))

    left = max(0, min(left, max(0, width - 1)))
    top = max(0, min(top, max(0, height - 1)))
    right = min(width, left + side)
    bottom = min(height, top + side)

    if right - left < 16 or bottom - top < 16:
        return (0, 0, width, height)

    return (left, top, right - left, bottom - top)


def _preprocess(image, crop):
    """Resize -> ToTensor -> ImageNet Normalize, as in ``VAL_TRANSFORMS``."""

    bundle = _torch()
    torch = bundle["torch"]
    numpy = _require_numpy()

    region = image.crop((crop[0], crop[1], crop[0] + crop[2], crop[1] + crop[3]))
    region = region.resize((INPUT_SIZE, INPUT_SIZE), Image.BICUBIC)

    array = numpy.asarray(region, dtype=numpy.float32) / 255.0
    array = (array - numpy.array(IMAGENET_MEAN, dtype=numpy.float32)) / numpy.array(
        IMAGENET_STD, dtype=numpy.float32
    )

    tensor = torch.from_numpy(array.transpose(2, 0, 1)).float().unsqueeze(0)

    return tensor


# --------------------------------------------------------------------------
# Grad-CAM
# --------------------------------------------------------------------------


def normalize_heatmap(raw):
    """Sanitize and min-max normalise a raw CAM array into ``[0, 1]``.

    Non-finite values become zero, and a constant map becomes an all-zero map.
    Both are reported as "no positive attribution" rather than replaced with a
    synthetic pattern.
    """

    numpy = _require_numpy()

    heatmap = numpy.asarray(raw, dtype=numpy.float32)
    heatmap = numpy.nan_to_num(heatmap, nan=0.0, posinf=0.0, neginf=0.0)

    floor = float(heatmap.min()) if heatmap.size else 0.0
    ceiling = float(heatmap.max()) if heatmap.size else 0.0

    if ceiling > floor:
        heatmap = (heatmap - floor) / (ceiling - floor)
    else:
        heatmap = numpy.zeros_like(heatmap)

    return numpy.clip(heatmap, 0.0, 1.0).astype(numpy.float32)


def gradcam_heatmap(model, tensor, torch_module=None):
    """Return ``(heatmap, probability_fake)`` for one preprocessed image.

    ``heatmap`` is a float32 array in ``[0, 1]`` sized ``INPUT_SIZE`` square,
    computed from real activations/gradients at ``model.features[-1]`` for the
    model's own logit. Callers must hold the inference lock.
    """

    numpy = _require_numpy()

    if torch_module is None:
        torch_module = _torch()["torch"]

    target = model.features[-1]

    captured: Dict[str, Any] = {}

    def forward_hook(_module, _inputs, output):
        captured["activations"] = output

    def backward_hook(_module, _grad_input, grad_output):
        captured["gradients"] = grad_output[0]

    forward_handle = target.register_forward_hook(forward_hook)
    backward_handle = target.register_full_backward_hook(backward_hook)

    try:
        model.zero_grad(set_to_none=True)

        # The graph is built from the input side: parameters are frozen, so the
        # input must require grad for activations to carry gradients.
        if not tensor.requires_grad:
            tensor.requires_grad_(True)

        with torch_module.enable_grad():
            logits = model(tensor)
            logit = logits.reshape(-1)[0]
            logit.backward()

        activations = captured.get("activations")
        gradients = captured.get("gradients")

        if activations is None or gradients is None:
            raise ExplainError(
                "inference_failed",
                "The local model did not expose activations for this image.",
                500,
            )

        # Channel weights = spatially averaged gradients (Grad-CAM eq. 1-2).
        weights = gradients.detach().mean(dim=(2, 3), keepdim=True)
        cam = (weights * activations.detach()).sum(dim=1).squeeze(0)
        cam = torch_module.relu(cam)

        heatmap = cam.detach().cpu().numpy().astype(numpy.float32)

        probability = float(torch_module.sigmoid(logit.detach()).item())

    except ExplainError:
        raise

    except Exception as error:
        # Exception type only: never log tensors, activations or image data.
        logger.warning("gradcam inference failed: %s", type(error).__name__)

        raise ExplainError(
            "inference_failed",
            "The local model could not complete inference for this image.",
            500,
        ) from error

    finally:
        forward_handle.remove()
        backward_handle.remove()
        model.zero_grad(set_to_none=True)

    heatmap = normalize_heatmap(heatmap)

    # 7x7 -> 224x224 with bilinear interpolation (same as the source repo).
    upscaled = Image.fromarray(heatmap, mode="F").resize(
        (INPUT_SIZE, INPUT_SIZE), Image.BILINEAR
    )

    return numpy.asarray(upscaled, dtype=numpy.float32), probability


def jet_colormap(heatmap):
    """OpenCV-compatible JET mapping without an OpenCV dependency."""

    numpy = _require_numpy()

    values = numpy.clip(heatmap.astype(numpy.float32), 0.0, 1.0)

    red = numpy.clip(1.5 - numpy.abs(4.0 * values - 3.0), 0.0, 1.0)
    green = numpy.clip(1.5 - numpy.abs(4.0 * values - 2.0), 0.0, 1.0)
    blue = numpy.clip(1.5 - numpy.abs(4.0 * values - 1.0), 0.0, 1.0)

    rgb = numpy.stack([red, green, blue], axis=-1)

    return (rgb * 255.0).round().astype(numpy.uint8)


def build_visuals(image, heatmap, crop):
    """Composite the heatmap over the original image, aligned to ``crop``.

    Returns ``(heatmap_image, overlay_image)`` at the original resolution
    (downscaled to ``MAX_OUTPUT_SIDE`` for transport). The heatmap is placed
    exactly over the analysed crop, so the two images share a frame and the
    overlay never shifts or distorts the original.
    """

    numpy = _require_numpy()

    width, height = image.size

    base = numpy.asarray(image.convert("RGB"), dtype=numpy.uint8)

    heat_rgb = jet_colormap(heatmap)

    # Resize the 224x224 map to the analysed crop's size on the original image.
    crop_heat = numpy.asarray(
        Image.fromarray(heat_rgb).resize((crop[2], crop[3]), Image.BILINEAR),
        dtype=numpy.uint8,
    )

    heat_canvas = numpy.zeros_like(base)

    left, top, crop_w, crop_h = crop

    heat_canvas[top : top + crop_h, left : left + crop_w] = crop_heat

    overlay = base.copy()
    region = overlay[top : top + crop_h, left : left + crop_w].astype(numpy.float32)
    overlay[top : top + crop_h, left : left + crop_w] = (
        0.5 * region + 0.5 * crop_heat.astype(numpy.float32)
    ).clip(0, 255).astype(numpy.uint8)

    heat_image = Image.fromarray(heat_canvas)
    overlay_image = Image.fromarray(overlay)

    longest = max(width, height)

    if longest > MAX_OUTPUT_SIDE:
        target = (
            max(1, int(round(width * MAX_OUTPUT_SIDE / longest))),
            max(1, int(round(height * MAX_OUTPUT_SIDE / longest))),
        )
        heat_image = heat_image.resize(target, Image.LANCZOS)
        overlay_image = overlay_image.resize(target, Image.LANCZOS)

    return heat_image, overlay_image


def _png_data_uri(image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)

    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    return f"data:image/png;base64,{encoded}"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------


def explain_image_file(path: str) -> Dict[str, Any]:
    """Generate a Grad-CAM explanation for the image at ``path``.

    Raises ``ExplainError`` on every failure. Returns a JSON-serialisable dict
    following the project's snake_case response conventions.
    """

    started = time.perf_counter()

    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as error:
        raise ExplainError(
            "invalid_image",
            "The uploaded image could not be read.",
            400,
        ) from error

    image = _load_image(data)

    width, height = image.size

    limitations = [
        "The local model was trained on Celeb-DF v2 face crops, so it is a "
        "face-level real/fake classifier, not a general image-authenticity "
        "model.",
        "Grad-CAM is a coarse localisation map: it shows where the network's "
        "gradients were strongest, not proof that those regions were "
        "manipulated.",
        "The local model's verdict is independent of the BitMind result and "
        "may disagree with it.",
    ]

    box, face_count, face_status = _detect_face(image)

    if face_status == "unavailable":
        limitations.append(
            "Face detection is unavailable on this server, so the whole "
            "image was analysed instead of a face crop."
        )
        crop = (0, 0, width, height)
    elif face_status == "none":
        raise ExplainError(
            "no_face_detected",
            "No face was detected in this image. The local model is trained "
            "on face crops, so no visual explanation was generated.",
            422,
        )
    else:
        crop = _square_crop(box, width, height)

        if face_count > 1:
            limitations.append(
                f"{face_count} faces were detected; the explanation covers "
                "the largest one."
            )

    if not _INFERENCE_LOCK.acquire(timeout=_INFERENCE_WAIT_SECONDS):
        raise ExplainError(
            "busy",
            "The visual-explanation model is busy. Please retry in a moment.",
            429,
        )

    try:
        model = load_model()
        tensor = _preprocess(image, crop)
        heatmap, probability = gradcam_heatmap(model, tensor)
        heat_image, overlay_image = build_visuals(image, heatmap, crop)
    finally:
        _INFERENCE_LOCK.release()

    if not math.isfinite(probability):
        # A non-finite logit/sigmoid means the pass produced no usable verdict;
        # report the failure instead of inventing a prediction.
        raise ExplainError(
            "inference_failed",
            "The local model produced an unusable output for this image.",
            500,
        )

    fake_probability = max(0.0, min(1.0, probability))
    prediction = "FAKE" if fake_probability >= 0.5 else "REAL"
    confidence = max(fake_probability, 1.0 - fake_probability) * 100.0

    if float(heatmap.max()) <= 0.0:
        limitations.append(
            "No positive attribution was found at the target layer; the "
            "heatmap is uniform rather than fabricated."
        )

    return {
        "success": True,
        "model_id": MODEL_ID,
        "model_source": MODEL_SOURCE,
        "model_license": MODEL_LICENSE,
        "gradcam_layer": GRADCAM_LAYER,
        "local_prediction": prediction,
        # Probability of the predicted class from the model's own sigmoid.
        # Uncalibrated: it is a raw sigmoid, not a validated posterior.
        "local_confidence": round(confidence, 1),
        "fake_probability": round(fake_probability * 100.0, 1),
        "heatmap": _png_data_uri(heat_image),
        "overlay": _png_data_uri(overlay_image),
        "image_width": width,
        "image_height": height,
        "overlay_width": overlay_image.size[0],
        "overlay_height": overlay_image.size[1],
        "analysed_crop": {
            "x": crop[0],
            "y": crop[1],
            "width": crop[2],
            "height": crop[3],
        },
        "faces_detected": face_count,
        "processing_time": round(time.perf_counter() - started, 2),
        "limitations": limitations,
    }
