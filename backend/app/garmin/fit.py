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


def extract_fit_from_zip(data: bytes) -> bytes:
    """The Personal API download-service returns a ZIP containing the .FIT.

    If ``data`` is a zip, return the first .fit entry's bytes; otherwise assume
    ``data`` is already a raw FIT file and return it unchanged.
    """
    import io
    import zipfile

    if len(data) >= 4 and data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            name = fit_names[0] if fit_names else (zf.namelist()[0] if zf.namelist() else None)
            if name is None:
                return b""
            return zf.read(name)
    return data


def _per_leg_cadence(activity_type: str | None) -> bool:
    t = (activity_type or "").lower()
    return "run" in t or "walk" in t


def parse_fit_records(
    fit_bytes: bytes, activity_type: str | None = None
) -> list[dict[str, Any]]:
    """Parse a FIT file's record messages into normalized sample dicts.

    Accepts either a raw .FIT file or a ZIP archive containing one (the Personal
    API download-service returns a zip). For running/walking ``activity_type`` the FIT
    cadence is per-leg, so it is doubled (incl. fractional_cadence) to match the
    steps-per-minute figure Garmin reports. Returns an empty list (not an error)
    when there are no record messages, so callers treat "no time series"
    gracefully.
    """
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "garmin-fit-sdk is not installed; cannot parse FIT files"
        ) from exc

    fit_bytes = extract_fit_from_zip(fit_bytes)
    if not fit_bytes:
        return []
    stream = Stream.from_byte_array(bytearray(fit_bytes))
    decoder = Decoder(stream)
    messages, errors = decoder.read()
    if errors:
        # Log but continue; partial decode is still useful.
        logger.warning("FIT decode reported %d non-fatal issue(s)", len(errors))

    records = messages.get("record_mesgs", []) if isinstance(messages, dict) else []
    samples: list[dict[str, Any]] = []
    per_leg = _per_leg_cadence(activity_type)
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
        cadence = _num(rec.get("cadence"))
        if per_leg and cadence is not None:
            cadence = (cadence + (_num(rec.get("fractional_cadence")) or 0.0)) * 2
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
                "cadence": cadence,
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
