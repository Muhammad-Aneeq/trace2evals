"""The import pipeline: parse -> redact -> normalize -> store.

Kept separate from `t2e.parsers` so that package stays a pure registry of format readers, and
so the CLI and the API share one definition of what "importing a file" means.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from t2e import parsers, redaction
from t2e.config import get_settings
from t2e.normalizer import normalize_runs
from t2e.schemas import ParseReport
from t2e.store import save_run, session_scope

#: Extensions considered importable when a directory is given.
TRACE_SUFFIXES = (".json", ".jsonl", ".ndjson")


def expand_paths(paths: Sequence[str | Path]) -> list[Path]:
    """Expand directories into a sorted, deterministic file list; keep explicit files as given."""
    found: list[Path] = []
    for entry in paths:
        path = Path(entry)
        if path.is_dir():
            found.extend(
                sorted(
                    child
                    for child in path.rglob("*")
                    if child.is_file() and child.suffix.lower() in TRACE_SUFFIXES
                )
            )
        else:
            found.append(path)
    # De-duplicate while preserving order (a file named twice imports once).
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def ingest_text(
    session: Session,
    text: str,
    *,
    file_label: str,
    fmt: str = "auto",
    redact: bool | None = None,
) -> ParseReport:
    """Import one file's worth of trace text. Never raises on bad trace data."""
    result = parsers.parse_text(text, file_label=file_label, fmt=fmt)
    report = result.report

    should_redact = get_settings().redact if redact is None else redact
    runs = result.runs

    if should_redact:
        runs, count, flags = redaction.redact_runs(runs)
        report.redactions = count
        report.pii_flags = flags
    else:
        flags: set[str] = set()
        for raw in runs:
            flags.update(redaction.scan_for_pii(raw.model_dump()))
        report.pii_flags = sorted(flags)
        if report.pii_flags:
            report.warnings.append(
                "redaction was disabled but PII-lookalike payloads were detected"
            )

    for run in normalize_runs(runs):
        save_run(session, run)

    return report


def ingest_file(
    session: Session, path: str | Path, *, fmt: str = "auto", redact: bool | None = None
) -> ParseReport:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report = ParseReport(file=path.name, format=fmt)
        report.records_seen += 1
        report.add_error("<file>", f"could not read file: {exc}")
        return report
    return ingest_text(session, text, file_label=path.name, fmt=fmt, redact=redact)


def ingest_paths(
    paths: Sequence[str | Path], *, fmt: str = "auto", redact: bool | None = None
) -> list[ParseReport]:
    """Import every file in `paths`, one report per file. Used by `t2e import`."""
    reports: list[ParseReport] = []
    with session_scope() as session:
        for path in expand_paths(paths):
            reports.append(ingest_file(session, path, fmt=fmt, redact=redact))
    return reports
