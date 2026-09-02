"""OpenTelemetry JSON importer, GenAI semantic-convention aware (spec 03 F1a).

Accepts the OTLP/JSON export shape (`resourceSpans -> scopeSpans -> spans`) and the two flatter
shapes tooling commonly emits (`{"spans": [...]}` and a bare span array).

The GenAI semantic conventions have moved more than once, so attribute lookup uses a tolerant alias
set rather than a single spelling - see `docs/importers.md` for the full mapping table. Model calls,
tool spans and agent handoffs are recognised; container spans (the root workflow span) become the
run itself rather than a step.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from t2e.parsers.base import ParseResult, as_error_text, excerpt, parse_timestamp, pick
from t2e.schemas import ParseReport, RawRun, RawStep, StepKind

SOURCE = "otel"

# --- attribute aliases (tolerant across semconv versions) ---------------------------------------

_OPERATION = ("gen_ai.operation.name", "gen_ai.operation", "operation.name")
_MODEL = (
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.model",
    "llm.model_name",
    "llm.request.model",
)
_PROMPT = (
    "gen_ai.prompt",
    "gen_ai.input.messages",
    "gen_ai.request.messages",
    "llm.prompts",
    "llm.input_messages",
    "input.value",
)
_COMPLETION = (
    "gen_ai.completion",
    "gen_ai.output.messages",
    "gen_ai.response.text",
    "gen_ai.response.messages",
    "llm.completions",
    "llm.output_messages",
    "output.value",
)
_TOOL_NAME = ("gen_ai.tool.name", "tool.name", "gen_ai.tool.call.name")
_TOOL_ARGS = (
    "gen_ai.tool.call.arguments",
    "gen_ai.tool.arguments",
    "gen_ai.tool.input",
    "tool.arguments",
    "tool.input",
    "input.value",
)
_TOOL_RESULT = (
    "gen_ai.tool.call.result",
    "gen_ai.tool.output",
    "gen_ai.tool.result",
    "tool.result",
    "tool.output",
    "output.value",
)
_AGENT_NAME = ("gen_ai.agent.name", "agent.name", "gen_ai.agent.id")

_TOOL_OPERATIONS = {"execute_tool", "execute_tool_call", "tool", "tool_call"}
_AGENT_OPERATIONS = {"invoke_agent", "create_agent", "handoff", "transfer_to_agent"}
_LLM_OPERATIONS = {
    "chat",
    "text_completion",
    "completion",
    "generate_content",
    "embeddings",
    "generate",
}


# --- OTLP AnyValue decoding ---------------------------------------------------------------------


def decode_any_value(value: Any) -> Any:
    """Unwrap an OTLP `AnyValue`. Plain JSON values pass straight through."""
    if not isinstance(value, dict):
        return value

    if "stringValue" in value or "string_value" in value:
        return pick(value, "stringValue")
    if "intValue" in value or "int_value" in value:
        raw = pick(value, "intValue")
        try:
            return int(raw)
        except (TypeError, ValueError):
            return raw
    if "doubleValue" in value or "double_value" in value:
        raw = pick(value, "doubleValue")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw
    if "boolValue" in value or "bool_value" in value:
        return bool(pick(value, "boolValue"))
    if "bytesValue" in value or "bytes_value" in value:
        raw = pick(value, "bytesValue")
        if isinstance(raw, str):
            try:
                return base64.b64decode(raw).decode("utf-8", "replace")
            except (ValueError, TypeError):
                return raw
        return raw
    if "arrayValue" in value or "array_value" in value:
        array = pick(value, "arrayValue") or {}
        return [decode_any_value(item) for item in (pick(array, "values") or [])]
    if "kvlistValue" in value or "kvlist_value" in value:
        kvlist = pick(value, "kvlistValue") or {}
        return decode_attributes(pick(kvlist, "values") or [])
    return value


def decode_attributes(attributes: Any) -> dict[str, Any]:
    """Accept the OTLP key/value list or the plain dict some exporters emit."""
    if isinstance(attributes, dict):
        return {str(k): decode_any_value(v) for k, v in attributes.items()}
    result: dict[str, Any] = {}
    if isinstance(attributes, list):
        for entry in attributes:
            if isinstance(entry, dict) and "key" in entry:
                result[str(entry["key"])] = decode_any_value(entry.get("value"))
    return result


def _maybe_json(value: Any) -> Any:
    """GenAI attributes are flat strings, so structured payloads arrive JSON-encoded."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "[") and text[-1:] in ("}", "]"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return value
    return value


