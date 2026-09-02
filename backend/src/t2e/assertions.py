"""The v1 assertion language: exactly five kinds, and no sixth.

Spec 03 sec 14 names over-building the assertion language as a live risk and caps v1 at five kinds:

    must_call_tool · must_escalate · must_cite · output_matches_regex · output_matches_schema

That cap is enforced by `ASSERTION_KINDS` in `t2e.schemas` and by a test. Adding a kind means arguing
against the spec, not just appending to a dict.

These functions are the assertion helpers the generated `test_cases.py` imports (spec 03 F5), so the
evaluation logic exists once and is tested once, rather than being duplicated into every export
(PLAN.md D-008).

A user plugs their own agent in by returning an `AgentRun` from an adapter. Nothing here calls a model:
assertions are pure functions over a result the caller already has.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from t2e.schemas import ASSERTION_KINDS

#: Tool names that conventionally mean "a human was pulled in". Overridable per assertion.
DEFAULT_ESCALATION_TOOLS = (
    "flag_exception",
    "escalate",
    "escalate_to_human",
    "create_ticket",
    "notify_reviewer",
    "request_approval",
)

#: Phrases that indicate escalation when no structured signal is available.
DEFAULT_ESCALATION_KEYWORDS = (
    "escalate",
    "escalated",
    "escalating",
    "refer to a human",
    "human review",
    "needs review",
    "cannot determine",
    "insufficient evidence",
)

#: Evidence-id shapes this domain uses, for citation detection when the adapter reports none.
DEFAULT_CITATION_PATTERN = re.compile(r"\b[A-Z]{2,6}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b")


@dataclass
class AgentRun:
    """What an adapter must return. Deliberately small: five assertions need very little.

    Only `output` is required. The other fields let an adapter report structured facts instead of
    making the assertions guess them from text, which is always the more reliable path.
    """

    output: str = ""
    #: Tool names the agent called, in order.
    tool_calls: list[str] = field(default_factory=list)
    #: Evidence ids the agent cited, if the adapter can report them.
    citations: list[str] = field(default_factory=list)
    #: Explicit escalation signal. None means "unknown, infer it".
    escalated: bool | None = None
    #: Anything else the adapter wants to carry through.
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_any(cls, value: Any) -> AgentRun:
        """Accept an `AgentRun`, a plain dict, or a bare string, so adapters stay easy to write."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(output=value)
        if isinstance(value, dict):
            tool_calls = value.get("tool_calls") or value.get("tools") or []
            # Tolerate [{"name": "x"}] as well as ["x"].
            names = [
                call.get("name", "") if isinstance(call, dict) else str(call) for call in tool_calls
            ]
            return cls(
                output=str(value.get("output", "") or ""),
                tool_calls=[name for name in names if name],
                citations=[str(c) for c in (value.get("citations") or [])],
                escalated=value.get("escalated"),
                meta=value.get("meta") or {},
            )
        raise TypeError(f"cannot interpret {type(value).__name__} as an AgentRun")


@dataclass
class AssertionOutcome:
    passed: bool
    kind: str
    message: str

    def __bool__(self) -> bool:
        return self.passed


def _ok(kind: str, message: str) -> AssertionOutcome:
    return AssertionOutcome(passed=True, kind=kind, message=message)


def _fail(kind: str, message: str) -> AssertionOutcome:
    return AssertionOutcome(passed=False, kind=kind, message=message)


# --- 1. must_call_tool --------------------------------------------------------------------------


def must_call_tool(result: Any, tool: str, *, allow_any: bool = False) -> AssertionOutcome:
    """The agent must have called `tool`. With `allow_any`, a comma-separated list satisfies any one."""
    run = AgentRun.from_any(result)
    wanted = [name.strip() for name in tool.split(",")] if allow_any else [tool]
    called = run.tool_calls

    hits = [name for name in wanted if name in called]
    if hits:
        return _ok("must_call_tool", f"called {', '.join(hits)}")
    return _fail(
        "must_call_tool",
        f"expected a call to {' or '.join(wanted)}; called {called or '(no tools)'}",
    )


# --- 2. must_escalate ---------------------------------------------------------------------------


