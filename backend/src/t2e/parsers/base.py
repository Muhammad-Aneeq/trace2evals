"""Shared parser plumbing.

The governing rule from spec 03 F1 is "strict-but-forgiving parsing with per-record error report":
a malformed record is recorded in the report and skipped, and every other record in the same file
still imports. No parser in this package is allowed to raise on bad input data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from t2e.schemas import ParseReport, RawRun


@dataclass
class ParseResult:
    """What every parser returns: the runs it recovered plus the report of what it could not use."""

    runs: list[RawRun] = field(default_factory=list)
    report: ParseReport = field(default_factory=lambda: ParseReport(file="", format=""))


# --- tolerant key access ------------------------------------------------------------------------

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _snake(key: str) -> str:
    return _CAMEL_BOUNDARY.sub("_", key).lower()


def _camel(key: str) -> str:
    head, *rest = key.split("_")
    return head + "".join(part.title() for part in rest)


def key_variants(key: str) -> tuple[str, ...]:
    """`startTimeUnixNano` and `start_time_unix_nano` are the same field in different exporters."""
    return tuple(dict.fromkeys((key, _snake(key), _camel(key))))


def pick(data: Any, *keys: str, default: Any = None) -> Any:
    """First present, non-None value among `keys`, tolerating camelCase/snake_case spelling."""
    if not isinstance(data, dict):
        return default
    for key in keys:
        for variant in key_variants(key):
            if variant in data and data[variant] is not None:
                return data[variant]
    return default


# --- timestamps ---------------------------------------------------------------------------------

#: Anything at or above this many seconds-since-epoch is really nanoseconds (year ~2001 in ns).
_NANO_THRESHOLD = 1e17
_MICRO_THRESHOLD = 1e14
_MILLI_THRESHOLD = 1e11


def to_aware(value: datetime) -> datetime:
    """Everything downstream compares timestamps, so they all become UTC-aware here."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_timestamp(value: Any) -> datetime | None:
    """Accept ISO-8601 strings and epoch numbers in ns/us/ms/s. Return None on anything else."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return to_aware(value)

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():  # epoch encoded as a string, which OTLP JSON does for int64
            return _from_epoch(float(text))
        try:
            # `Z` is legal ISO-8601 but fromisoformat only learned it in 3.11+; normalize anyway.
            return to_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None

    if isinstance(value, int | float):
        return _from_epoch(float(value))
    return None


def _from_epoch(number: float) -> datetime | None:
    if number <= 0:
        return None
    if number >= _NANO_THRESHOLD:
        seconds = number / 1e9
    elif number >= _MICRO_THRESHOLD:
        seconds = number / 1e6
    elif number >= _MILLI_THRESHOLD:
        seconds = number / 1e3
    else:
        seconds = number
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


# --- misc ---------------------------------------------------------------------------------------


def excerpt(value: Any) -> str:
    """Render a bad record for the report. JSON, not Python repr, so it reads like the input."""
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def as_error_text(value: Any) -> str | None:
    """Normalize the many shapes an error field arrives in to a non-empty string, or None."""
    if value is None or value is False:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("message", "error", "detail", "reason", "type"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    text = str(value).strip()
    return text or None
