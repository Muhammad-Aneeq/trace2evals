"""Export formats and the writer that puts them on disk.

Three formats (spec 03 F5): the versioned `cases.jsonl` you keep, a generated pytest stub that runs
anywhere, and an optional Promptfoo config. `cases.jsonl` is always written alongside the pytest stub,
because a stub without its cases is inert.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from t2e.exporters import cases_jsonl, promptfoo, pytest_stub
from t2e.models import Case

FORMATS = ("jsonl", "pytest", "promptfoo")


def parse_formats(spec: str) -> list[str]:
    """Parse a `--format jsonl,pytest` string. Unknown names are an error, not a silent skip."""
    requested = [name.strip().lower() for name in spec.split(",") if name.strip()]
    if not requested:
        raise ValueError(f"no formats requested; expected any of {', '.join(FORMATS)}")

    unknown = [name for name in requested if name not in FORMATS]
    if unknown:
        raise ValueError(
            f"unknown export format(s): {', '.join(unknown)}. Expected any of {', '.join(FORMATS)}"
        )

    # De-duplicate, preserving the canonical order so output is deterministic.
    return [name for name in FORMATS if name in set(requested)]


def render(
    cases: Sequence[Case], *, version: str, formats: Sequence[str]
) -> dict[str, str]:
    """Render the requested formats to `{filename: text}` without touching the filesystem."""
    rendered: dict[str, str] = {}

    # The pytest stub is useless without its cases, so requesting it implies the JSONL.
    needs_jsonl = "jsonl" in formats or "pytest" in formats
    if needs_jsonl:
        rendered[cases_jsonl.FILENAME] = cases_jsonl.render(cases)
    if "pytest" in formats:
        rendered[pytest_stub.FILENAME] = pytest_stub.render(
            cases, version=version, cases_filename=cases_jsonl.FILENAME
        )
    if "promptfoo" in formats:
        rendered[promptfoo.FILENAME] = promptfoo.render(cases, version=version)

    return rendered


def write(
    cases: Sequence[Case],
    *,
    version: str,
    formats: Sequence[str],
    out_dir: str | Path,
) -> dict[str, Any]:
    """Write the export and report exactly what landed where."""
    directory = Path(out_dir)
    directory.mkdir(parents=True, exist_ok=True)

    rendered = render(cases, version=version, formats=formats)
    written: list[dict[str, Any]] = []
    for filename, text in rendered.items():
        path = directory / filename
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append({"file": str(path), "bytes": len(text.encode("utf-8"))})

    return {
        "version": version,
        "case_count": len(cases),
        "formats": list(formats),
        "out_dir": str(directory),
        "files": written,
    }


__all__ = ["FORMATS", "cases_jsonl", "parse_formats", "promptfoo", "pytest_stub", "render", "write"]