def must_escalate(
    result: Any,
    *,
    tools: tuple[str, ...] | list[str] = DEFAULT_ESCALATION_TOOLS,
    keywords: tuple[str, ...] | list[str] = DEFAULT_ESCALATION_KEYWORDS,
) -> AssertionOutcome:
    """The agent must have handed off to a human rather than guessing.

    An explicit `escalated` flag from the adapter always wins. Otherwise an escalation tool call
    counts, and only then does a keyword in the output - text matching is the weakest signal, so it
    is the last resort.
    """
    run = AgentRun.from_any(result)

    if run.escalated is True:
        return _ok("must_escalate", "adapter reported escalated=True")
    if run.escalated is False:
        return _fail("must_escalate", "adapter reported escalated=False")

    matched_tool = next((name for name in run.tool_calls if name in set(tools)), None)
    if matched_tool:
        return _ok("must_escalate", f"called escalation tool {matched_tool!r}")

    lowered = run.output.lower()
    matched_keyword = next((word for word in keywords if word in lowered), None)
    if matched_keyword:
        return _ok("must_escalate", f"output signals escalation ({matched_keyword!r})")

    return _fail(
        "must_escalate",
        "no escalation signal: no escalated flag, no escalation tool call, "
        "and no escalation language in the output",
    )


# --- 3. must_cite -------------------------------------------------------------------------------


def must_cite(
    result: Any,
    sources: list[str] | tuple[str, ...] | None = None,
    *,
    min_count: int = 1,
) -> AssertionOutcome:
    """The claim must be grounded in evidence.

    With `sources`, every named id must appear. Without, at least `min_count` citation-shaped ids
    must be present - which is what catches an ungrounded answer that sounds authoritative.
    """
    run = AgentRun.from_any(result)

    found = set(run.citations)
    if not found:
        found = set(DEFAULT_CITATION_PATTERN.findall(run.output))

    if sources:
        missing = [source for source in sources if source not in found and source not in run.output]
        if missing:
            return _fail("must_cite", f"missing citation(s): {', '.join(missing)}")
        return _ok("must_cite", f"cited all {len(sources)} required source(s)")

    if len(found) >= min_count:
        return _ok("must_cite", f"found {len(found)} citation(s)")
    return _fail(
        "must_cite",
        f"expected at least {min_count} citation(s), found {len(found) or 'none'}",
    )


# --- 4. output_matches_regex --------------------------------------------------------------------


def output_matches_regex(result: Any, pattern: str, *, flags: str = "") -> AssertionOutcome:
    """The output must match `pattern`. `flags` accepts any of `i`, `m`, `s`."""
    run = AgentRun.from_any(result)

    compiled_flags = 0
    if "i" in flags:
        compiled_flags |= re.IGNORECASE
    if "m" in flags:
        compiled_flags |= re.MULTILINE
    if "s" in flags:
        compiled_flags |= re.DOTALL

    try:
        regex = re.compile(pattern, compiled_flags)
    except re.error as exc:
        # A broken pattern is an authoring bug, and must fail loudly rather than pass by accident.
        return _fail("output_matches_regex", f"invalid regex {pattern!r}: {exc}")

    if regex.search(run.output):
        return _ok("output_matches_regex", f"output matches {pattern!r}")
    return _fail(
        "output_matches_regex",
        f"output does not match {pattern!r}; output was {_clip(run.output)!r}",
    )


# --- 5. output_matches_schema -------------------------------------------------------------------

#: The JSON Schema subset supported without taking a dependency (PLAN.md D-017).
_SUPPORTED_SCHEMA_KEYS = {
    "type",
    "required",
    "properties",
    "items",
    "enum",
    "minimum",
    "maximum",
    "minItems",
    "minLength",
}

_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def output_matches_schema(result: Any, schema: dict[str, Any]) -> AssertionOutcome:
    """The output must parse as JSON and satisfy `schema`.

    A deliberately small JSON Schema subset is implemented in-tree (`type`, `required`, `properties`,
    `items`, `enum`, `minimum`/`maximum`, `minItems`, `minLength`) so the tool keeps its zero-runtime-
    dependency promise. Unsupported keywords are reported, never silently ignored - an assertion that
    quietly does nothing is worse than one that fails.
    """
    run = AgentRun.from_any(result)

    unsupported = _unsupported_keywords(schema)
    if unsupported:
        return _fail(
            "output_matches_schema",
            f"unsupported JSON Schema keyword(s): {', '.join(sorted(unsupported))}. "
            f"Supported: {', '.join(sorted(_SUPPORTED_SCHEMA_KEYS))}",
        )

    text = run.output.strip()
    # Tolerate a fenced code block, which models emit constantly.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return _fail(
            "output_matches_schema",
            f"output is not valid JSON ({exc.msg}); output was {_clip(run.output)!r}",
        )

    problems = _validate(payload, schema, path="$")
    if problems:
        return _fail("output_matches_schema", "; ".join(problems[:5]))
    return _ok("output_matches_schema", "output satisfies the schema")


