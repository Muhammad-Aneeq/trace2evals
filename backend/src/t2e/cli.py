"""The `t2e` command line: import, label --serve, export, stats.

Kept dependency-free (argparse from the stdlib) so the CLI starts fast and installs anywhere.
Subcommand bodies live in `t2e.cli_commands`; this module owns only the argument surface.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from t2e import __version__

FAILURE_TAGS = (
    "wrong_tool",
    "bad_args",
    "ungrounded",
    "no_escalation",
    "format_break",
    "hallucinated_fact",
    "other",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="t2e",
        description=(
            "Trace2Evals - turn agent traces into versioned eval cases you own. "
            "Runs fully offline: no LLM calls, no telemetry."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  t2e import fixtures/otel/clean_run.json\n"
            "  t2e import fixtures/langsmith/ --format langsmith\n"
            "  t2e label --serve\n"
            "  t2e export --version v1 --format jsonl,pytest\n"
            "  t2e stats --json\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"t2e {__version__}")
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="SQLite database path (default: ./.t2e/t2e.db)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # t2e import <file>
    p_import = sub.add_parser(
        "import",
        help="import a trace file or directory into the local store",
        description="Import OpenTelemetry JSON or LangSmith JSONL traces. "
        "Parsing is strict-but-forgiving: bad records are reported, good records still import.",
    )
    p_import.add_argument("path", nargs="+", help="trace file(s) or directory to import")
    p_import.add_argument(
        "--format",
        choices=("auto", "otel", "langsmith"),
        default="auto",
        help="input format (default: auto-sniff by extension and shape)",
    )
    p_import.add_argument(
        "--no-redact",
        action="store_true",
        help="skip the redaction pass (default: redact PII-lookalike payloads on import)",
    )
    p_import.add_argument("--json", action="store_true", help="emit the parse report as JSON")

    # t2e label --serve
    p_label = sub.add_parser(
        "label",
        help="launch the local labeling UI",
        description="Serve the labeling UI on localhost. Nothing leaves the machine.",
    )
    p_label.add_argument(
        "--serve", action="store_true", help="launch the UI (the only mode in v1)"
    )
    p_label.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    p_label.add_argument("--port", type=int, default=8765, help="bind port (default: 8765)")
    p_label.add_argument("--no-browser", action="store_true", help="do not open a browser tab")

    # t2e export --version vN
    p_export = sub.add_parser(
        "export",
        help="export eval cases at a version",
        description="Write versioned cases.jsonl, a generated pytest stub, and optional Promptfoo YAML.",
    )
    p_export.add_argument(
        "--version",
        dest="case_version",
        required=True,
        metavar="vN",
        help="case version to export, e.g. v1",
    )
    p_export.add_argument(
        "--format",
        default="jsonl,pytest",
        help="comma-separated: jsonl, pytest, promptfoo (default: jsonl,pytest)",
    )
    p_export.add_argument(
        "--out", metavar="DIR", default="exports", help="output directory (default: exports/)"
    )
    p_export.add_argument("--notes", default="", help="notes recorded against the export version")

    # t2e stats
    p_stats = sub.add_parser(
        "stats",
        help="print label distribution and case counts (CI-friendly)",
        description="Prints run/label/case counts, verdict and failure-tag distribution, "
        "and median seconds per label. Exits non-zero when the store is empty.",
    )
    p_stats.add_argument("--json", action="store_true", help="emit stats as JSON")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    from t2e import cli_commands

    handlers = {
        "import": cli_commands.cmd_import,
        "label": cli_commands.cmd_label,
        "export": cli_commands.cmd_export,
        "stats": cli_commands.cmd_stats,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
