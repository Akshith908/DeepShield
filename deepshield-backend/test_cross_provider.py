"""Simulated-provider cross-provider tests.

All provider payloads in this module are hand-built representative outputs.
Reality Defender is NEVER called (its quota is exhausted); these tests pin
the combine semantics in services.analyzer, not live provider behavior.
"""

import pytest

from services.analyzer import combine_provider_payloads


BITMIND_AI = {
    "success": True,
    "media_type": "image",
    "provider": "BitMind",
    "prediction": "LIKELY_AI_GENERATED",
    "risk_score": 88.0,
    "risk_level": "HIGH",
    "confidence": 88.0,
    "signals": [
        {"name": "AI Generation Detection", "value": "AI-generated", "score": 88.0},
    ],
    "explanation": {
        "summary": "flagged as AI-generated",
        "reasons": ["BitMind classified the file as AI-generated."],
        "contributions": [
            {"name": "AI Generation Detection", "value": "AI-generated", "score": 88.0, "points": 88.0},
        ],
        "caveat": "single detector",
    },
}

BITMIND_AUTHENTIC = {
    "success": True,
    "media_type": "image",
    "provider": "BitMind",
    "prediction": "LIKELY_AUTHENTIC",
    "risk_score": 20.0,
    "risk_level": "LOW",
    "confidence": 80.0,
    "signals": [
        {"name": "AI Generation Detection", "value": "authentic", "score": 20.0},
    ],
    "explanation": {
        "summary": "no strong signal",
        "reasons": ["BitMind found no AI-generation signal."],
        "contributions": [
            {"name": "AI Generation Detection", "value": "authentic", "score": 20.0, "points": 20.0},
        ],
        "caveat": "single detector",
    },
}

RD_AUTHENTIC = {
    "success": True,
    "media_type": "audio",
    "provider": "Reality Defender",
    "prediction": "LIKELY_AUTHENTIC",
    "risk_score": 15.0,
    "risk_level": "LOW",
    "confidence": 15.0,
    "signals": [
        {"name": "Waveform Model", "value": "AUTHENTIC", "score": 15.0},
        {"name": "Spectrogram Model", "value": "AUTHENTIC", "score": 10.0},
    ],
    "explanation": {
        "summary": "authentic",
        "reasons": ["aggregate 15%"],
        "contributions": [],
        "caveat": None,
    },
}

RD_MANIPULATED = {
    "success": True,
    "media_type": "audio",
    "provider": "Reality Defender",
    "prediction": "LIKELY_MANIPULATED",
    "risk_score": 62.0,
    "risk_level": "MEDIUM",
    "confidence": 62.0,
    "signals": [
        {"name": "Waveform Model", "value": "MANIPULATED", "score": 62.0},
    ],
    "explanation": {
        "summary": "manipulated",
        "reasons": ["aggregate 62%"],
        "contributions": [],
        "caveat": None,
    },
}

RD_INCONCLUSIVE = {
    "success": True,
    "media_type": "audio",
    "provider": "Reality Defender",
    "prediction": "INCONCLUSIVE",
    "risk_score": 0.0,
    "risk_level": "LOW",
    "confidence": 0.0,
    "signals": [],
    "explanation": {
        "summary": "no verdict",
        "reasons": ["no final status"],
        "contributions": [],
        "caveat": "single/zero detector",
    },
}


class TestAgreement:
    def test_both_agree_authentic(self):
        combined = combine_provider_payloads(BITMIND_AUTHENTIC, RD_AUTHENTIC)

        assert combined["prediction"] == "LIKELY_AUTHENTIC"
        # Conservative upper bound of the agreeing scores (20 vs 15).
        assert combined["risk_score"] == 20.0
        assert combined["risk_level"] == "LOW"
        assert any("agree" in r for r in combined["explanation"]["reasons"])
        assert any("not proof" in r for r in combined["explanation"]["reasons"])
        assert {p["provider"] for p in combined["providers"]} == {
            "BitMind", "Reality Defender"
        }
        assert all(p["status"] == "OK" for p in combined["providers"])

    def test_both_agree_manipulation(self):
        combined = combine_provider_payloads(BITMIND_AI, RD_MANIPULATED)

        assert combined["prediction"] in {"LIKELY_AI_GENERATED", "LIKELY_MANIPULATED"}
        assert combined["risk_score"] == 88.0  # upper bound: 88 vs 62
        assert combined["risk_level"] == "HIGH"
        assert any("agree" in r for r in combined["explanation"]["reasons"])


