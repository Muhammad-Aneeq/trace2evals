"""Parser registry and format sniffing.

Exactly two importers exist in v1 and that is deliberate (spec 03 sec 2 non-goals: "more than two
formats"). Adding a third means adding it here *and* arguing for it against that non-goal.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from t2e.parsers import langsmith, otel
from t2e.parsers.base import ParseResult

#: format name -> text parser. `parse_text(text, file_label)` is the whole parser contract.
PARSERS: dict[str, Callable[[str, str], ParseResult]] = {
    otel.SOURCE: otel.parse_text,
    langsmith.SOURCE: langsmith.parse_text,
}

FORMATS = tuple(PARSERS)

#: Substrings that identify a format by content, weighted by how conclusive they are.
_OTEL_MARKERS = (
    ('"resourceSpans"', 5),
    ('"resource_spans"', 5),
    ('"scopeSpans"', 4),
    ('"scope_spans"', 4),
    ('"spanId"', 3),
    ('"traceId"', 2),
    ('"startTimeUnixNano"', 3),
    ('"gen_ai.', 1),
)
_LANGSMITH_MARKERS = (
    ('"run_type"', 5),
    ('"dotted_order"', 4),
    ('"parent_run_id"', 3),
    ('"child_run_ids"', 3),
    ('"session_id"', 1),
    ('"inputs"', 1),
)

_EXTENSION_HINT = {".jsonl": langsmith.SOURCE, ".ndjson": langsmith.SOURCE, ".json": otel.SOURCE}

#: Only the head of a large file is inspected; markers appear early in both formats.
_SNIFF_BYTES = 65_536


def score_formats(text: str) -> dict[str, int]:
    head = text[:_SNIFF_BYTES]
    return {
        otel.SOURCE: sum(weight for marker, weight in _OTEL_MARKERS if marker in head),
        langsmith.SOURCE: sum(weight for marker, weight in _LANGSMITH_MARKERS if marker in head),
    }


def sniff_format(text: str, filename: str | None = None) -> str | None:
    """Identify the format by content, using the file extension only to break a tie."""
    scores = score_formats(text)
    best = max(scores, key=lambda name: scores[name])
    if scores[best] > 0 and scores[best] != min(scores.values()):
        return best

    if filename:
        hint = _EXTENSION_HINT.get(Path(filename).suffix.lower())
        if hint:
            return hint
    return best if scores[best] > 0 else None


def parse_text(text: str, file_label: str = "<text>", fmt: str = "auto") -> ParseResult:
    """Parse with an explicit format, or sniff when `fmt` is "auto"."""
    if fmt == "auto":
        detected = sniff_format(text, file_label)
        if detected is None:
            from t2e.schemas import ParseReport

            report = ParseReport(file=file_label, format="unknown")
            report.records_seen += 1
            report.add_error(
                "<file>",
                "could not identify the trace format; pass --format otel or --format langsmith",
                excerpt=text[:200],
            )
            return ParseResult(report=report)
        fmt = detected

    if fmt not in PARSERS:
        raise ValueError(f"unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")
    return PARSERS[fmt](text, file_label)


def parse_file(path: str | Path, fmt: str = "auto") -> ParseResult:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        from t2e.schemas import ParseReport

        report = ParseReport(file=path.name, format=fmt)
        report.records_seen += 1
        report.add_error("<file>", f"could not read file: {exc}")
        return ParseResult(report=report)
    return parse_text(text, file_label=path.name, fmt=fmt)


__all__ = ["FORMATS", "PARSERS", "parse_file", "parse_text", "score_formats", "sniff_format"]
