"""Export snapshot tests against golden files (spec 03 sec 10).

A deterministic fixture set is built by hand rather than taken from the live store, because a golden
file that depends on `created_at` or an autoincrement id would churn on every run and stop being a
useful signal.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import yaml

from t2e import CASE_SCHEMA_VERSION, exporters, store
from t2e.exporters import cases_jsonl, promptfoo, pytest_stub
from t2e.models import Case

FIXED_TIME = datetime(2026, 8, 20, 14, 30, tzinfo=UTC)


def make_case(case_id: int, *, run_id: str | None, expectations, tags, input_text: str) -> Case:
    """A detached ORM instance with pinned id and timestamp, so goldens stay byte-stable."""
    return Case(
        id=case_id,
        version="v1",
        run_id=run_id,
        input_json=store.dumps(input_text),
        expectations_json=store.dumps(expectations),
        tags_json=store.dumps(tags),
        created_at=FIXED_TIME,
    )


@pytest.fixture
def cases() -> list[Case]:
    """Five cases covering all five assertion kinds, plus a manual case with no run."""
    return [
        make_case(
            1,
            run_id="4f2a9c1e8b7d6a5f3e2d1c0b9a8f7e6d",
            input_text=(
                "Bank transaction BNK-20260814-0042 for 4,812.50 GBP has no matching GL entry. "
                "Investigate and propose a root cause with evidence."
            ),
            expectations=[
                {
                    "kind": "must_call_tool",
                    "tool": "get_invoice",
                    "note": "the run was tagged wrong_tool: name the tool the agent should have called",
                },
                {"kind": "must_cite", "min_count": 1, "note": "tagged ungrounded"},
            ],
            tags=["wrong_tool", "ungrounded", "source:otel"],
        ),
        make_case(
            2,
            run_id="9e4b7d2c6a1f5e8b3d0c9a2f7e4b1d6c",
            input_text=(
                "Transaction BNK-20260814-0067 for 19,400.00 USD references PO-99001, "
                "which does not exist in the ledger. Investigate."
            ),
            expectations=[
                {
                    "kind": "must_escalate",
                    "note": "tagged no_escalation: the agent must hand off instead of guessing",
                },
                {
                    "kind": "must_cite",
                    "sources": ["PO-99001"],
                    "note": "tagged hallucinated_fact",
                },
            ],
            tags=["no_escalation", "hallucinated_fact", "had_error", "source:otel"],
        ),
        make_case(
            3,
            run_id="5b0e3c12-0003-4c33-9e03-cc0000000001",
            input_text="Reconcile the 2026-08 intercompany balance between entity GB01 and entity US04.",
            expectations=[
                {
                    "kind": "output_matches_schema",
                    "schema": {
                        "type": "object",
                        "required": ["root_cause", "evidence"],
                        "properties": {
                            "root_cause": {"type": "string"},
                            "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                        },
                    },
                    "note": "tagged format_break: the consumer parses this as JSON",
                }
            ],
            tags=["format_break", "had_error", "source:langsmith"],
        ),
        make_case(
            4,
            run_id="6c1f4d23-0004-4d44-8f04-dd0000000001",
            input_text=(
                "Accrual reversal AC-2026-0311 for 4,120.00 GBP did not reverse in 2026-08. "
                "Route to the right specialist and resolve."
            ),
            expectations=[
                {
                    "kind": "output_matches_regex",
                    "pattern": r"\bSCHED-1188\b",
                    "note": "regression guard: the schedule id must appear",
                },
                {
                    "kind": "must_call_tool",
                    "tool": "flag_exception",
                    "note": "regression guard: this correct run escalated",
                },
            ],
            tags=["source:langsmith", "multi_agent"],
        ),
        make_case(
            5,
            run_id=None,
            input_text="A hand-written case: a 3.00 GBP variance below the 100.00 materiality threshold.",
            expectations=[
                {
                    "kind": "output_matches_regex",
                    "pattern": "(?i)below the .*threshold",
                    "flags": "",
                    "note": "written by hand, not derived from a trace",
                }
            ],
            tags=["manual", "materiality"],
        ),
    ]


# --- cases.jsonl --------------------------------------------------------------------------------


def test_cases_jsonl_golden(cases, assert_golden):
    assert_golden("cases.jsonl", cases_jsonl.render(cases))


def test_cases_jsonl_records_are_stable_and_versioned(cases):
    records = cases_jsonl.parse(cases_jsonl.render(cases))

    assert len(records) == 5
    assert all(record["schema_version"] == CASE_SCHEMA_VERSION for record in records)
    assert [record["case_id"] for record in records] == [
        "v1-0001",
        "v1-0002",
        "v1-0003",
        "v1-0004",
        "v1-0005",
    ]
    # A manual case has no run id, and that must survive the round trip as null.
    assert records[4]["run_id"] is None


def test_cases_jsonl_round_trips(cases):
    rendered = cases_jsonl.render(cases)
    reparsed = cases_jsonl.parse(rendered)

    assert reparsed[0]["expectations"][0]["tool"] == "get_invoice"
    assert reparsed[2]["expectations"][0]["schema"]["required"] == ["root_cause", "evidence"]


def test_cases_jsonl_ends_with_a_newline(cases):
    """So the file concatenates and diffs cleanly."""
    assert cases_jsonl.render(cases).endswith("\n")


def test_empty_export_is_an_empty_string_not_a_stray_newline():
    assert cases_jsonl.render([]) == ""


def test_parse_rejects_a_malformed_line():
    with pytest.raises(ValueError, match="line 2 is not valid JSON"):
        cases_jsonl.parse('{"case_id": "v1-0001"}\n{broken\n')


def test_parse_rejects_a_non_object_line():
    with pytest.raises(ValueError, match="line 1 is not a JSON object"):
        cases_jsonl.parse('"just a string"\n')


# --- test_cases.py ------------------------------------------------------------------------------


def test_pytest_stub_golden(cases, assert_golden):
    assert_golden("test_cases.py", pytest_stub.render(cases, version="v1"))


def test_pytest_stub_is_syntactically_valid_python(cases):
    import ast

    source = pytest_stub.render(cases, version="v1")
    ast.parse(source)  # raises SyntaxError if the template is broken


def test_pytest_stub_imports_the_shared_helpers(cases):
    """PLAN.md D-008: helpers are imported, not inlined, so they are tested in one place."""
    source = pytest_stub.render(cases, version="v1")

    assert "from t2e.assertions import assert_all, check_all" in source
    assert "def assert_all" not in source, "the helper must not be duplicated into the stub"


def test_pytest_stub_documents_the_adapter_contract(cases):
    source = pytest_stub.render(cases, version="v1")

    assert "run_agent" in source
    assert "conftest.py" in source
    assert "tool_calls" in source


def test_pytest_stub_guards_against_an_empty_suite(cases):
    """An empty suite passing silently is the failure mode that hides regressions."""
    source = pytest_stub.render(cases, version="v1")
    assert "no cases loaded" in source


# --- promptfoo ----------------------------------------------------------------------------------


def test_promptfoo_golden(cases, assert_golden):
    assert_golden("promptfooconfig.yaml", promptfoo.render(cases, version="v1"))


def test_promptfoo_is_valid_yaml_with_one_test_per_case(cases):
    config = yaml.safe_load(promptfoo.render(cases, version="v1"))

    assert len(config["tests"]) == 5
    assert config["tests"][0]["description"] == "v1-0001"
    assert config["tests"][0]["vars"]["input"].startswith("Bank transaction")


def test_promptfoo_maps_the_exact_equivalents(cases):
    config = yaml.safe_load(promptfoo.render(cases, version="v1"))
    by_id = {test["description"]: test for test in config["tests"]}

    # regex -> regex
    regex_assert = next(a for a in by_id["v1-0004"]["assert"] if a["type"] == "regex")
    assert regex_assert["value"] == r"\bSCHED-1188\b"

    # schema -> is-json with the schema attached
    json_assert = next(a for a in by_id["v1-0003"]["assert"] if a["type"] == "is-json")
    assert json_assert["value"]["required"] == ["root_cause", "evidence"]

    # pinned citations -> icontains-all
    contains = next(a for a in by_id["v1-0002"]["assert"] if a["type"] == "icontains-all")
    assert contains["value"] == ["PO-99001"]


def test_promptfoo_states_its_own_weakness(cases):
    """must_call_tool/must_escalate are weaker here; the file has to say so."""
    rendered = promptfoo.render(cases, version="v1")

    assert "CAVEAT" in rendered
    assert "does not see the agent's tool trace" in rendered
    assert "not as the authoritative eval gate" in rendered


def test_promptfoo_leaves_providers_for_the_user(cases):
    config = yaml.safe_load(promptfoo.render(cases, version="v1"))
    assert config["providers"] == []


# --- the format registry ------------------------------------------------------------------------


def test_parse_formats_normalises_and_deduplicates():
    assert exporters.parse_formats("pytest,jsonl") == ["jsonl", "pytest"]
    assert exporters.parse_formats("JSONL, jsonl ") == ["jsonl"]


def test_parse_formats_rejects_the_unknown():
    with pytest.raises(ValueError, match="unknown export format"):
        exporters.parse_formats("jsonl,parquet")
    with pytest.raises(ValueError, match="no formats requested"):
        exporters.parse_formats("  ")


def test_requesting_pytest_also_writes_the_cases_it_needs(cases):
    """A stub without its cases is inert, so the JSONL is implied."""
    rendered = exporters.render(cases, version="v1", formats=["pytest"])

    assert set(rendered) == {"cases.jsonl", "test_cases.py"}


def test_write_puts_every_requested_format_on_disk(cases, tmp_path):
    result = exporters.write(
        cases, version="v1", formats=["jsonl", "pytest", "promptfoo"], out_dir=tmp_path / "out"
    )

    assert result["case_count"] == 5
    written = {entry["file"].rsplit("\\")[-1].rsplit("/")[-1] for entry in result["files"]}
    assert written == {"cases.jsonl", "test_cases.py", "promptfooconfig.yaml"}
    for entry in result["files"]:
        from pathlib import Path

        assert Path(entry["file"]).is_file()
        assert entry["bytes"] > 0


def test_write_uses_lf_newlines_so_goldens_match_across_platforms(cases, tmp_path):
    exporters.write(cases, version="v1", formats=["jsonl"], out_dir=tmp_path)
    raw = (tmp_path / "cases.jsonl").read_bytes()

    assert b"\r\n" not in raw
