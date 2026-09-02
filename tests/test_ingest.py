"""The import pipeline end to end: parse -> redact -> normalize -> store."""

from __future__ import annotations

import pytest

from t2e import store
from t2e.ingest import expand_paths, ingest_file, ingest_paths, ingest_text


def test_importing_both_formats_populates_the_store(db, fixtures_dir):
    reports = ingest_paths([fixtures_dir / "otel", fixtures_dir / "langsmith"])

    assert len(reports) == 12, "6 fixtures per format"
    assert sum(r.runs_imported for r in reports) > 0

    with store.session_scope() as session:
        runs = store.list_runs(session)
        sources = {r.source for r in runs}

    assert sources == {"otel", "langsmith"}


def test_directory_expansion_is_sorted_and_deduplicated(fixtures_dir):
    once = expand_paths([fixtures_dir / "otel"])
    twice = expand_paths([fixtures_dir / "otel", fixtures_dir / "otel"])

    assert [p.name for p in once] == sorted(p.name for p in once)
    assert once == twice, "naming a path twice must import it once"


def test_format_is_sniffed_per_file(db, fixtures_dir):
    with store.session_scope() as session:
        otel_report = ingest_file(session, fixtures_dir / "otel" / "05_minimal_flat_events.json")
        langsmith_report = ingest_file(
            session, fixtures_dir / "langsmith" / "01_clean_reconciliation.jsonl"
        )

    assert otel_report.format == "otel"
    assert langsmith_report.format == "langsmith"


def test_explicit_format_overrides_sniffing(db, fixtures_dir):
    with store.session_scope() as session:
        report = ingest_file(
            session, fixtures_dir / "otel" / "01_clean_reconciliation.json", fmt="langsmith"
        )

    # Forcing the wrong parser must fail loudly in the report, not crash and not silently import.
    assert report.format == "langsmith"
    assert report.runs_imported == 0
    assert report.errors


def test_unidentifiable_content_is_reported(db):
    with store.session_scope() as session:
        report = ingest_text(session, "hello, world", file_label="notes.txt")

    assert report.runs_imported == 0
    assert "could not identify the trace format" in report.errors[0].reason


def test_redaction_is_applied_on_import_by_default(db, fixtures_dir):
    with store.session_scope() as session:
        report = ingest_file(session, fixtures_dir / "otel" / "02_tool_heavy_with_pii.json")

    assert report.redactions > 0
    assert {"email", "phone", "iban", "credit_card"} <= set(report.pii_flags)

    with store.session_scope() as session:
        run = store.run_row_to_trace_run(
            store.get_run(session, "7c1d5e9a3f8b2d6c4a0e7f1b8d3c5a92")
        )

    blob = str(run.model_dump())
    assert "northwind-supplies.example" not in blob
    assert "GB29NWBK60161331926819" not in blob
    assert "4111111111111111" not in blob
    assert "[REDACTED:email]" in blob


def test_redaction_can_be_disabled_but_still_warns(db, fixtures_dir):
    with store.session_scope() as session:
        report = ingest_file(
            session, fixtures_dir / "otel" / "02_tool_heavy_with_pii.json", redact=False
        )

    assert report.redactions == 0
    assert report.pii_flags, "the warning banner still needs its signal"
    assert any("redaction was disabled" in w for w in report.warnings)

    with store.session_scope() as session:
        run = store.run_row_to_trace_run(
            store.get_run(session, "7c1d5e9a3f8b2d6c4a0e7f1b8d3c5a92")
        )
    assert "northwind-supplies.example" in str(run.model_dump())


def test_reimporting_the_same_file_is_idempotent(db, fixtures_dir):
    path = fixtures_dir / "otel" / "01_clean_reconciliation.json"

    ingest_paths([path])
    with store.session_scope() as session:
        first = store.count_runs(session)

    ingest_paths([path])
    with store.session_scope() as session:
        assert store.count_runs(session) == first


def test_malformed_file_imports_partially_and_reports(db, fixtures_dir):
    with store.session_scope() as session:
        report = ingest_file(session, fixtures_dir / "langsmith" / "06_malformed_mixed.jsonl")

    assert report.runs_imported == 2
    assert report.errors

    with store.session_scope() as session:
        assert store.count_runs(session) == 2


def test_missing_path_is_reported_not_raised(db, tmp_path):
    reports = ingest_paths([tmp_path / "nothing_here.json"])

    assert len(reports) == 1
    assert reports[0].runs_imported == 0
    assert "could not read file" in reports[0].errors[0].reason


@pytest.mark.parametrize("suffix", [".json", ".jsonl", ".ndjson"])
def test_all_trace_suffixes_are_discovered(tmp_path, suffix):
    (tmp_path / f"trace{suffix}").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.md").write_text("ignore me", encoding="utf-8")

    found = [p.name for p in expand_paths([tmp_path])]

    assert found == [f"trace{suffix}"]