class TestDisagreement:
    def test_providers_disagree_verdict_is_uncertain(self):
        combined = combine_provider_payloads(BITMIND_AUTHENTIC, RD_MANIPULATED)

        # Never silently picks the more extreme verdict.
        assert combined["prediction"] == "INCONCLUSIVE"
        # Never averages incompatible scales; upper bound is stated.
        assert combined["risk_score"] == 62.0
        assert any("disagree" in r for r in combined["explanation"]["reasons"])
        assert any(
            "not an average" in r for r in combined["explanation"]["reasons"]
        )
        assert "uncertain" in combined["explanation"]["caveat"]

    def test_disagreement_reports_both_individual_scores(self):
        combined = combine_provider_payloads(BITMIND_AUTHENTIC, RD_MANIPULATED)
        ledger = {p["provider"]: p for p in combined["providers"]}

        assert ledger["BitMind"]["risk_score"] == 20.0
        assert ledger["Reality Defender"]["risk_score"] == 62.0

    def test_contributions_are_tagged_per_provider(self):
        combined = combine_provider_payloads(BITMIND_AUTHENTIC, RD_AUTHENTIC)

        names = [c["name"] for c in combined["explanation"]["contributions"]]
        assert any(n.startswith("BitMind") for n in names)
        assert any(n.startswith("Reality Defender") for n in names)

        upper = combined["risk_score"]
        points = sum(c["points"] for c in combined["explanation"]["contributions"])
        assert abs(points - upper) <= 0.1


class TestPartialFailure:
    def test_bitmind_ok_reality_defender_failed(self):
        combined = combine_provider_payloads(
            BITMIND_AI,
            None,
            secondary_error={
                "provider": "Reality Defender",
                "kind": "failed",
                "message": "Provider rejected the request.",
            },
        )

        # The valid result is preserved verbatim.
        assert combined["prediction"] == "LIKELY_AI_GENERATED"
        assert combined["risk_score"] == 88.0
        assert combined["provider"] == "BitMind"

        ledger = {p["provider"]: p for p in combined["providers"]}
        assert ledger["BitMind"]["status"] == "OK"
        assert ledger["Reality Defender"]["status"] == "FAILED"
        assert "risk_score" not in ledger["Reality Defender"]  # nothing fabricated

        assert any(
            "Reality Defender" in r and "could not contribute" in r
            for r in combined["explanation"]["reasons"]
        )

    def test_reality_defender_ok_bitmind_failed(self):
        combined = combine_provider_payloads(
            None,
            RD_AUTHENTIC,
            secondary_error={
                "provider": "BitMind",
                "kind": "failed",
                "message": "Provider rejected the request.",
            },
        )

        assert combined["prediction"] == "LIKELY_AUTHENTIC"
        assert combined["risk_score"] == 15.0
        assert combined["provider"] == "Reality Defender"

        ledger = {p["provider"]: p for p in combined["providers"]}
        assert ledger["Reality Defender"]["status"] == "OK"
        assert ledger["BitMind"]["status"] == "FAILED"

    def test_unavailability_distinguished_from_failure(self):
        combined = combine_provider_payloads(
            BITMIND_AI,
            None,
            secondary_error={
                "provider": "Reality Defender",
                "kind": "unavailable",
            },
        )
        ledger = {p["provider"]: p for p in combined["providers"]}

        assert ledger["Reality Defender"]["status"] == "UNAVAILABLE"

    def test_both_fail_raises_no_fabricated_verdict(self):
        with pytest.raises(ValueError):
            combine_provider_payloads(None, None)


class TestInconclusive:
    def test_one_provider_inconclusive_uncertainty_reported(self):
        combined = combine_provider_payloads(BITMIND_AI, RD_INCONCLUSIVE)

        assert combined["prediction"] == "LIKELY_AI_GENERATED"
        assert combined["risk_score"] == 88.0
        assert any("no final verdict" in r for r in combined["explanation"]["reasons"])

    def test_both_inconclusive_is_unchanged_uncertain(self):
        rd = dict(RD_INCONCLUSIVE, risk_score=0.0)
        bitmind_inconclusive = dict(
            BITMIND_AI,
            prediction="INCONCLUSIVE",
            risk_score=0.0,
        )

        combined = combine_provider_payloads(bitmind_inconclusive, rd)

        assert combined["prediction"] == "INCONCLUSIVE"
        assert combined["risk_score"] == 0.0


class TestMalformedEvidence:
    def test_malformed_secondary_signals_do_not_crash_combination(self):
        broken_rd = dict(RD_AUTHENTIC, signals=[
            {"name": "Broken", "value": "x", "score": None},
            {"name": "Bad", "value": "y", "score": "junk"},
        ])

        combined = combine_provider_payloads(BITMIND_AUTHENTIC, broken_rd)

        assert combined["prediction"] == "LIKELY_AUTHENTIC"
        # Only BitMind's valid signal is used as evidence.
        names = [c["name"] for c in combined["explanation"]["contributions"]]
        assert all(n.startswith("BitMind") for n in names)


class TestNoLeakage:
    def test_provider_ledger_contains_no_credentials_or_sdk_details(self):
        combined = combine_provider_payloads(
            BITMIND_AI,
            None,
            secondary_error={
                "provider": "Reality Defender",
                "kind": "failed",
                "message": "Invalid API key (Code: unauthorized)",
            },
        )

        ledger_text = str(combined["providers"])
        for secret in ("Bearer", "BITMIND_API_KEY", "sk-", "eyJ"):
            assert secret not in ledger_text