def _attr(attrs: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in attrs and attrs[name] not in (None, ""):
            return _maybe_json(attrs[name])
    return None


# --- span iteration -----------------------------------------------------------------------------


class _SpanRecord:
    __slots__ = ("span", "locator", "resource", "scope", "attrs")

    def __init__(
        self, span: dict[str, Any], locator: str, resource: dict[str, Any], scope: str | None
    ) -> None:
        self.span = span
        self.locator = locator
        self.resource = resource
        self.scope = scope
        self.attrs = decode_attributes(pick(span, "attributes"))


def _iter_spans(doc: Any, report: ParseReport) -> Iterator[_SpanRecord]:
    """Yield every span in the document, whichever of the three accepted shapes it uses."""
    resource_spans = pick(doc, "resourceSpans")
    if isinstance(resource_spans, list):
        yield from _iter_otlp(resource_spans, report)
        return

    flat = pick(doc, "spans") if isinstance(doc, dict) else None
    if isinstance(flat, list):
        yield from _iter_flat(flat, report, "spans")
        return

    if isinstance(doc, list):
        # A bare array: either resourceSpans entries or spans themselves.
        if doc and isinstance(doc[0], dict) and (
            "scopeSpans" in doc[0] or "scope_spans" in doc[0] or "resource" in doc[0]
        ):
            yield from _iter_otlp(doc, report)
        else:
            yield from _iter_flat(doc, report, "")
        return

    report.add_error(
        "<document>",
        "unrecognised OpenTelemetry JSON shape: expected `resourceSpans`, `spans`, or a span array",
        excerpt=excerpt(doc),
    )


def _iter_otlp(
    resource_spans: list[Any], report: ParseReport, prefix: str = "resourceSpans"
) -> Iterator[_SpanRecord]:
    for i, resource_span in enumerate(resource_spans):
        base = f"{prefix}[{i}]" if prefix else f"[{i}]"
        if not isinstance(resource_span, dict):
            report.records_seen += 1
            report.add_error(base, "not a JSON object", excerpt=excerpt(resource_span))
            continue

        resource = decode_attributes(pick(pick(resource_span, "resource") or {}, "attributes"))
        scope_spans = pick(resource_span, "scopeSpans", "instrumentationLibrarySpans")
        if not isinstance(scope_spans, list):
            report.records_seen += 1
            report.add_error(
                base, "missing or invalid `scopeSpans`", excerpt=excerpt(resource_span)
            )
            continue

        for j, scope_span in enumerate(scope_spans):
            scope_locator = f"{base}.scopeSpans[{j}]"
            if not isinstance(scope_span, dict):
                report.records_seen += 1
                report.add_error(scope_locator, "not a JSON object", excerpt=excerpt(scope_span))
                continue
            scope_name = pick(pick(scope_span, "scope", "instrumentationLibrary") or {}, "name")
            spans = pick(scope_span, "spans")
            if not isinstance(spans, list):
                report.records_seen += 1
                report.add_error(
                    scope_locator, "missing or invalid `spans`", excerpt=excerpt(scope_span)
                )
                continue
            for k, span in enumerate(spans):
                locator = f"{scope_locator}.spans[{k}]"
                report.records_seen += 1
                if not isinstance(span, dict):
                    report.add_error(locator, "not a JSON object", excerpt=excerpt(span))
                    continue
                yield _SpanRecord(span, locator, resource, scope_name)


def _iter_flat(spans: list[Any], report: ParseReport, prefix: str) -> Iterator[_SpanRecord]:
    for k, span in enumerate(spans):
        locator = f"{prefix}[{k}]" if prefix else f"[{k}]"
        report.records_seen += 1
        if not isinstance(span, dict):
            report.add_error(locator, "not a JSON object", excerpt=excerpt(span))
            continue
        yield _SpanRecord(span, locator, {}, None)


# --- span interpretation ------------------------------------------------------------------------


def _span_error(record: _SpanRecord) -> str | None:
    status = pick(record.span, "status") or {}
    code = pick(status, "code")
    is_error = code in (2, "2", "STATUS_CODE_ERROR", "ERROR", "Error")
    message = as_error_text(pick(status, "message"))

    # An exception event is often the only place the real message lives.
    for event in pick(record.span, "events") or []:
        if not isinstance(event, dict):
            continue
        if pick(event, "name") == "exception":
            attrs = decode_attributes(pick(event, "attributes"))
            detail = attrs.get("exception.message") or attrs.get("exception.type")
            if detail:
                return str(detail)
            is_error = True
    if is_error:
        return message or "span reported STATUS_CODE_ERROR"
    return message


def _event_messages(record: _SpanRecord, names: tuple[str, ...]) -> Any:
    """Newer semconv puts prompts/completions in span events rather than attributes."""
    collected: list[Any] = []
    for event in pick(record.span, "events") or []:
        if not isinstance(event, dict):
            continue
        name = str(pick(event, "name") or "")
        if name in names:
            attrs = decode_attributes(pick(event, "attributes"))
            body = attrs.get("gen_ai.event.content") or attrs.get("body") or attrs
            collected.append(_maybe_json(body))
    if not collected:
        return None
    return collected[0] if len(collected) == 1 else collected


_PROMPT_EVENTS = (
    "gen_ai.user.message",
    "gen_ai.system.message",
    "gen_ai.assistant.message",
    "gen_ai.tool.message",
)
_COMPLETION_EVENTS = ("gen_ai.choice", "gen_ai.assistant.message")


def classify(record: _SpanRecord, is_root: bool) -> StepKind | None:
    """Map a span to a step kind, or None when it is a container rather than a step."""
    attrs = record.attrs
    operation = str(_attr(attrs, _OPERATION) or "").lower()
    name = str(pick(record.span, "name") or "")
    lowered = name.lower()

    if (
        operation in _TOOL_OPERATIONS
        or _attr(attrs, _TOOL_NAME) is not None
        or lowered.startswith(("execute_tool", "tool.", "tool "))
    ):
        return "tool"

    if operation in _AGENT_OPERATIONS or "handoff" in lowered or "transfer_to" in lowered:
        # The outermost agent span is the run; a nested one is a delegation.
        is_container = is_root and operation != "handoff" and "handoff" not in lowered
        return None if is_container else "handoff"

    if (
        operation in _LLM_OPERATIONS
        or _attr(attrs, _MODEL) is not None
        or _attr(attrs, _PROMPT) is not None
        or _attr(attrs, _COMPLETION) is not None
    ):
        return "llm"

    return None


def _step_from_span(record: _SpanRecord, kind: StepKind) -> RawStep:
    attrs = record.attrs
    span_name = str(pick(record.span, "name") or "span")
    started = parse_timestamp(pick(record.span, "startTimeUnixNano", "startTime"))
    ended = parse_timestamp(pick(record.span, "endTimeUnixNano", "endTime"))

    if kind == "tool":
        name = str(_attr(attrs, _TOOL_NAME) or span_name)
        args = _attr(attrs, _TOOL_ARGS)
        output = _attr(attrs, _TOOL_RESULT)
    elif kind == "llm":
        name = str(_attr(attrs, _MODEL) or span_name)
        args = _attr(attrs, _PROMPT) or _event_messages(record, _PROMPT_EVENTS)
        output = _attr(attrs, _COMPLETION) or _event_messages(record, _COMPLETION_EVENTS)
    else:
        name = str(_attr(attrs, _AGENT_NAME) or span_name)
        args = _attr(attrs, _PROMPT) or _attr(attrs, _TOOL_ARGS)
        output = _attr(attrs, _COMPLETION) or _attr(attrs, _TOOL_RESULT)

    meta: dict[str, Any] = {"span_name": span_name}
    if record.scope:
        meta["scope"] = record.scope
    for token_key in ("gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens"):
        if token_key in attrs:
            meta["input_tokens"] = attrs[token_key]
            break
    for token_key in ("gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens"):
        if token_key in attrs:
            meta["output_tokens"] = attrs[token_key]
            break

    return RawStep(
        kind=kind,
        name=name,
        args=args,
        output=output,
        started=started,
        ended=ended,
        error=_span_error(record),
        meta=meta,
    )


# --- run assembly -------------------------------------------------------------------------------


def _group_key(record: _SpanRecord, fallback: str) -> str:
    trace_id = pick(record.span, "traceId")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    span_id = pick(record.span, "spanId")
    if isinstance(span_id, str) and span_id.strip():
        return span_id.strip()
    return fallback


def _build_run(
    trace_id: str, records: list[_SpanRecord], file_label: str, report: ParseReport
) -> RawRun | None:
    span_ids = {
        str(pick(r.span, "spanId")) for r in records if pick(r.span, "spanId") is not None
    }

    def is_root(record: _SpanRecord) -> bool:
        parent = pick(record.span, "parentSpanId")
        return not (isinstance(parent, str) and parent.strip() and parent.strip() in span_ids)

    roots = [r for r in records if is_root(r)]
    root = roots[0] if roots else records[0]

    steps: list[RawStep] = []
    for record in records:
        kind = classify(record, is_root=record is root)
        if kind is None:
            continue
        steps.append(_step_from_span(record, kind))

    starts = [
        ts
        for ts in (
            parse_timestamp(pick(r.span, "startTimeUnixNano", "startTime")) for r in records
        )
        if ts
    ]
    ends = [
        ts
        for ts in (parse_timestamp(pick(r.span, "endTimeUnixNano", "endTime")) for r in records)
        if ts
    ]

    root_attrs = root.attrs
    run_input = _attr(root_attrs, _PROMPT) or _event_messages(root, _PROMPT_EVENTS)
    if run_input is None:
        run_input = next((s.args for s in steps if s.kind == "llm" and s.args), None)
    run_output = _attr(root_attrs, _COMPLETION) or _event_messages(root, _COMPLETION_EVENTS)
    if run_output is None:
        run_output = next((s.output for s in reversed(steps) if s.output), None)

    root_error = _span_error(root)

    if not steps and run_input is None and run_output is None:
        # A trace of pure infrastructure spans (HTTP, DB) has nothing an agent could be labeled on.
        report.add_error(
            f"trace {trace_id}",
            "no GenAI spans in trace (no model call, tool call, or agent span)",
            excerpt=str(pick(root.span, "name") or ""),
        )
        return None

    meta: dict[str, Any] = {
        "trace_id": trace_id,
        "source_file": file_label,
        "root_span": str(pick(root.span, "name") or ""),
        "span_count": len(records),
    }
    if service := root.resource.get("service.name"):
        meta["service"] = service
    if root.scope:
        meta["scope"] = root.scope

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


# --- entry points -------------------------------------------------------------------------------


def parse_text(text: str, file_label: str = "<text>") -> ParseResult:
    report = ParseReport(file=file_label, format=SOURCE)
    result = ParseResult(report=report)

    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        report.records_seen += 1
        report.add_error("<document>", f"file is not valid JSON: {exc.msg} at line {exc.lineno}")
        return result

    grouped: dict[str, list[_SpanRecord]] = {}
    order: list[str] = []
    for index, record in enumerate(_iter_spans(doc, report)):
        key = _group_key(record, fallback=f"{Path(file_label).stem}-{index}")
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
        report.warnings.append("no GenAI spans recognised in this file")
    return result


def parse_file(path: str | Path) -> ParseResult:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        report = ParseReport(file=path.name, format=SOURCE)
        report.add_error("<file>", f"could not read file: {exc}")
        return ParseResult(report=report)
    return parse_text(text, file_label=path.name)
