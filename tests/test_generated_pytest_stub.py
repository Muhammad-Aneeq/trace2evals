"""Proof that the generated pytest stub actually runs.

Spec 03 F5 promises "a generated `test_cases.py` pytest stub (assertion helpers included)". A golden
file only proves the text is stable; it does not prove the file *works*. So these tests write the stub
and its cases into a temp directory, add a `conftest.py` with a fake agent adapter, and run pytest on
it in a subprocess - the same thing a user would do.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from t2e import exporters, store
from t2e.models import Case

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = REPO_ROOT / "backend" / "src"

FIXED_TIME = datetime(2026, 8, 20, 14, 30, tzinfo=UTC)


def make_case(case_id: int, input_text: str, expectations: list[dict]) -> Case:
    return Case(
        id=case_id,
        version="v1",
        run_id=f"run-{case_id}",
        input_json=store.dumps(input_text),
        expectations_json=store.dumps(expectations),
        tags_json=store.dumps(["generated-suite-test"]),
        created_at=FIXED_TIME,
    )


#: One case per assertion kind, so a green run exercises all five.
SUITE = [
    make_case(
        1,
        "tool-case",
        [{"kind": "must_call_tool", "tool": "get_invoice"}],
    ),
    make_case(2, "escalate-case", [{"kind": "must_escalate"}]),
    make_case(3, "cite-case", [{"kind": "must_cite", "sources": ["INV-2026-0881"]}]),
    make_case(
        4,
        "regex-case",
        [{"kind": "output_matches_regex", "pattern": r"partial payment"}],
    ),
    make_case(
        5,
        "schema-case",
        [
            {
                "kind": "output_matches_schema",
                "schema": {"type": "object", "required": ["root_cause"]},
            }
        ],
    ),
]

#: A conftest whose adapter answers each case correctly. This is the shape a user writes.
GOOD_CONFTEST = '''
import pytest


@pytest.fixture
def run_agent():
    def _run(case_input: str):
        if case_input == "tool-case":
            return {"output": "found it", "tool_calls": ["search_counterparty", "get_invoice"]}
        if case_input == "escalate-case":
            return {"output": "handing off", "escalated": True}
        if case_input == "cite-case":
            return {"output": "Evidence: INV-2026-0881, GL-88213."}
        if case_input == "regex-case":
            return "Root cause: partial payment against INV-2026-0881."
        if case_input == "schema-case":
            return '{"root_cause": "partial_payment", "evidence": ["INV-2026-0881"]}'
        raise AssertionError(f"unexpected case input: {case_input!r}")

    return _run
'''

#: An adapter that gets everything wrong, to prove the suite can actually fail.
BAD_CONFTEST = '''
import pytest


@pytest.fixture
def run_agent():
    def _run(case_input: str):
        # Confident, ungrounded, no tools, no escalation, not JSON: every assertion should fail.
        return {"output": "It was definitely a duplicate.", "tool_calls": [], "escalated": False}

    return _run
'''


def write_suite(directory: Path, conftest: str | None, cases: list[Case] | None = None) -> None:
    exporters.write(
        cases if cases is not None else SUITE,
        version="v1",
        formats=["jsonl", "pytest"],
        out_dir=directory,
    )
    if conftest is not None:
        (directory / "conftest.py").write_text(conftest, encoding="utf-8")


def run_pytest(directory: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """Run pytest in a subprocess so the generated suite is exercised exactly as a user would."""
    env = {
        **dict(__import__("os").environ),
        # `t2e` is installed in this venv, but be explicit so the test does not depend on that.
        "PYTHONPATH": str(BACKEND_SRC),
        "PYTHONIOENCODING": "utf-8",
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", *extra, str(directory)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(directory),
        timeout=300,
    )


def test_generated_suite_passes_with_a_correct_adapter(tmp_path):
    write_suite(tmp_path, GOOD_CONFTEST)

    result = run_pytest(tmp_path)

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    # 5 parametrized expectation checks + 5 agent checks + the versioning guard + the summary.
    assert "12 passed" in result.stdout, result.stdout


def test_generated_suite_fails_loudly_with_a_broken_agent(tmp_path):
    """A suite that cannot fail is not an eval suite."""
    write_suite(tmp_path, BAD_CONFTEST)

    result = run_pytest(tmp_path)

    assert result.returncode != 0
    # Every assertion kind should be named in the failure output.
    for kind in (
        "must_call_tool",
        "must_escalate",
        "must_cite",
        "output_matches_regex",
        "output_matches_schema",
    ):
        assert kind in result.stdout, f"{kind} missing from failure output:\n{result.stdout}"


def test_generated_suite_skips_cleanly_without_an_adapter(tmp_path):
    """No `run_agent` fixture: the suite must explain itself, not crash confusingly."""
    write_suite(tmp_path, conftest=None)

    result = run_pytest(tmp_path)

    # The structural tests still pass; the agent tests error on the missing fixture.
    assert "run_agent" in result.stdout
    assert "fixture 'run_agent' not found" in result.stdout


def test_failure_message_names_the_case_and_lists_every_failure(tmp_path):
    write_suite(
        tmp_path,
        BAD_CONFTEST,
        cases=[
            make_case(
                7,
                "multi-fail",
                [
                    {"kind": "must_call_tool", "tool": "get_invoice"},
                    {"kind": "must_cite", "min_count": 1},
                    {"kind": "must_escalate"},
                ],
            )
        ],
    )

    result = run_pytest(tmp_path, "-k", "test_agent_meets_expectations")

    assert "case v1-0007" in result.stdout
    assert "3 of 3 expectation(s) failed" in result.stdout


def test_generated_suite_refuses_to_run_empty(tmp_path):
    """An empty suite passing green is the failure mode that silently hides regressions."""
    from t2e.exporters import cases_jsonl, pytest_stub

    (tmp_path / cases_jsonl.FILENAME).write_text("", encoding="utf-8")
    (tmp_path / pytest_stub.FILENAME).write_text(
        pytest_stub.render([], version="v1"), encoding="utf-8"
    )
    (tmp_path / "conftest.py").write_text(GOOD_CONFTEST, encoding="utf-8")

    result = run_pytest(tmp_path)

    assert result.returncode != 0
    assert "no cases loaded" in result.stdout


def test_generated_suite_rejects_a_foreign_schema_version(tmp_path):
    """A case file from a different t2e must be re-exported, not silently mis-evaluated."""
    write_suite(tmp_path, GOOD_CONFTEST)

    path = tmp_path / "cases.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    for record in records:
        record["schema_version"] = 999
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n", encoding="utf-8"
    )

    result = run_pytest(tmp_path, "-k", "versioned")

    assert result.returncode != 0
    assert "different schema version" in result.stdout


@pytest.mark.parametrize("filename", ["cases.jsonl", "test_cases.py"])
def test_export_produces_both_files_side_by_side(tmp_path, filename):
    write_suite(tmp_path, GOOD_CONFTEST)
    assert (tmp_path / filename).is_file()
