"""LangSmith run-export JSONL importer (spec 03 F1b).

One JSON run record per line. Records are stitched into runs by `trace_id`, falling back to walking
`parent_run_id` to a root when the export predates `trace_id`. `dotted_order` is preferred for step
ordering because it is the export's own canonical sequence and survives equal timestamps.

Run-type mapping (full table in `docs/importers.md`):
    llm, embedding        -> llm step
    tool, retriever       -> tool step
    chain, agent (nested) -> handoff step
    chain, agent (root)   -> the run container itself, not a step
    prompt, parser        -> skipped as formatting noise, counted in meta
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from t2e.parsers.base import ParseResult, as_error_text, parse_timestamp, pick
from t2e.schemas import ParseReport, RawRun, RawStep, StepKind

SOURCE = "langsmith"

_KIND_BY_RUN_TYPE: dict[str, StepKind] = {
    "llm": "llm",
    "embedding": "llm",
    "chat_model": "llm",
    "tool": "tool",
    "retriever": "tool",
    "chain": "handoff",
    "agent": "handoff",
}

#: Structural records that carry no agent behaviour worth labeling.
_IGNORED_RUN_TYPES = {"prompt", "parser"}

#: Run types that act as containers when they sit at the root of a trace.
_CONTAINER_RUN_TYPES = {"chain", "agent"}


def _record_error_text(record: dict[str, Any]) -> str | None:
    return as_error_text(pick(record, "error"))


def _step_from_record(record: dict[str, Any], kind: StepKind) -> RawStep:
    name = str(pick(record, "name") or pick(record, "run_type") or "run")
    inputs = pick(record, "inputs")
    outputs = pick(record, "outputs")

    meta: dict[str, Any] = {"run_type": str(pick(record, "run_type") or "")}
    if run_id := pick(record, "id"):
        meta["langsmith_run_id"] = str(run_id)
    extra = pick(record, "extra") or {}
    if isinstance(extra, dict):
        metadata = pick(extra, "metadata")
        if isinstance(metadata, dict):
            if model := (metadata.get("ls_model_name") or metadata.get("model")):
                meta["model"] = model
    if tags := pick(record, "tags"):
        if isinstance(tags, list) and tags:
            meta["tags"] = [str(t) for t in tags]

    return RawStep(
        kind=kind,
        name=name,
        args=inputs,
        output=outputs,
        started=parse_timestamp(pick(record, "start_time")),
        ended=parse_timestamp(pick(record, "end_time")),
        error=_record_error_text(record),
        order_key=str(pick(record, "dotted_order")) if pick(record, "dotted_order") else None,
        meta=meta,
    )


def _find_root(records: list[dict[str, Any]]) -> dict[str, Any]:
    """The record whose parent is absent from this group; ties broken by dotted_order then start."""
    ids = {str(pick(r, "id")) for r in records if pick(r, "id") is not None}
    roots = [
        r
        for r in records
        if not (
            (parent := pick(r, "parent_run_id")) is not None and str(parent) in ids
        )
    ]
    candidates = roots or records
    return min(
        candidates,
        key=lambda r: (
            str(pick(r, "dotted_order") or ""),
            parse_timestamp(pick(r, "start_time")) is None,
            str(parse_timestamp(pick(r, "start_time")) or ""),
        ),
    )


def _build_run(
    trace_id: str, records: list[dict[str, Any]], file_label: str, report: ParseReport
) -> RawRun | None:
    root = _find_root(records)

    steps: list[RawStep] = []
    skipped = 0
    for record in records:
        run_type = str(pick(record, "run_type") or "").lower()
        if run_type in _IGNORED_RUN_TYPES:
            skipped += 1
            continue
        # A root chain/agent is the run itself; a nested one is a real delegation step.
        if record is root and run_type in _CONTAINER_RUN_TYPES:
            continue
        kind = _KIND_BY_RUN_TYPE.get(run_type)
        if kind is None:
            report.add_error(
                f"run {pick(record, 'id')}",
                f"unknown run_type {run_type!r}; record skipped",
                excerpt=json.dumps(record, default=str)[:200],
            )
            continue
        steps.append(_step_from_record(record, kind))

    starts = [ts for ts in (parse_timestamp(pick(r, "start_time")) for r in records) if ts]
    ends = [ts for ts in (parse_timestamp(pick(r, "end_time")) for r in records) if ts]

    run_input = pick(root, "inputs")
    if run_input is None:
        run_input = next((s.args for s in steps if s.args), None)
    run_output = pick(root, "outputs")
    if run_output is None:
        run_output = next((s.output for s in reversed(steps) if s.output), None)

    root_error = _record_error_text(root)

    meta: dict[str, Any] = {
        "trace_id": trace_id,
        "source_file": file_label,
        "root_name": str(pick(root, "name") or ""),
        "record_count": len(records),
    }
    if skipped:
        meta["skipped_records"] = skipped
    if session := pick(root, "session_id", "session_name"):
        meta["session"] = str(session)
    if tags := pick(root, "tags"):
        if isinstance(tags, list) and tags:
            meta["tags"] = [str(t) for t in tags]

    if not steps and run_input is None and run_output is None:
        report.add_error(f"trace {trace_id}", "no usable records in trace")
        return None

    return RawRun(
        run_id=trace_id,
        source=SOURCE,
        started=min(starts) if starts else None,
        ended=max(ends) if ends else None,
        input=run_input,
        output=run_output,
        error=root_error,
        status="error" if root_error else None,
        steps=steps,
        meta=meta,
    )


def _iter_records(text: str, report: ParseReport) -> list[tuple[str, dict[str, Any]]]:
    """Line-delimited JSON, tolerating a whole-file JSON array or single object instead."""
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            doc = json.loads(stripped)
        except json.JSONDecodeError as exc:
            report.records_seen += 1
            report.add_error(
                "<document>", f"file is not valid JSON: {exc.msg} at line {exc.lineno}"
            )
            return []
        records: list[tuple[str, dict[str, Any]]] = []
        for i, item in enumerate(doc if isinstance(doc, list) else []):
            report.records_seen += 1
            if isinstance(item, dict):
                records.append((f"[{i}]", item))
            else:
                report.add_error(f"[{i}]", "record is not a JSON object", excerpt=str(item))
        return records

    records = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        report.records_seen += 1
        locator = f"line {lineno}"
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            report.add_error(locator, f"invalid JSON: {exc.msg}", excerpt=line)
            continue
        if not isinstance(item, dict):
            report.add_error(locator, "record is not a JSON object", excerpt=line)
            continue
        if pick(item, "id") is None and pick(item, "trace_id") is None:
            report.add_error(locator, "record has neither `id` nor `trace_id`", excerpt=line)
            continue
        records.append((locator, item))
    return records


def parse_text(text: str, file_label: str = "<text>") -> ParseResult:
    report = ParseReport(file=file_label, format=SOURCE)
    result = ParseResult(report=report)

    records = _iter_records(text, report)

    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for index, (_locator, record) in enumerate(records):
        trace_id = pick(record, "trace_id")
        if not (isinstance(trace_id, str) and trace_id.strip()):
            # Pre-trace_id exports: a child inherits its root's id, a root uses its own.
            trace_id = _resolve_trace_id(record, records) or f"{Path(file_label).stem}-{index}"
        key = str(trace_id).strip()
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(record)

    for key in order:
        run = _build_run(key, grouped[key], file_label, report)
        if run is None:
            continue
        result.runs.append(run)
        report.runs_imported += 1
        report.steps_imported += len(run.steps)

    if not result.runs and not report.errors:
        report.warnings.append("no usable run records in this file")
    return result


def _resolve_trace_id(
    record: dict[str, Any], records: list[tuple[str, dict[str, Any]]]
) -> str | None:
    """Walk `parent_run_id` up to a root to synthesise the missing trace id."""
    by_id = {str(pick(r, "id")): r for _loc, r in records if pick(r, "id") is not None}
    current = record
    seen: set[str] = set()
    while True:
        current_id = str(pick(current, "id") or "")
        if current_id in seen:  # cycle in a corrupt export
            return current_id or None
        seen.add(current_id)
        parent = pick(current, "parent_run_id")
        if parent is None or str(parent) not in by_id:
            return current_id or None
        current = by_id[str(parent)]


def parse_file(path: str | Path) -> ParseResult:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report = ParseReport(file=path.name, format=SOURCE)
        report.add_error("<file>", f"could not read file: {exc}")
        return ParseResult(report=report)
    return parse_text(text, file_label=path.name)
