"""The versioned `cases.jsonl` export - the artefact you actually keep.

Schema is documented in `docs/cases_schema.md` and pinned by `CASE_SCHEMA_VERSION`. Every record
carries that version so a downstream reader can refuse a shape it does not understand, and so the
golden-file tests fail loudly rather than drifting.

Records are written with sorted keys and a stable ordering (version, then case id), which is what makes
byte-for-byte golden comparison meaningful.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from typing import Any

from t2e import CASE_SCHEMA_VERSION
from t2e.models import Case
from t2e.store import loads

FORMAT = "jsonl"
FILENAME = "cases.jsonl"


def case_to_record(case: Case) -> dict[str, Any]:
    """One case as a portable record. No SQLite ids leak: `case_id` is stable within an export."""
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "case_id": f"{case.version}-{case.id:04d}",
        "version": case.version,
        "run_id": case.run_id,
        "input": loads(case.input_json, ""),
        "expectations": loads(case.expectations_json, []) or [],
        "tags": loads(case.tags_json, []) or [],
        "created_at": case.created_at.isoformat() if case.created_at else None,
    }


def render(cases: Sequence[Case]) -> str:
    """JSONL text. Trailing newline included so the file concatenates and diffs cleanly."""
    ordered = sorted(cases, key=lambda case: (case.version, case.id))
    lines = [
        json.dumps(case_to_record(case), sort_keys=True, ensure_ascii=False) for case in ordered
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def parse(text: str) -> list[dict[str, Any]]:
    """Read back an export. Used by the generated pytest stub to load its cases."""
    records: list[dict[str, Any]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"cases.jsonl line {lineno} is not valid JSON: {exc.msg}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"cases.jsonl line {lineno} is not a JSON object")
        records.append(record)
    return records


def iter_records(cases: Iterable[Case]) -> Iterable[dict[str, Any]]:
    for case in cases:
        yield case_to_record(case)
