"""Subcommand bodies for the `t2e` CLI.

Exit codes are chosen for CI: 0 success, 1 a real failure (unreadable file, nothing importable,
empty store), 2 bad usage. `t2e stats` failing on an empty store is deliberate - a green CI step
that measured nothing is worse than a red one.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from pathlib import Path

from t2e import store
from t2e.config import Settings, get_settings, set_settings
from t2e.schemas import ParseReport

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def _apply_db_override(args: argparse.Namespace) -> Settings:
    """`--db` must take effect before anything touches the engine."""
    db = getattr(args, "db", None)
    if db:
        store.reset_engine()
        set_settings(Settings(db_path=Path(db)))
    return get_settings()


# --- import -------------------------------------------------------------------------------------


def _render_report(report: ParseReport) -> str:
    lines: list[str] = []
    status = "ok " if report.runs_imported else "-- "
    lines.append(
        f"{status}{report.file}  [{report.format}]  "
        f"{report.runs_imported} run(s), {report.steps_imported} step(s), "
        f"{len(report.errors)} record error(s)"
    )
    if report.redactions:
        lines.append(f"     redacted {report.redactions} value(s): {', '.join(report.pii_flags)}")
    elif report.pii_flags:
        lines.append(f"     PII-lookalike detected: {', '.join(report.pii_flags)}")
    for warning in report.warnings:
        lines.append(f"     warning: {warning}")
    for error in report.errors:
        lines.append(f"     error at {error.locator}: {error.reason}")
    return "\n".join(lines)


def cmd_import(args: argparse.Namespace) -> int:
    _apply_db_override(args)
    from t2e.ingest import ingest_paths

    reports = ingest_paths(args.path, fmt=args.format, redact=not args.no_redact)

    if not reports:
        print("t2e import: no importable files found (looked for .json, .jsonl, .ndjson)")
        return EXIT_FAIL

    if args.json:
        print(json.dumps([r.model_dump() for r in reports], indent=2, default=str))
    else:
        for report in reports:
            print(_render_report(report))

        total_runs = sum(r.runs_imported for r in reports)
        total_errors = sum(len(r.errors) for r in reports)
        total_redactions = sum(r.redactions for r in reports)
        flags = sorted({flag for r in reports for flag in r.pii_flags})

        print()
        print(
            f"imported {total_runs} run(s) from {len(reports)} file(s); "
            f"{total_errors} record error(s); {total_redactions} redaction(s)"
        )
        if flags:
            # The CLI equivalent of the UI's warning banner (spec 03 sec 11).
            disposition = (
                "Redaction was DISABLED."
                if args.no_redact
                else "Values were redacted on import."
            )
            print(
                f"WARNING: payloads looked like PII ({', '.join(flags)}). {disposition}"
            )
        if total_runs:
            print("next: t2e label --serve")

    return EXIT_OK if any(r.runs_imported for r in reports) else EXIT_FAIL


# --- label --serve ------------------------------------------------------------------------------


def cmd_label(args: argparse.Namespace) -> int:
    settings = _apply_db_override(args)

    if not args.serve:
        print("t2e label: --serve is the only mode in v1. Try `t2e label --serve`.")
        return EXIT_USAGE

    import uvicorn

    from t2e.api.app import WEB_DIR, create_app

    host = args.host or settings.host
    port = args.port or settings.port
    url = f"http://{host}:{port}/"

    with store.session_scope() as session:
        total = store.count_runs(session)
        unlabeled = store.count_runs(session, labeled=False)

    print(f"t2e label --serve   {url}")
    print(f"  database   {settings.resolved_db_path()}")
    print(f"  runs       {total} ({unlabeled} unlabeled)")
    if not WEB_DIR.is_dir():
        print("  UI         NOT BUILT - run `npm --prefix frontend install && "
              "npm --prefix frontend run build`")
        print("             the API is still available at /api (docs at /api/docs)")
    else:
        print("  UI         built")
    if total == 0:
        print("  hint       nothing to label yet: `t2e import <file>` first")
    print("  privacy    local-only; no telemetry, no outbound requests")
    print()

    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")
    return EXIT_OK


# --- export -------------------------------------------------------------------------------------


def cmd_export(args: argparse.Namespace) -> int:
    _apply_db_override(args)
    from t2e import exporters

    try:
        formats = exporters.parse_formats(args.format)
    except ValueError as exc:
        print(f"t2e export: {exc}", file=sys.stderr)
        return EXIT_USAGE

    with store.session_scope() as session:
        cases = store.list_cases(session, version=args.case_version)
        if not cases:
            available = sorted({row.version for row in store.list_cases(session)})
            print(
                f"t2e export: no cases at version {args.case_version!r}."
                + (f" Available: {', '.join(available)}" if available else " No cases exist yet."),
                file=sys.stderr,
            )
            return EXIT_FAIL

        result = exporters.write(
            cases, version=args.case_version, formats=formats, out_dir=args.out
        )
        store.record_export_version(
            session,
            version=args.case_version,
            case_count=len(cases),
            notes=args.notes,
        )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"exported {result['case_count']} case(s) at {args.case_version} -> {result['out_dir']}")
        for entry in result["files"]:
            print(f"  {entry['file']}  ({entry['bytes']} bytes)")
        if "pytest" in formats:
            print()
            print("the generated suite needs an agent adapter before it can run:")
            print("  see the docstring at the top of test_cases.py for the conftest.py to add")

    return EXIT_OK


def cmd_stats(args: argparse.Namespace) -> int:
    _apply_db_override(args)
    from t2e import stats as stats_module

    with store.session_scope() as session:
        stats = stats_module.collect(session)

    if args.json:
        print(json.dumps(stats.to_dict(), indent=2))
    else:
        print(stats_module.render_text(stats))

    if stats.runs_total == 0:
        print("\nno runs in the store: `t2e import <file>` first", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK
