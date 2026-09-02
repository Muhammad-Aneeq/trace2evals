"""The CLI surface from spec 03 F6, with the exit codes CI depends on.

`main(argv)` is called directly rather than through a subprocess: it is faster, and the exit code and
stdout are exactly what a shell would see.
"""

from __future__ import annotations

import json

import pytest

from t2e import store
from t2e.cli import build_parser, main


@pytest.fixture
def cli(db, tmp_path, monkeypatch):
    """Run CLI commands against a temp database, from a temp working directory."""
    monkeypatch.chdir(tmp_path)

    def run(*argv: str) -> int:
        return main(["--db", str(db.db_path), *argv])

    return run


# --- the argument surface -----------------------------------------------------------------------


def test_all_four_commands_exist():
    """spec 03 F6: t2e import <file>, t2e label --serve, t2e export --version vN, t2e stats."""
    parser = build_parser()
    actions = [action for action in parser._actions if action.dest == "command"]
    assert set(actions[0].choices) == {"import", "label", "export", "stats"}


def test_no_command_prints_help_and_exits_2(capsys):
    assert main([]) == 2
    assert "t2e import" in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert "t2e" in capsys.readouterr().out


def test_export_requires_a_version():
    with pytest.raises(SystemExit) as excinfo:
        main(["export"])
    assert excinfo.value.code == 2


# --- t2e import ---------------------------------------------------------------------------------


def test_import_a_directory_reports_per_file(cli, capsys, fixtures_dir):
    assert cli("import", str(fixtures_dir / "otel")) == 0

    out = capsys.readouterr().out
    assert "01_clean_reconciliation.json" in out
    assert "imported 8 run(s) from 6 file(s)" in out
    # Malformed records are reported, not swallowed.
    assert "record error(s)" in out
    assert "next: t2e label --serve" in out


def test_import_warns_about_pii_and_says_what_it_did(cli, capsys, fixtures_dir):
    cli("import", str(fixtures_dir / "otel" / "02_tool_heavy_with_pii.json"))

    out = capsys.readouterr().out
    assert "redacted 5 value(s)" in out
    assert "WARNING: payloads looked like PII" in out
    assert "Values were redacted on import." in out


def test_import_with_no_redact_says_redaction_was_disabled(cli, capsys, fixtures_dir):
    cli("import", str(fixtures_dir / "otel" / "02_tool_heavy_with_pii.json"), "--no-redact")

    out = capsys.readouterr().out
    assert "Redaction was DISABLED." in out


def test_import_json_output_is_machine_readable(cli, capsys, fixtures_dir):
    cli("import", str(fixtures_dir / "langsmith" / "01_clean_reconciliation.jsonl"), "--json")

    reports = json.loads(capsys.readouterr().out)
    assert reports[0]["format"] == "langsmith"
    assert reports[0]["runs_imported"] == 1


def test_import_of_an_unreadable_path_exits_nonzero(cli, capsys):
    assert cli("import", "does_not_exist.json") == 1
    assert "could not read file" in capsys.readouterr().out


def test_import_with_an_explicit_format(cli, capsys, fixtures_dir):
    assert cli(
        "import", str(fixtures_dir / "langsmith" / "01_clean_reconciliation.jsonl"),
        "--format", "langsmith",
    ) == 0
    assert "[langsmith]" in capsys.readouterr().out


def test_forcing_the_wrong_format_fails_rather_than_importing_nonsense(cli, capsys, fixtures_dir):
    assert cli(
        "import", str(fixtures_dir / "otel" / "01_clean_reconciliation.json"),
        "--format", "langsmith",
    ) == 1


# --- t2e stats ----------------------------------------------------------------------------------


def test_stats_on_an_empty_store_exits_nonzero(cli, capsys):
    """A green CI step that measured nothing is worse than a red one."""
    assert cli("stats") == 1
    captured = capsys.readouterr()
    assert "no runs in the store" in captured.err


def test_stats_prints_a_greppable_report(cli, capsys, fixtures_dir):
    cli("import", str(fixtures_dir / "otel"))
    capsys.readouterr()

    assert cli("stats") == 0
    out = capsys.readouterr().out

    assert "runs                 8" in out
    assert "unlabeled            8" in out
    assert "verdicts" in out
    assert "failure tags" in out
    assert "(none recorded)" in out
    assert "no timed labels yet" in out


