"""Decode .FIT activity files into time-series samples.

Uses the official Garmin FIT SDK for Python (``garmin-fit-sdk``). We extract the
``record`` messages, which carry the per-sample time series (timestamp, position,
heart rate, speed, altitude, cadence, power, distance, temperature).

All fields are optional per record; anything absent stays None (never zero).
Position is stored by the FIT format in semicircles and converted to degrees
using the documented constant 180 / 2^31.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("mygarmin.garmin.fit")

# FIT epoch is 1989-12-31 00:00:00 UTC; convert to Unix epoch.
_FIT_EPOCH_OFFSET = 631065600
# Semicircle -> degree conversion (documented FIT constant).
_SEMICIRCLE_TO_DEG = 180.0 / (2**31)


def _to_unix_seconds(ts: Any) -> int | None:
    """Convert a FIT record timestamp to Unix seconds."""
    if ts is None:
        return None
    # The SDK may yield a datetime or an int of seconds since the FIT epoch.
    try:
        # datetime-like
        if hasattr(ts, "timestamp"):
            return int(ts.timestamp())
    except (OSError, OverflowError, ValueError):
        return None
    try:
        return int(ts) + _FIT_EPOCH_OFFSET
    except (TypeError, ValueError):
        return None


def _semicircles_to_degrees(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v) * _SEMICIRCLE_TO_DEG
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_fit_records(fit_bytes: bytes) -> list[dict[str, Any]]:
    """Parse a FIT file's record messages into normalized sample dicts.

    Returns an empty list (not an error) when the file has no record messages,
    so callers can treat "no time series" gracefully.
    """
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "garmin-fit-sdk is not installed; cannot parse FIT files"
        ) from exc

    stream = Stream.from_byte_array(bytearray(fit_bytes))
    decoder = Decoder(stream)
    messages, errors = decoder.read()
    if errors:
        # Log but continue; partial decode is still useful.
        logger.warning("FIT decode reported %d non-fatal issue(s)", len(errors))

    records = messages.get("record_mesgs", []) if isinstance(messages, dict) else []
    samples: list[dict[str, Any]] = []
    for i, rec in enumerate(records):
        clock = _to_unix_seconds(rec.get("timestamp"))
        lat = _semicircles_to_degrees(rec.get("position_lat"))
        lon = _semicircles_to_degrees(rec.get("position_long"))
        # altitude may be enhanced_altitude; prefer the enhanced value if present.
        elevation = _num(rec.get("enhanced_altitude"))
        if elevation is None:
            elevation = _num(rec.get("altitude"))
        speed = _num(rec.get("enhanced_speed"))
        if speed is None:
            speed = _num(rec.get("speed"))
        samples.append(
            {
                "sample_index": i,
                "offset_seconds": None,  # filled below
                "clock_time_seconds": clock,
                "latitude": lat,
                "longitude": lon,
                "elevation_meters": elevation,
                "heart_rate_bpm": int(rec["heart_rate"]) if rec.get("heart_rate") is not None else None,
                "speed_mps": speed,
                "cadence": _num(rec.get("cadence")),
                "power_watts": _num(rec.get("power")),
                "distance_meters": _num(rec.get("distance")),
                "temperature_celsius": _num(rec.get("temperature")),
                "source": "fit",
            }
        )

    start = min(
        (s["clock_time_seconds"] for s in samples if s["clock_time_seconds"] is not None),
        default=None,
    )
    if start is not None:
        for s in samples:
            if s["clock_time_seconds"] is not None:
                s["offset_seconds"] = s["clock_time_seconds"] - start
    return samples


def fit_has_gps(samples: list[dict[str, Any]]) -> bool:
    return any(s.get("latitude") is not None and s.get("longitude") is not None for s in samples)
