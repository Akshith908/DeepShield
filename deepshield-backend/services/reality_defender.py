from __future__ import annotations

import logging
import os
import re
import time

from realitydefender import RealityDefender

logger = logging.getLogger(__name__)


_POSITIVE_INT_RE = re.compile(r"^[1-9]\d*$")

# Polling defaults.
#
# The SDK default window is 2000ms / 30 attempts (~60s), which abandons longer
# valid scans, so this app has always used a ~5 minute window. Measured audio
# runs show the provider usually finishes well inside the first interval, so
# the fixed sleep dominates detection latency: dropping the interval from
# 2000ms to 1000ms cut median end-to-end time by ~0.9-1.2s across valid MP3,
# OGG, and 8MB WAV samples with no errors and the same terminal statuses.
#
# 1000ms * 300 attempts preserves the prior ~5 minute (300s) deadline exactly,
# while 1000ms keeps peak request rate at ~1/s (no documented limit is
# exceeded, and typical runs still need only 2-4 result requests).
DEFAULT_POLL_INTERVAL_MS = 1000
DEFAULT_MAX_ATTEMPTS = 300


def _parse_positive_int(value: str | None, name: str, default: int) -> int:
    """Parse a required-positive integer configuration value.

    Returns the parsed value, or `default` when the environment variable is
    unset. Raises `RuntimeError` for present but invalid values so that bad
    configuration is rejected early and explicitly.
    """
    if value is None:
        return default

    if not _POSITIVE_INT_RE.match(value):
        raise RuntimeError(
            f"Invalid {name}: {value!r}. "
            f"Expected a positive integer (for example {default})."
        )

    parsed = int(value)
    if parsed <= 0:
        raise RuntimeError(
            f"Invalid {name}: {value!r}. Must be a positive integer."
        )

    return parsed


def load_polling_config() -> dict[str, int]:
    """Load and validate Reality Defender polling configuration from env.

    Defaults poll every 1000ms for up to 300 attempts, preserving the app's
    ~5 minute polling deadline while halving detection-granularity latency.
    (The SDK's own default is 2000ms / 30 attempts.)
    """
    polling_interval_ms = _parse_positive_int(
        os.getenv("RD_POLL_INTERVAL_MS"),
        "RD_POLL_INTERVAL_MS",
        DEFAULT_POLL_INTERVAL_MS,
    )

    max_attempts = _parse_positive_int(
        os.getenv("RD_POLL_MAX_ATTEMPTS"),
        "RD_POLL_MAX_ATTEMPTS",
        DEFAULT_MAX_ATTEMPTS,
    )

    return {
        "polling_interval_ms": polling_interval_ms,
        "max_attempts": max_attempts,
    }


def _now_ms() -> float:
    return time.perf_counter() * 1000.0


def _log_stage(stage: str, start_ms: float, end_ms: float, file_basename: str) -> None:
    """Log a stage duration without credentials, media bytes, or user data."""
    logger.info(
        "reality_defender %s took %.0f ms for %s",
        stage,
        end_ms - start_ms,
        file_basename,
    )


async def analyze_audio(file_path: str) -> dict:
    api_key = os.getenv("REALITY_DEFENDER_API_KEY")

    if not api_key:
        raise RuntimeError(
            "REALITY_DEFENDER_API_KEY is not configured"
        )

    config = load_polling_config()

    rd = RealityDefender(api_key=api_key)

    t_upload_start = _now_ms()

    try:
        upload_response = await rd.upload(
            file_path=file_path
        )
    finally:
        await rd.cleanup()

    t_upload_end = _now_ms()
    _log_stage(
        "upload",
        t_upload_start,
        t_upload_end,
        os.path.basename(file_path),
    )

    request_id = upload_response["request_id"]

    t_result_start = _now_ms()

    result = await rd.get_result(
        request_id,
        max_attempts=config["max_attempts"],
        polling_interval=config["polling_interval_ms"],
    )

    t_result_end = _now_ms()
    _log_stage(
        "poll",
        t_result_start,
        t_result_end,
        os.path.basename(file_path),
    )

    logger.info(
        "reality_defender total %.0f ms for %s",
        t_result_end - t_upload_start,
        os.path.basename(file_path),
    )

    return result
