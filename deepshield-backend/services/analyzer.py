import asyncio
import logging

from fastapi import HTTPException
from realitydefender.errors import RealityDefenderError

from services.bitmind import (
    ProviderError,
    analyze_image,
    analyze_video,
)

from services.reality_defender import (
    analyze_audio,
)


logger = logging.getLogger(__name__)


def get_risk_level(score: float) -> str:
    if score < 30:
        return "LOW"

    if score < 70:
        return "MEDIUM"

    return "HIGH"


def combine_provider_payloads(
    primary: dict | None,
    secondary: dict | None = None,
    secondary_error: dict | None = None,
) -> dict:
    """Cross-provider reliability layer (multi-provider extension point).

    Today each media type routes to exactly one provider, so this function is
    not yet on the live request path; it defines the tested semantics that a
    future dual-provider flow must follow when running BitMind and Reality
    Defender over the same media.

    Semantics (all derivable from the inputs, never invented):
    - Each provider outcome is reported individually as status OK / FAILED /
      UNAVAILABLE, with its own prediction and score when available.
    - Agreement: when both providers place the media in the same verdict
      category, that verdict is reported. The combined risk score is the
      higher of the two provider scores, reported as an explicit conservative
      upper bound (never averaged, because provider scales are incompatible).
    - Disagreement: the combined verdict becomes INCONCLUSIVE with the higher
      provider score as the conservative upper bound; the explanation states
      the conflict rather than presenting consensus or proof.
    - One provider inconclusive: the other's verdict stands, with an added
      reason noting the missing vote.
    - Partial failure: the valid result is preserved verbatim and the failed
      provider is reported as unavailable; no score is fabricated for it.
    - A missing single-provider score is never converted into evidence of
      authenticity (see INCONCLUSIVE handling in the normalizers).
    """
    if primary is None and secondary is None:
        raise ValueError(
            "combine_provider_payloads requires at least one provider result"
        )

    providers: list[dict] = []

    def _entry(payload: dict) -> dict:
        return {
            "provider": payload.get("provider") or "provider",
            "status": "OK",
            "prediction": payload.get("prediction") or "INCONCLUSIVE",
            "risk_score": payload.get("risk_score"),
        }

    if primary is not None:
        providers.append(_entry(primary))
    if secondary is not None:
        providers.append(_entry(secondary))

    if secondary_error:
        providers.append({
            "provider": secondary_error.get("provider") or "provider",
            "status": (
                "UNAVAILABLE"
                if secondary_error.get("kind") == "unavailable"
                else "FAILED"
            ),
            "message": (
                secondary_error.get("message")
                or "The provider did not return a usable result."
            ),
        })

    concern = {"LIKELY_AI_GENERATED", "LIKELY_MANIPULATED"}

    if primary is not None and secondary is not None:
        p_pred = primary.get("prediction") or "INCONCLUSIVE"
        s_pred = secondary.get("prediction") or "INCONCLUSIVE"
        p_risk = float(primary.get("risk_score") or 0.0)
        s_risk = float(secondary.get("risk_score") or 0.0)
        upper = round(max(p_risk, s_risk), 1)

        def _category(prediction: str) -> str | None:
            if prediction in concern:
                return "concern"
            if prediction == "LIKELY_AUTHENTIC":
                return "authentic"
            return None

        p_cat = _category(p_pred)
        s_cat = _category(s_pred)

        if p_cat is not None and p_cat == s_cat:
            combined_prediction = p_pred
        elif p_cat is not None and s_cat is None:
            # One provider returned no verdict: the available verdict stands,
            # with the uncertainty called out in the explanation.
            combined_prediction = p_pred
        elif s_cat is not None and p_cat is None:
            combined_prediction = s_pred
        else:
            # Both inconclusive or outright disagreement.
            combined_prediction = "INCONCLUSIVE"

        combined_signals = []
        for payload in (primary, secondary):
            for signal in payload.get("signals") or []:
                if isinstance(signal.get("score"), (int, float)):
                    combined_signals.append({
                        "name": (
                            f"{payload.get('provider')} — "
                            f"{signal.get('name') or 'Detection signal'}"
                        ),
                        "value": signal.get("value") or "",
                        "score": float(signal["score"]),
                    })

        combined = {
            "success": primary.get("success", True),
            "media_type": primary.get("media_type") or "media",
            "provider": "Multiple providers",
            "prediction": combined_prediction,
            "risk_score": upper,
            "risk_level": get_risk_level(upper),
            "confidence": min(
                float(primary.get("confidence") or 0.0),
                float(secondary.get("confidence") or 0.0),
            ),
            "providers": providers,
            "signals": combined_signals,
        }

        explanation = build_explanation(dict(
            combined,
            signals=combined_signals,
        ))

        if p_cat is not None and p_cat == s_cat:
            explanation["reasons"].insert(
                0,
                f"{primary.get('provider')} and {secondary.get('provider')} agree "
                f"on the '{p_pred}' verdict category; both provider scores are "
                f"shown below under the combined score. Agreement is not proof "
                f"of correctness.",
            )
        elif p_pred != "INCONCLUSIVE" and s_pred != "INCONCLUSIVE":
            explanation["reasons"].insert(
                0,
                f"{primary.get('provider')} ({p_pred}) and {secondary.get('provider')} "
                f"({s_pred}) disagree, so no single verdict is attributed. The "
                f"combined score is the higher provider score as a conservative "
                f"upper bound, not an average.",
            )
            explanation["caveat"] = (
                "The providers returned conflicting verdicts, so the overall "
                "interpretation is uncertain. Verify the media through an "
                "independent source before relying on either individual score."
            )
        else:
            if p_pred == "INCONCLUSIVE" and s_pred == "INCONCLUSIVE":
                explanation["reasons"].insert(
                    0,
                    "Neither provider produced a final verdict, so the combined "
                    "interpretation is uncertain.",
                )
            else:
                missing = (
                    primary.get("provider")
                    if p_pred == "INCONCLUSIVE"
                    else secondary.get("provider")
                )
                explanation["reasons"].insert(
                    0,
                    f"{missing} returned no final verdict, so the combined "
                    f"interpretation is uncertain.",
                )

        combined["explanation"] = explanation

        return combined

    # Single-provider outcome (or partial failure): preserve the valid result
    # verbatim, extend it with the provider ledger, and add honest reasons
    # about the provider that could not contribute.
    base = primary if primary is not None else secondary
    combined = dict(base or {})
    combined["providers"] = providers

    explanation = combined.get("explanation") or build_explanation(combined)
    if combined.get("explanation") is None:
        combined["explanation"] = explanation

    for entry in providers:
        if entry["status"] != "OK":
            provider_name = entry["provider"]
            explanation["reasons"].insert(
                0,
                f"{provider_name} could not contribute an analysis result "
                f"({entry['status'].lower()}). This verdict rests entirely on "
                f"the remaining provider's output.",
            )

    combined["explanation"] = explanation

    return combined


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
    """Translate a BitMind response into the shared normalized payload.

    Score semantics: BitMind's `confidence` is the detector's own model
    confidence in the `isAI` flag — it is NOT a calibrated manipulation
    probability and its 30/70 risk bands here are reporting bands, not
    provider-documented probability cutoffs. For authentic verdicts the risk
    score expresses residual uncertainty (100% - confidence), which follows
    the same rule the provider exposes; on genuine two-provider flows the
    incompatible score semantics are never averaged (see
    combine_provider_payloads).
    """

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


def _reality_defender_error_to_http(
    error: RealityDefenderError,
    filename: str,
) -> HTTPException:
    """Convert an SDK provider error into the same sanitized FastAPI response
    shape used for BitMind failures (HTTP 424, Failed Dependency).

    The SDK error message is logged for operators but never forwarded: the
    response body omits the API key, the uploaded media bytes, and raw
    SDK/traceback details.
    """
    logger.warning(
        "reality_defender failed for %s: %s",
        filename,
        error,
    )

    return HTTPException(
        status_code=424,
        detail={
            "provider": "Reality Defender",
            "file": filename,
            "message": "The external analysis provider rejected or failed the request. "
            "The request is safe to retry. If the problem persists, verify the "
            "provider API key configuration.",
        },
    )


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

        try:
            result = await analyze_audio(
                file_path
            )
        except RealityDefenderError as error:
            raise _reality_defender_error_to_http(
                error,
                filename,
            ) from error

        return normalize_reality_defender(
            result
        )

    raise ValueError(
        "Unsupported media type"
    )
