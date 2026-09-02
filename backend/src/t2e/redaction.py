"""Redaction on import, and PII-lookalike detection (spec 03 sec 11).

Real traces carry customer text, so redaction runs by default and happens *before* normalization -
previews are derived from already-redacted payloads, so a secret can never reach the UI or an export
through a preview.

Two classes of pattern:
  * `redact=True`  - replaced in place with `[REDACTED:<name>]`
  * `redact=False` - detect-only, too false-positive-prone to rewrite automatically, but they still
    raise the warning banner so a human can decide

Redaction is idempotent: the `[REDACTED:...]` placeholder matches none of the patterns.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from t2e.schemas import RawRun, RawStep


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern[str]
    #: False = flag it in the report but leave the text alone.
    redact: bool = True
    #: Optional extra check to suppress false positives (e.g. Luhn on card-shaped digits).
    validator: str | None = None


def _luhn_ok(digits: str) -> bool:
    """Card-shaped numbers are only redacted if they pass Luhn, so IDs and order numbers survive."""
    nums = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(nums) <= 19:
        return False
    total = 0
    for i, digit in enumerate(reversed(nums)):
        if i % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


DEFAULT_PATTERNS: tuple[Pattern, ...] = (
    Pattern("email", re.compile(r"\b[\w.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    Pattern(
        "api_key",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}"
            r"|ghp_[A-Za-z0-9]{20,}"
            r"|gh[pousr]_[A-Za-z0-9]{20,}"
            r"|AKIA[0-9A-Z]{16}"
            r"|xox[baprs]-[A-Za-z0-9-]{10,})\b"
        ),
    ),
    Pattern("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*")),
    Pattern("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    Pattern(
        "iban",
        re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    ),
    Pattern(
        "credit_card",
        re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        validator="luhn",
    ),
    Pattern(
        "phone",
        re.compile(
            r"(?<![\w.])(?:\+\d{1,3}[ -]?)?"
            r"(?:\(\d{2,4}\)[ -]?|\d{2,4}[ -])\d{3,4}[ -]\d{3,4}(?![\w.])"
        ),
    ),
    Pattern("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    # --- detect-only: flagged, never rewritten ---
    Pattern(
        "street_address",
        re.compile(
            r"\b\d{1,5}\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+"
            r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Boulevard|Blvd|Drive|Dr)\b"
        ),
        redact=False,
    ),
    Pattern(
        "date_of_birth",
        re.compile(r"\b(?:date[ _-]?of[ _-]?birth|dob)\b", re.IGNORECASE),
        redact=False,
    ),
)

_VALIDATORS = {"luhn": _luhn_ok}


def load_extra_patterns(path: str | Path) -> list[Pattern]:
    """Read `name=regex` lines from a file. Bad lines are skipped rather than fatal."""
    patterns: list[Pattern] = []
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return patterns
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, expression = line.partition("=")
        try:
            patterns.append(Pattern(name.strip(), re.compile(expression.strip())))
        except re.error:
            continue
    return patterns


class _Redactor:
    """Applies a pattern set, accumulating a count and the set of names seen."""

    def __init__(self, patterns: Sequence[Pattern]) -> None:
        self.patterns = patterns
        self.count = 0
        self.flags: set[str] = set()

    def text(self, value: str) -> str:
        for pattern in self.patterns:
            validator = _VALIDATORS.get(pattern.validator or "")

            def replace(match: re.Match[str], _p: Pattern = pattern, _v=validator) -> str:
                if _v is not None and not _v(match.group(0)):
                    return match.group(0)
                self.flags.add(_p.name)
                if not _p.redact:
                    return match.group(0)
                self.count += 1
                return f"[REDACTED:{_p.name}]"

            value = pattern.regex.sub(replace, value)
        return value

    def value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {key: self.value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.value(item) for item in value)
        return value


def redact_text(
    text: str, patterns: Sequence[Pattern] | None = None
) -> tuple[str, int, list[str]]:
    redactor = _Redactor(patterns or DEFAULT_PATTERNS)
    result = redactor.text(text)
    return result, redactor.count, sorted(redactor.flags)


def redact_value(
    value: Any, patterns: Sequence[Pattern] | None = None
) -> tuple[Any, int, list[str]]:
    redactor = _Redactor(patterns or DEFAULT_PATTERNS)
    result = redactor.value(value)
    return result, redactor.count, sorted(redactor.flags)


def scan_for_pii(value: Any, patterns: Sequence[Pattern] | None = None) -> list[str]:
    """Detect without rewriting. Drives the warning banner when redaction is disabled."""
    redactor = _Redactor(patterns or DEFAULT_PATTERNS)
    redactor.value(value)
    return sorted(redactor.flags)


def redact_raw_run(
    raw: RawRun, patterns: Sequence[Pattern] | None = None
) -> tuple[RawRun, int, list[str]]:
    """Redact a parsed run before normalization, so previews are built from clean payloads."""
    redactor = _Redactor(patterns or DEFAULT_PATTERNS)

    steps = [
        RawStep(
            kind=step.kind,
            name=step.name,
            args=redactor.value(step.args),
            output=redactor.value(step.output),
            started=step.started,
            ended=step.ended,
            latency_ms=step.latency_ms,
            error=redactor.text(step.error) if step.error else None,
            order_key=step.order_key,
            meta=redactor.value(step.meta),
        )
        for step in raw.steps
    ]

    cleaned = raw.model_copy(
        update={
            "input": redactor.value(raw.input),
            "output": redactor.value(raw.output),
            "error": redactor.text(raw.error) if raw.error else None,
            "steps": steps,
            # `meta` holds trace ids and file names, not payloads, but scan it anyway.
            "meta": redactor.value(raw.meta),
        }
    )
    return cleaned, redactor.count, sorted(redactor.flags)


def redact_runs(
    raws: Iterable[RawRun], patterns: Sequence[Pattern] | None = None
) -> tuple[list[RawRun], int, list[str]]:
    cleaned: list[RawRun] = []
    total = 0
    flags: set[str] = set()
    for raw in raws:
        run, count, run_flags = redact_raw_run(raw, patterns)
        cleaned.append(run)
        total += count
        flags.update(run_flags)
    return cleaned, total, sorted(flags)
