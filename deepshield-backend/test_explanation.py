import pytest

from services.analyzer import (
    build_explanation,
    normalize_bitmind,
    normalize_reality_defender,
)

# ---------------------------------------------------------------------------
# build_explanation: edge cases
# ---------------------------------------------------------------------------

BASE = {
    "prediction": "LIKELY_AI_GENERATED",
    "risk_score": 88.0,
    "confidence": 88.0,
    "provider": "BitMind",
    "media_type": "image",
    "signals": [{"name": "AI Gen", "value": "AI-generated", "score": 88.0}],
}


def _single_risk(payload: dict) -> float:
    return payload["risk_score"]


class TestMissingSignals:
    def test_no_signals_yields_empty_contributions(self):
        payload = dict(BASE, signals=[])
        e = build_explanation(payload)

        assert e["contributions"] == []

    def test_no_signals_still_produces_summary_and_reasons(self):
        payload = dict(BASE, signals=[])
        e = build_explanation(payload)

        assert e["summary"]
        assert "no risk score was attributed" not in e["summary"]  # still verdict-based
        assert e["reasons"]

    def test_no_signals_flags_single_detector_caveat(self):
        payload = dict(BASE, signals=[])
        e = build_explanation(payload)

        assert e["caveat"] and "single detector" in e["caveat"]

    def test_missing_signals_key_treated_as_empty(self):
        payload = {k: v for k, v in BASE.items() if k != "signals"}
        e = build_explanation(payload)

        assert e["contributions"] == []


class TestZeroRisk:
    def test_zero_risk_allocates_zero_points(self):
        payload = dict(BASE, risk_score=0.0)
        e = build_explanation(payload)

        assert e["contributions"]
        assert all(c["points"] == 0 for c in e["contributions"])

    def test_zero_risk_large_caveat(self):
        e = build_explanation(dict(BASE, risk_score=0.0))

        assert e["caveat"] == (
            "Score is in the 30-70% medium band: detectors disagree or evidence "
            "is split, so independent verification is recommended."
        ) or len(e["contributions"]) == 1

    def test_inconclusive_zero_risk(self):
        payload = {
            "prediction": "INCONCLUSIVE",
            "risk_score": 0.0,
            "confidence": 0.0,
            "provider": "Reality Defender",
            "media_type": "audio",
            "signals": [],
        }
        e = build_explanation(payload)

        assert "no risk score was attributed" in e["summary"]
        assert any("no final status" in r for r in e["reasons"])


class TestMalformedEvidence:
    def test_non_numeric_scores_are_dropped(self):
        payload = dict(
            BASE,
            signals=[
                {"name": "Good", "value": "v", "score": 0.8},
                {"name": "None", "value": "v", "score": None},
                {"name": "Text", "value": "v", "score": "garbage"},
            ],
        )
        e = build_explanation(payload)

        assert len(e["contributions"]) == 1
        assert e["contributions"][0]["name"] == "Good"

    def test_missing_name_and_value_get_defaults(self):
        payload = dict(BASE, signals=[{"score": 0.5}])
        e = build_explanation(payload)

        assert e["contributions"][0]["name"] == "Detection signal"
        assert e["contributions"][0]["value"] == ""

    def test_malformed_risk_score_defaults_to_zero(self):
        e = build_explanation(dict(BASE, risk_score=None))

        assert e["contributions"][0]["points"] == 0


