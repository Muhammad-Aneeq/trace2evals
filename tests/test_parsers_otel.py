"""OpenTelemetry importer: snapshot-tested normalization, plus the malformed-record contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from t2e.normalizer import normalize_runs
from t2e.parsers import otel, sniff_format

FIXTURE_NAMES = [
    "01_clean_reconciliation",
    "02_tool_heavy_with_pii",
    "03_tool_error_no_escalation",
    "04_handoff_two_traces",
    "05_minimal_flat_events",
    "06_malformed_mixed",
]


def fixture_path(fixtures_dir: Path, name: str) -> Path:
    return fixtures_dir / "otel" / f"{name}.json"


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_normalization_snapshot(name, fixtures_dir, assert_snapshot):
    """The F2 shape of every fixture is frozen. `spec_dump` emits only the contract fields."""
    result = otel.parse_file(fixture_path(fixtures_dir, name))
    runs = normalize_runs(result.runs)

    assert_snapshot(
        f"otel_{name}",
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
    """Guards against a fixture being added without a snapshot: the list above must be complete."""
    on_disk = sorted(p.stem for p in (fixtures_dir / "otel").glob("*.json"))
    assert on_disk == sorted(FIXTURE_NAMES)


@pytest.mark.parametrize("name", FIXTURE_NAMES)
def test_snapshot_file_is_committed(name):
    path = Path(__file__).parent / "snapshots" / f"otel_{name}.json"
    assert path.exists(), f"missing committed snapshot for {name}"


# --- the strict-but-forgiving contract (spec 03 F1) ---------------------------------------------


def test_malformed_file_reports_errors_and_still_imports_good_records(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "06_malformed_mixed"))

    assert result.report.errors, "malformed records must be reported"
    assert result.runs, "good records in a damaged file must still import"

    reasons = " | ".join(e.reason for e in result.report.errors)
    assert "not a JSON object" in reasons
    assert "scopeSpans" in reasons

    # The intact trace survived in full.
    by_id = {run.run_id: run for run in result.runs}
    good = by_id["aaaa1111bbbb2222cccc3333dddd4444"]
    assert [s.kind for s in good.steps] == ["tool"]
    assert good.steps[0].name == "get_invoice"


def test_unparseable_timestamps_do_not_drop_the_span(fixtures_dir):
    """A span with a broken timestamp still imports; latency is simply unknown."""
    result = otel.parse_file(fixture_path(fixtures_dir, "06_malformed_mixed"))
    runs = normalize_runs(result.runs)
    run = next(r for r in runs if r.run_id == "eeee5555ffff6666aaaa7777bbbb8888")

    assert run.started is None
    assert run.steps[0].latency is None
    assert "Write off" in run.steps[0].args_preview


def test_infrastructure_only_trace_is_reported_not_imported(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "06_malformed_mixed"))

    assert "cccc9999dddd0000eeee1111ffff2222" not in {r.run_id for r in result.runs}
    assert any("no GenAI spans" in e.reason for e in result.report.errors)


def test_invalid_json_is_reported_and_never_raises():
    result = otel.parse_text("{not json at all", file_label="broken.json")

    assert result.runs == []
    assert len(result.report.errors) == 1
    assert "not valid JSON" in result.report.errors[0].reason


def test_missing_file_is_reported_not_raised(tmp_path):
    result = otel.parse_file(tmp_path / "does_not_exist.json")

    assert result.runs == []
    assert "could not read file" in result.report.errors[0].reason


# --- GenAI semantic-convention awareness --------------------------------------------------------


def test_step_kinds_and_model_names(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "01_clean_reconciliation"))
    (run,) = normalize_runs(result.runs)

    # The root `invoke_agent` span is the run, not a step.
    assert [s.kind for s in run.steps] == ["llm", "tool", "tool", "llm"]
    assert [s.name for s in run.steps] == [
        "gpt-4o-mini",
        "search_counterparty",
        "get_invoice",
        "gpt-4o-mini",
    ]
    assert run.meta["service"] == "exception-workbench"
    assert run.outcome.status == "success"


def test_nested_invoke_agent_is_a_handoff(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "04_handoff_two_traces"))
    runs = {r.run_id: r for r in normalize_runs(result.runs)}
    run = runs["1a2b3c4d5e6f70819a2b3c4d5e6f7081"]

    kinds = [s.kind for s in run.steps]
    assert "handoff" in kinds
    handoff = next(s for s in run.steps if s.kind == "handoff")
    assert handoff.name == "fx_specialist"


def test_two_traces_in_one_file_become_two_runs(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "04_handoff_two_traces"))
    assert len(result.runs) == 2
    assert result.report.runs_imported == 2


def test_span_status_error_and_exception_event_become_step_error(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "03_tool_error_no_escalation"))
    (run,) = normalize_runs(result.runs)

    failing = next(s for s in run.steps if s.error)
    assert failing.name == "get_invoice"
    # The exception event carries the better message, so it wins over status.message.
    assert "no invoice with id PO-99001" in failing.error
    assert run.has_error


def test_flat_shape_and_event_carried_payloads(fixtures_dir):
    """`{"spans": [...]}`, snake_case keys, and prompts delivered as span events."""
    result = otel.parse_file(fixture_path(fixtures_dir, "05_minimal_flat_events"))
    (run,) = normalize_runs(result.runs)

    assert len(run.steps) == 1
    step = run.steps[0]
    assert step.kind == "llm"
    assert "materiality threshold" in step.args_preview
    assert "auto-write-off" in step.output_preview
    assert step.latency == pytest.approx(2310.0)


def test_latency_is_milliseconds(fixtures_dir):
    result = otel.parse_file(fixture_path(fixtures_dir, "01_clean_reconciliation"))
    (run,) = normalize_runs(result.runs)

    # First llm span: 1786698900.14 -> 1786698901.76 = 1620 ms
    assert run.steps[0].latency == pytest.approx(1620.0)
    assert run.duration == pytest.approx(6480.0)


def test_dict_style_attributes_are_accepted():
    """Some exporters emit attributes as a plain object rather than an OTLP key/value list."""
    doc = """
    {"spans": [{"traceId": "t1", "spanId": "s1", "name": "chat gpt-4o",
      "startTimeUnixNano": "1786698900000000000", "endTimeUnixNano": "1786698901000000000",
      "attributes": {"gen_ai.operation.name": "chat", "gen_ai.request.model": "gpt-4o",
                     "gen_ai.prompt": "hello", "gen_ai.completion": "hi"}}]}
    """
    result = otel.parse_text(doc, file_label="dict_attrs.json")
    (run,) = normalize_runs(result.runs)

    assert run.steps[0].name == "gpt-4o"
    assert run.steps[0].args_preview == "hello"


def test_otlp_any_value_decoding():
    assert otel.decode_any_value({"stringValue": "x"}) == "x"
    assert otel.decode_any_value({"intValue": "42"}) == 42
    assert otel.decode_any_value({"doubleValue": 1.5}) == 1.5
    assert otel.decode_any_value({"boolValue": True}) is True
    assert otel.decode_any_value({"arrayValue": {"values": [{"stringValue": "a"}]}}) == ["a"]
    assert otel.decode_any_value(
        {"kvlistValue": {"values": [{"key": "k", "value": {"intValue": "7"}}]}}
    ) == {"k": 7}


def test_format_sniffing_prefers_content_over_extension(fixtures_dir):
    text = fixture_path(fixtures_dir, "01_clean_reconciliation").read_text(encoding="utf-8")
    assert sniff_format(text, "mislabelled.jsonl") == "otel"
