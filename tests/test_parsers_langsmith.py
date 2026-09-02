"""LangSmith importer: snapshot-tested normalization, plus the malformed-record contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from t2e.normalizer import normalize_runs
from t2e.parsers import langsmith, sniff_format

FIXTURE_NAMES = [
    "01_clean_reconciliation",
    "02_wrong_tool_bad_args",
    "03_tool_error_run_failed",
    "04_nested_handoff",
    "05_minimal_no_trace_id",
    "06_malformed_mixed",
]


def fixture_path(fixtures_dir: Path, name: str) -> Path:
    return fixtures_dir / "langsmith" / f"{name}.jsonl"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_normalization_snapshot(name, fixtures_dir, assert_snapshot):
    result = langsmith.parse_file(fixture_path(fixtures_dir, name))
    runs = normalize_runs(result.runs)

    assert_snapshot(
        f"langsmith_{name}",
        {
            "report": {
                "format": result.report.format,
                "records_seen": result.report.records_seen,
                "runs_imported": result.report.runs_imported,
                "steps_imported": result.report.steps_imported,
                "errors": [e.spec_dump() for e in result.report.errors],
                "warnings": result.report.warnings,
            },
            "runs": [run.spec_dump() for run in runs],
        },
    )


def test_every_fixture_is_covered(fixtures_dir):
    on_disk = sorted(p.stem for p in (fixtures_dir / "langsmith").glob("*.jsonl"))
    assert on_disk == sorted(FIXTURE_NAMES)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_snapshot_file_is_committed(name):
    path = Path(__file__).parent / "snapshots" / f"langsmith_{name}.json"
    assert path.exists(), f"missing committed snapshot for {name}"


# --- the strict-but-forgiving contract (spec 03 F1) ---------------------------------------------


def test_malformed_file_reports_every_bad_line_and_keeps_the_good_ones(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "06_malformed_mixed"))

    reasons = " | ".join(e.reason for e in result.report.errors)
    assert "invalid JSON" in reasons
    assert "not a JSON object" in reasons
    assert "neither `id` nor `trace_id`" in reasons
    assert "unknown run_type" in reasons

    run_ids = {run.run_id for run in result.runs}
    assert "8e3b6f45-0006-4f66-8b06-ff0000000001" in run_ids
    assert "9f4c7a56-0007-4a77-9c07-aa1000000009" in run_ids


def test_error_locators_point_at_line_numbers(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "06_malformed_mixed"))
    line_errors = [e for e in result.report.errors if e.locator.startswith("line ")]

    assert line_errors, "line-oriented errors must name their line"
    for error in line_errors:
        assert error.locator.removeprefix("line ").isdigit()


def test_unknown_run_type_is_skipped_but_the_run_survives(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "06_malformed_mixed"))
    run = next(r for r in result.runs if r.run_id == "8e3b6f45-0006-4f66-8b06-ff0000000001")

    assert "telepathy" not in {s.meta.get("run_type") for s in run.steps}
    assert [s.kind for s in run.steps] == ["tool", "llm"]


def test_invalid_json_line_never_raises():
    result = langsmith.parse_text('{"broken": ', file_label="broken.jsonl")

    assert result.runs == []
    assert "invalid JSON" in result.report.errors[0].reason


def test_missing_file_is_reported_not_raised(tmp_path):
    result = langsmith.parse_file(tmp_path / "nope.jsonl")

    assert result.runs == []
    assert "could not read file" in result.report.errors[0].reason


# --- run-type mapping and structure -------------------------------------------------------------


def test_root_chain_is_the_run_not_a_step(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "01_clean_reconciliation"))
    (run,) = normalize_runs(result.runs)

    assert [s.kind for s in run.steps] == ["llm", "tool", "tool", "llm"]
    assert "reconciliation_investigator" not in [s.name for s in run.steps]
    assert run.meta["root_name"] == "reconciliation_investigator"
    assert "BNK-20260815-0007" in run.input


def test_nested_chain_is_a_handoff_and_parser_records_are_skipped(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "04_nested_handoff"))
    (run,) = normalize_runs(result.runs)

    handoffs = [s for s in run.steps if s.kind == "handoff"]
    assert [h.name for h in handoffs] == ["accruals_specialist"]
    assert "format_hypotheses" not in [s.name for s in run.steps]
    assert run.meta["skipped_records"] == 1


def test_dotted_order_drives_step_ordering(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "04_nested_handoff"))
    (run,) = normalize_runs(result.runs)

    names = [s.name for s in run.steps]
    # The handoff must precede its own children even though timestamps nearly coincide.
    assert names.index("accruals_specialist") < names.index("get_accrual_schedule")


def test_run_level_error_marks_the_run_failed(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "03_tool_error_run_failed"))
    (run,) = normalize_runs(result.runs)

    assert run.outcome.status == "error"
    assert "503" in run.outcome.error
    assert run.has_error
    failing = next(s for s in run.steps if s.error)
    assert failing.name == "propose_match"


def test_missing_trace_id_falls_back_to_parent_walk(fixtures_dir):
    """Fixture 05 has no `trace_id` anywhere: grouping must still produce two coherent runs."""
    result = langsmith.parse_file(fixture_path(fixtures_dir, "05_minimal_no_trace_id"))
    runs = {r.run_id: r for r in normalize_runs(result.runs)}

    assert len(runs) == 2
    standalone = runs["7d2a5e34-0005-4e55-9a05-ee0000000001"]
    assert [s.kind for s in standalone.steps] == ["llm"]

    # The chain's two children were grouped under the chain, not split into their own runs.
    grouped = runs["7d2a5e34-0005-4e55-9a05-ee0000000002"]
    assert [s.kind for s in grouped.steps] == ["tool", "llm"]


def test_whole_file_json_array_is_accepted():
    text = (
        '[{"id":"a","trace_id":"t","run_type":"llm","name":"ChatOpenAI",'
        '"start_time":"2026-08-15T00:00:00Z","end_time":"2026-08-15T00:00:01Z",'
        '"inputs":{"messages":[{"role":"user","content":"hi"}]},'
        '"outputs":{"generations":[{"text":"hello"}]}}]'
    )
    result = langsmith.parse_text(text, file_label="array.json")
    (run,) = normalize_runs(result.runs)

    assert run.steps[0].kind == "llm"
    assert run.steps[0].output_preview == "hello"


def test_latency_from_iso_timestamps(fixtures_dir):
    result = langsmith.parse_file(fixture_path(fixtures_dir, "01_clean_reconciliation"))
    (run,) = normalize_runs(result.runs)

    # 08:15:00.180 -> 08:15:01.740 = 1560 ms
    assert run.steps[0].latency == pytest.approx(1560.0)
    assert run.duration == pytest.approx(5812.0)


def test_format_sniffing_prefers_content_over_extension(fixtures_dir):
    text = fixture_path(fixtures_dir, "01_clean_reconciliation").read_text(encoding="utf-8")
    assert sniff_format(text, "mislabelled.json") == "langsmith"