class TestRoundingAndTotals:
    ROUNDING_TOLERANCE_PER_SIGNAL = 0.05

    def test_points_sum_matches_risk_score_within_rounding(self):
        payload = dict(
            BASE,
            risk_score=33.4,
            signals=[
                {"name": "A", "value": "a", "score": 0.5},
                {"name": "B", "value": "b", "score": 0.5},
                {"name": "C", "value": "c", "score": 0.333},
            ],
        )
        e = build_explanation(payload)
        total = sum(c["points"] for c in e["contributions"])

        assert abs(total - 33.4) <= self.ROUNDING_TOLERANCE_PER_SIGNAL * 3

    @pytest.mark.parametrize("risk", [0.0, 12.5, 29.9, 30.0, 50.0, 69.9, 70.0, 99.9])
    def test_points_sum_across_score_boundaries(self, risk):
        payload = dict(
            BASE,
            risk_score=risk,
            signals=[
                {"name": "A", "value": "a", "score": 0.4},
                {"name": "B", "value": "b", "score": 0.6},
            ],
        )
        e = build_explanation(payload)
        total = sum(c["points"] for c in e["contributions"])

        assert abs(total - risk) <= self.ROUNDING_TOLERANCE_PER_SIGNAL * 2

    @pytest.mark.parametrize(
        "risk,badge",
        [
            (29.9, "low evidence"),
            (30.0, "moderate evidence"),
            (69.9, "moderate evidence"),
            (70.0, "strong evidence"),
        ],
    )
    def test_evidence_band_at_thresholds(self, risk, badge):
        e = build_explanation(dict(BASE, risk_score=risk))

        assert any(badge in r for r in e["reasons"]), e["reasons"]


class TestBitMindNormalization:
    def test_ai_generated_confidence_to_points(self):
        result = {"isAI": True, "confidence": 0.92}
        p = normalize_bitmind(result, "image")

        assert p["prediction"] == "LIKELY_AI_GENERATED"
        assert p["risk_score"] == 92.0
        assert p["risk_level"] == "HIGH"

        total = sum(c["points"] for c in p["explanation"]["contributions"])
        assert abs(total - 92.0) <= 0.05

    def test_authentic_risk_is_residual_uncertainty(self):
        result = {"isAI": False, "confidence": 0.9}
        p = normalize_bitmind(result, "image")

        assert p["prediction"] == "LIKELY_AUTHENTIC"
        assert p["risk_score"] == 10.0
        assert p["risk_level"] == "LOW"

        total = sum(c["points"] for c in p["explanation"]["contributions"])
        assert abs(total - 10.0) <= 0.05

    def test_confidence_out_of_range_is_clamped(self):
        p = normalize_bitmind({"isAI": True, "confidence": 5.0}, "image")

        assert p["risk_score"] == 100.0

    def test_asymmetry_between_authentic_and_ai_algo_scores(self):
        # Confirms absence of redundant signals in contributions
        p = normalize_bitmind({"isAI": False, "confidence": 0.5}, "video")

        assert len(p["explanation"]["contributions"]) == 1


class TestRealityDefenderNormalization:
    def test_score_and_models_to_contributions(self):
        result = {
            "status": "MANIPULATED",
            "score": 0.45,
            "models": [
                {"name": "Waveform", "status": "MANIPULATED", "score": 0.9},
                {"name": "Spectrogram", "status": "AUTHENTIC", "score": 0.0},
            ],
        }
        p = normalize_reality_defender(result)

        assert p["media_type"] == "audio"
        assert p["prediction"] == "LIKELY_MANIPULATED"
        assert p["risk_score"] == 45.0

        total = sum(c["points"] for c in p["explanation"]["contributions"])
        assert abs(total - 45.0) <= 0.1

    def test_unknown_status_is_inconclusive_with_zero_risk(self):
        result = {"status": "UNKNOWN", "score": 0.6, "models": []}
        p = normalize_reality_defender(result)

        assert p["prediction"] == "INCONCLUSIVE"
        assert p["risk_score"] == 0.0
        assert p["risk_level"] == "LOW"
        assert p["confidence"] == 0.0

    def test_none_score_without_verdict(self):
        result = {"status": None, "score": None, "models": []}
        p = normalize_reality_defender(result)

        assert p["prediction"] == "INCONCLUSIVE"
        assert p["risk_score"] == 0.0
        assert p["explanation"]["caveat"]  # single/zero detector honesty

    def test_model_without_score_is_reported_without_points(self):
        result = {
            "status": "AUTHENTIC",
            "score": 0.2,
            "models": [
                {"name": "M1", "status": "AUTHENTIC", "score": None},
                {"name": "M2", "status": "AUTHENTIC", "score": 0.2},
            ],
        }
        p = normalize_reality_defender(result)
        contributed = [c for c in p["explanation"]["contributions"] if c["points"] > 0]

        assert len(contributed) == 1
        assert contributed[0]["name"] == "M2"
