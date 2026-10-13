import asyncio

from fastapi import HTTPException

from services.bitmind import (
    ProviderError,
    analyze_image,
    analyze_video,
)

from services.reality_defender import (
    analyze_audio,
)


def get_risk_level(score: float) -> str:
    if score < 30:
        return "LOW"

    if score < 70:
        return "MEDIUM"

    return "HIGH"


def safe_percent(value, default: float = 0.0) -> float:
    """Convert a provider score to a 0-100 float, tolerating None/garbage."""
    try:
        return max(0.0, min(100.0, float(value) * 100.0))
    except (TypeError, ValueError):
        return default


def normalize_bitmind(
    result: dict,
    media_type: str,
) -> dict:

    is_ai = bool(result.get("isAI", False))
    confidence = max(0.0, min(1.0, float(result.get("confidence", 0) or 0)))

    if is_ai:
        risk_score = confidence * 100
        prediction = "LIKELY_AI_GENERATED"
        detection_status = "AI-generated content detected"
    else:
        risk_score = (1 - confidence) * 100
        prediction = "LIKELY_AUTHENTIC"
        detection_status = "No strong AI-generation signal detected"

    return {
        "success": True,
        "media_type": media_type,
        "prediction": prediction,
        "risk_score": round(risk_score, 1),
        "risk_level": get_risk_level(risk_score),
        "confidence": round(confidence * 100, 1),
        "provider": "BitMind",

        "signals": [
            {
                "name": "AI Generation Detection",
                "value": detection_status,
                "score": round(confidence * 100, 1),
            }
        ],
    }


def normalize_reality_defender(result: dict) -> dict:

    status = result.get("status") or "UNKNOWN"

    # format_result can return score=None when no verdict was reached
    # (e.g. still analyzing, or models without a predictionNumber).
    raw_score = result.get("score")

    if raw_score is None:
        risk_score = 0.0
    else:
        risk_score = safe_percent(raw_score)

    if status == "MANIPULATED":
        prediction = "LIKELY_MANIPULATED"

    elif status == "AUTHENTIC":
        prediction = "LIKELY_AUTHENTIC"

    else:
        prediction = "INCONCLUSIVE"
        risk_score = 0.0

    signals = []

    for model in result.get("models", []):
        signals.append(
            {
                "name": model.get(
                    "name",
                    "Audio Detection Model",
                ),

                "value": model.get(
                    "status",
                    "UNKNOWN",
                ),

                "score": (
                    round(safe_percent(model.get("score")), 1)
                    if model.get("score") is not None
                    else None
                ),
            }
        )

    return {
        "success": True,
        "media_type": "audio",
        "prediction": prediction,
        "risk_score": round(risk_score, 1),
        "risk_level": get_risk_level(risk_score) if prediction != "INCONCLUSIVE" else "LOW",
        "confidence": round(risk_score, 1) if prediction != "INCONCLUSIVE" else 0.0,
        "provider": "Reality Defender",
        "signals": signals,
    }


def _provider_error_to_http(
    error: ProviderError,
) -> HTTPException:
    """Convert a sanitized BitMind provider error into a safe FastAPI response.

    Provider 4xx failures are surfaced to the frontend as HTTP 424
    (Failed Dependency), which is semantically appropriate for a dependent
    external service being unavailable or rejecting the request. The response
    body intentionally omits the API key, the uploaded media bytes, and any
    raw traceback.
    """
    return HTTPException(
        status_code=424,
        detail={
            "provider": "BitMind",
            "provider_status": error.status_code,
            "file": error.file,
            "message": "The external analysis provider rejected or failed the request. "
            "The request is safe to retry. If the problem persists, verify the "
            "uploaded file meets the provider's limits.",
        },
    )


async def analyze_file(
    file_path: str,
    filename: str,
    media_type: str,
) -> dict:

    if media_type == "image":

        try:
            result = await asyncio.to_thread(
                analyze_image,
                file_path,
                filename,
            )
        except ProviderError as error:
            raise _provider_error_to_http(error) from error

        return normalize_bitmind(
            result,
            "image",
        )

    if media_type == "video":

        try:
            result = await asyncio.to_thread(
                analyze_video,
                file_path,
                filename,
            )
        except ProviderError as error:
            raise _provider_error_to_http(error) from error

        return normalize_bitmind(
            result,
            "video",
        )

    if media_type == "audio":

        result = await analyze_audio(
            file_path
        )

        return normalize_reality_defender(
            result
        )

    raise ValueError(
        "Unsupported media type"
    )