def _unsupported_keywords(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    found = {key for key in schema if key not in _SUPPORTED_SCHEMA_KEYS and not key.startswith("$")}
    for value in schema.get("properties", {}).values():
        found |= _unsupported_keywords(value)
    if isinstance(schema.get("items"), dict):
        found |= _unsupported_keywords(schema["items"])
    return found


def _validate(value: Any, schema: dict[str, Any], path: str) -> list[str]:
    problems: list[str] = []

    expected_type = schema.get("type")
    if expected_type:
        python_type = _JSON_TYPES.get(expected_type)
        if python_type is None:
            return [f"{path}: unknown type {expected_type!r}"]
        # bool is a subclass of int in Python, but JSON treats them as distinct.
        if expected_type in ("number", "integer") and isinstance(value, bool):
            return [f"{path}: expected {expected_type}, got boolean"]
        if not isinstance(value, python_type):
            return [f"{path}: expected {expected_type}, got {_json_type_name(value)}"]

    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{path}: {value!r} is not one of {schema['enum']}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{path}: missing required property {key!r}")
        for key, subschema in (schema.get("properties") or {}).items():
            if key in value and isinstance(subschema, dict):
                problems.extend(_validate(value[key], subschema, f"{path}.{key}"))

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            problems.append(f"{path}: expected at least {min_items} item(s), got {len(value)}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                problems.extend(_validate(item, item_schema, f"{path}[{index}]"))

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            problems.append(f"{path}: expected at least {min_length} character(s), got {len(value)}")

    if isinstance(value, int | float) and not isinstance(value, bool):
        minimum, maximum = schema.get("minimum"), schema.get("maximum")
        if minimum is not None and value < minimum:
            problems.append(f"{path}: {value} is below the minimum {minimum}")
        if maximum is not None and value > maximum:
            problems.append(f"{path}: {value} is above the maximum {maximum}")

    return problems


def _json_type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if value is None:
        return "null"
    for name, python_type in _JSON_TYPES.items():
        if name in ("number", "boolean", "null"):
            continue
        if isinstance(value, python_type):
            return name
    return type(value).__name__


# --- dispatch -----------------------------------------------------------------------------------

_HANDLERS = {
    "must_call_tool": lambda run, params: must_call_tool(
        run, params["tool"], allow_any=bool(params.get("allow_any", False))
    ),
    "must_escalate": lambda run, params: must_escalate(
        run,
        tools=params.get("tools", DEFAULT_ESCALATION_TOOLS),
        keywords=params.get("keywords", DEFAULT_ESCALATION_KEYWORDS),
    ),
    "must_cite": lambda run, params: must_cite(
        run, params.get("sources"), min_count=int(params.get("min_count", 1))
    ),
    "output_matches_regex": lambda run, params: output_matches_regex(
        run, params["pattern"], flags=str(params.get("flags", ""))
    ),
    "output_matches_schema": lambda run, params: output_matches_schema(run, params["schema"]),
}


def check(result: Any, expectation: dict[str, Any]) -> AssertionOutcome:
    """Evaluate one expectation record from a case, e.g. `{"kind": "must_call_tool", ...}`."""
    kind = expectation.get("kind")
    if kind not in ASSERTION_KINDS:
        return _fail(
            str(kind),
            f"unknown assertion kind {kind!r}; v1 supports exactly: {', '.join(ASSERTION_KINDS)}",
        )

    params = {key: value for key, value in expectation.items() if key not in ("kind", "note")}
    try:
        return _HANDLERS[kind](result, params)
    except KeyError as exc:
        return _fail(str(kind), f"assertion {kind!r} is missing required parameter {exc.args[0]!r}")


def check_all(result: Any, expectations: list[dict[str, Any]]) -> list[AssertionOutcome]:
    return [check(result, expectation) for expectation in expectations]


def assert_all(result: Any, expectations: list[dict[str, Any]], *, case_id: str = "") -> None:
    """Raise a readable `AssertionError` listing every failure. Used by the generated pytest stub."""
    outcomes = check_all(result, expectations)
    failures = [outcome for outcome in outcomes if not outcome.passed]
    if not failures:
        return

    header = f"case {case_id}: " if case_id else ""
    detail = "\n".join(f"  - [{outcome.kind}] {outcome.message}" for outcome in failures)
    raise AssertionError(
        f"{header}{len(failures)} of {len(outcomes)} expectation(s) failed:\n{detail}"
    )


def _clip(text: str, limit: int = 160) -> str:
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"
