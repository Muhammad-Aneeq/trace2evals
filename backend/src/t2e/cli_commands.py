"""Subcommand bodies for the `t2e` CLI.

Phase 0 scaffold: the argument surface in `t2e.cli` is final, the bodies are filled in as their
supporting layers land (import in Phase 1, label --serve in Phase 2, export/stats in Phase 3).
Each stub tells the truth about its state rather than pretending to succeed.
"""

from __future__ import annotations

import argparse

_PENDING = "not yet implemented at this build phase - see PLAN.md"


def _pending(name: str, phase: str) -> int:
    print(f"t2e {name}: {_PENDING} ({phase})")
    return 70  # EX_SOFTWARE: signals "unavailable", never a false success


def cmd_import(args: argparse.Namespace) -> int:
    return _pending("import", "Phase 1")


def cmd_label(args: argparse.Namespace) -> int:
    return _pending("label", "Phase 2")


def cmd_export(args: argparse.Namespace) -> int:
    return _pending("export", "Phase 3")


def cmd_stats(args: argparse.Namespace) -> int:
    return _pending("stats", "Phase 3")
