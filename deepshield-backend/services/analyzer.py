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


def build_explanation(payload: dict) -> dict:
    """Explainability layer: derive per-signal contributions and plain-language
    reasons from the already-normalized analysis payload.

    Deterministic and derived only from provider data we already have (no new
    external calls). Contributions split the 0-100 risk score across detector
    signals proportional to each signal's own evidence score, so the stated
    points always sum to risk_score (within rounding). Reasons describe how the
    score was computed and why the verdict follows.
    """
    prediction = payload.get("prediction") or "INCONCLUSIVE"
    risk_score = float(payload.get("risk_score") or 0.0)
    confidence = float(payload.get("confidence") or 0.0)
    provider = payload.get("provider") or "provider"
    media_type = payload.get("media_type") or "media"
    signals = payload.get("signals") or []

    scored = [
        signal
        for signal in signals
        if isinstance(signal.get("score"), (int, float))
    ]
    total_evidence = sum(float(s["score"]) for s in scored)

    contributions = []
    for signal in scored:
        score = float(signal["score"])
        share = (score / total_evidence) if total_evidence > 0 else 0.0
        contributions.append({
            "name": signal.get("name") or "Detection signal",
            "value": str(signal.get("value") or ""),
            "score": round(score, 1),
            "points": round(share * risk_score, 1),
        })

    if prediction == "LIKELY_AI_GENERATED":
        summary = (
            f"The {provider} detector flagged this {media_type} as AI-generated "
            f"with {risk_score:.1f}% risk, above the 30% low-risk threshold."
        )
    elif prediction == "LIKELY_MANIPULATED":
        summary = (
            f"The {provider} detectors measured {risk_score:.1f}% manipulation "
            f"risk for this {media_type}, above the 30% low-risk threshold."
        )
    elif prediction == "LIKELY_AUTHENTIC":
        summary = (
            f"No strong AI-generation signal was found; the {risk_score:.1f}% "
            f"residual risk keeps this {media_type} below the 70% high-risk threshold."
        )
    else:
        summary = (
            f"The {provider} analysis did not reach a verdict, so no risk score "
            f"was attributed. Treat this {media_type} as unverified."
        )

    reasons = []

    if prediction == "INCONCLUSIVE":
        reasons.append(
            "Provider returned no final status (e.g. analysis still running or "
            "models without a prediction), so the score is reported as 0."
        )
    elif provider == "BitMind":
        if prediction == "LIKELY_AI_GENERATED":
            reasons.append(
                f"BitMind classified the file as AI-generated at {confidence:.1f}% "
                f"confidence; risk score equals that confidence (90%+ means a "
                f"forgery finding, 30-70% warrants verification)."
            )
        else:
            reasons.append(
                f"BitMind found no AI-generation signal; risk score is the "
                f"remaining uncertainty (100% - {confidence:.1f}% confidence)."
            )
    else:
        reasons.append(
            f"{provider} returned an aggregate {risk_score:.1f}% score for this "
            f"{media_type} file; each detection model's own score is listed below."
        )

    if contributions:
        top = max(contributions, key=lambda c: c["points"])
        reasons.append(
            f"Largest contributor: {top['name']} ({top['value']}, "
            f"{top['score']:.1f}%) accounted for +{top['points']:.1f} of the risk score."
        )

    if risk_score >= 70:
        band = "strong"
    elif risk_score >= 30:
        band = "moderate"
    else:
        band = "low"
    reasons.append(
        f"{confidence:.1f}% model confidence and the {risk_score:.1f}% score "
        f"translate to {risk_score:.1f}/100 risk ({band} evidence)."
    )

    caveat = None
    if len(scored) <= 1:
        caveat = (
            "This verdict rests on a single detector's output, so there is no "
            "cross-model agreement check. Scores near the 30-70% band should be "
            "treated as inconclusive rather than proof."
        )
    elif 30 <= risk_score < 70:
        caveat = (
            "Score is in the 30-70% medium band: detectors disagree or evidence "
            "is split, so independent verification is recommended."
        )

    return {
        "summary": summary,
        "reasons": reasons,
        "contributions": contributions,
        "caveat": caveat,
    }


def with_explanation(payload: dict) -> dict:
    """Attach the explainability payload to a normalized analysis result."""
    payload["explanation"] = build_explanation(payload)
    return payload


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

    return with_explanation({
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
    })


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

    return with_explanation({
        "success": True,
        "media_type": "audio",
        "prediction": prediction,
        "risk_score": round(risk_score, 1),
        "risk_level": get_risk_level(risk_score) if prediction != "INCONCLUSIVE" else "LOW",
        "confidence": round(risk_score, 1) if prediction != "INCONCLUSIVE" else 0.0,
        "provider": "Reality Defender",
        "signals": signals,
    })


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