def test_stats_reports_the_distribution_and_speed_once_labeled(cli, capsys, fixtures_dir, db):
    cli("import", str(fixtures_dir / "otel"))
    capsys.readouterr()

    with store.session_scope() as session:
        runs = store.list_runs(session)
        store.set_label(session, runs[0].id, verdict="right", seconds_spent=4.0)
        store.set_label(
            session, runs[1].id, verdict="wrong", tags=["wrong_tool"], seconds_spent=8.0
        )

    assert cli("stats") == 0
    out = capsys.readouterr().out

    assert "labeled              2" in out
    assert "wrong_tool" in out
    assert "median             6.0s  (PASS)" in out
    assert "target             <10.0s median" in out


def test_stats_json_output(cli, capsys, fixtures_dir):
    cli("import", str(fixtures_dir / "otel"))
    capsys.readouterr()

    assert cli("stats", "--json") == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["runs_total"] == 8
    assert payload["target_median_seconds"] == 10.0
    assert payload["meets_speed_target"] is None, "nothing timed yet, so nothing proven"


# --- t2e export ---------------------------------------------------------------------------------


def _seed_a_case(db, fixtures_dir):
    from t2e.casebuilder import suggest_expectations, suggest_tags
    from t2e.ingest import ingest_paths

    ingest_paths([fixtures_dir / "otel" / "03_tool_error_no_escalation.json"])
    with store.session_scope() as session:
        run_row = store.list_runs(session)[0]
        store.set_label(
            session, run_row.id, verdict="wrong", tags=["no_escalation"], seconds_spent=7.0
        )
        run = store.run_row_to_trace_run(run_row)
        store.create_case(
            session,
            version="v1",
            run_id=run.run_id,
            input_value=run.input,
            expectations=suggest_expectations(run, "wrong", ["no_escalation"]),
            tags=suggest_tags(run, ["no_escalation"]),
        )


def test_export_writes_the_files_and_explains_the_next_step(cli, capsys, fixtures_dir, db, tmp_path):
    _seed_a_case(db, fixtures_dir)

    assert cli("export", "--version", "v1", "--out", str(tmp_path / "out")) == 0
    out = capsys.readouterr().out

    assert "exported 1 case(s) at v1" in out
    assert "cases.jsonl" in out
    assert "test_cases.py" in out
    # The stub cannot run without an adapter, and the CLI has to say so.
    assert "needs an agent adapter" in out

    assert (tmp_path / "out" / "cases.jsonl").is_file()
    assert (tmp_path / "out" / "test_cases.py").is_file()


def test_export_of_an_unknown_version_exits_nonzero(cli, capsys, fixtures_dir, db, tmp_path):
    _seed_a_case(db, fixtures_dir)

    assert cli("export", "--version", "v9", "--out", str(tmp_path / "out")) == 1
    err = capsys.readouterr().err
    assert "no cases at version 'v9'" in err
    assert "Available: v1" in err


def test_export_with_no_cases_at_all_says_so(cli, capsys, tmp_path):
    assert cli("export", "--version", "v1", "--out", str(tmp_path / "out")) == 1
    assert "No cases exist yet." in capsys.readouterr().err


def test_export_rejects_an_unknown_format(cli, capsys, tmp_path):
    assert cli("export", "--version", "v1", "--format", "parquet", "--out", str(tmp_path)) == 2
    assert "unknown export format" in capsys.readouterr().err


def test_export_json_manifest(cli, capsys, fixtures_dir, db, tmp_path):
    _seed_a_case(db, fixtures_dir)

    assert cli("export", "--version", "v1", "--out", str(tmp_path / "out"), "--json") == 0
    manifest = json.loads(capsys.readouterr().out)

    assert manifest["case_count"] == 1
    assert manifest["formats"] == ["jsonl", "pytest"]
    assert len(manifest["files"]) == 2


def test_export_promptfoo_only_still_needs_no_cases_file(cli, capsys, fixtures_dir, db, tmp_path):
    _seed_a_case(db, fixtures_dir)

    assert cli(
        "export", "--version", "v1", "--format", "promptfoo", "--out", str(tmp_path / "pf")
    ) == 0
    assert (tmp_path / "pf" / "promptfooconfig.yaml").is_file()
    assert not (tmp_path / "pf" / "cases.jsonl").exists()


# --- t2e label ----------------------------------------------------------------------------------


def test_label_without_serve_is_a_usage_error(cli, capsys):
    assert cli("label") == 2
    assert "--serve is the only mode" in capsys.readouterr().out
