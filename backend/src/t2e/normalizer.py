"""RawRun -> TraceRun.

Both importers funnel through here, so preview truncation, latency arithmetic, step ordering and
outcome derivation are decided in exactly one place. That is what makes an OTel run and a
LangSmith run comparable once normalized - and what makes the snapshot tests meaningful.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from t2e.schemas import (
    INPUT_LIMIT,
    OUTPUT_LIMIT,
    PREVIEW_LIMIT,
    Outcome,
    RawRun,
    RawStep,
    Step,
    TraceRun,
)

#: Keys that commonly hold the human-meaningful text inside a structured payload, best first.
_TEXT_KEYS = (
    "input",
    "output",
    "question",
    "query",
    "prompt",
    "text",
    "content",
    "answer",
    "result",
    "value",
)

_ELLIPSIS = "…"


def to_text(value: Any, limit: int) -> str:
    """Render any payload as readable text, preferring the obvious text field when there is one."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _truncate(value.strip(), limit)
    if isinstance(value, bool | int | float):
        return str(value)
    if isinstance(value, dict):
        # Unwrap a lone wrapper key like {"input": "..."}, but keep meaningful keys visible:
        # tool args read far better as {"po":"PO-76550"} than as a bare "PO-76550".
        if len(value) == 1:
            ((only_key, only_value),) = value.items()
            if only_key in _TEXT_KEYS:
                return to_text(only_value, limit)
        for key in _TEXT_KEYS:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return _truncate(candidate.strip(), limit)
        if "generations" in value:
            rendered = _render_generations(value["generations"])
            if rendered:
                return _truncate(rendered, limit)
        if messages := value.get("messages"):
            rendered = _render_messages(messages)
            if rendered:
                return _truncate(rendered, limit)
        return _truncate(_compact_json(value), limit)
    if isinstance(value, list):
        rendered = _render_messages(value)
        if rendered:
            return _truncate(rendered, limit)
        return _truncate(_compact_json(value), limit)
    return _truncate(str(value), limit)


def make_preview(value: Any, limit: int | None = None) -> str:
    """A short, single-line rendering for step cards. Whitespace is collapsed on purpose."""
    text = to_text(value, limit or PREVIEW_LIMIT)
    return " ".join(text.split())


def _render_generations(generations: Any) -> str:
    """Unwrap LangChain's `LLMResult.generations`, which nests one list per prompt."""
    if not isinstance(generations, list):
        return ""
    texts: list[str] = []
    stack = list(generations)
    while stack:
        item = stack.pop(0)
        if isinstance(item, list):
            stack = list(item) + stack
        elif isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
            elif isinstance(message := item.get("message"), dict):
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    texts.append(content.strip())
        elif isinstance(item, str) and item.strip():
            texts.append(item.strip())
    return "\n".join(texts)


def _render_messages(messages: Any) -> str:
    """Render a chat-message array as `role: content` lines; return "" if it isn't one."""
    if not isinstance(messages, list) or not messages:
        return ""
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            return ""
        role = message.get("role")
        content = message.get("content")
        if role is None and content is None:
            return ""
        if isinstance(content, list):
            # Multi-part content blocks: keep only the text parts.
            parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("text")
            ]
            content = " ".join(parts)
        if content is None:
            content = ""
        lines.append(f"{role}: {content}" if role else str(content))
    return "\n".join(lines).strip()


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: limit - 1] + _ELLIPSIS


# --- latency / ordering -------------------------------------------------------------------------


def _duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    delta = (end - start).total_seconds() * 1000.0
    if delta < 0:
        return None  # clock skew or a mis-parsed timestamp: report nothing rather than nonsense
    return round(delta, 3)


def _step_latency(step: RawStep) -> float | None:
    if step.latency_ms is not None:
        return round(step.latency_ms, 3)
    return _duration_ms(step.started, step.ended)


def _sort_steps(steps: list[RawStep]) -> list[RawStep]:
    """Prefer an explicit ordering key (`dotted_order`), then start time, then input order."""
    indexed = list(enumerate(steps))
    if any(step.order_key for _, step in indexed):
        return [
            step
            for _, step in sorted(
                indexed,
                key=lambda pair: (pair[1].order_key is None, pair[1].order_key or "", pair[0]),
            )
        ]
    return [
        step
        for _, step in sorted(
            indexed,
            key=lambda pair: (
                pair[1].started is None,
                pair[1].started or datetime.min.replace(tzinfo=None),
                pair[0],
            ),
        )
    ]


# --- outcome ------------------------------------------------------------------------------------


def derive_outcome(raw: RawRun, steps: list[Step]) -> Outcome:
    """Deterministic precedence, documented in docs/importers.md:

    1. an explicit status from the source wins
    2. a run-level error means `error`
    3. a failing step with no run output means `error`
    4. any run output means `success`
    5. otherwise `unknown`

    `outcome.error` describes why the *run* failed, so it is set only when the status is `error`.
    A run that recovered from a failing step stays `success`; the step keeps its own `error`, and
    `meta.n_step_errors` plus `TraceRun.has_error` still expose that something went wrong inside.
    """
    output = to_text(raw.output, OUTPUT_LIMIT)
    error = raw.error or next((step.error for step in reversed(steps) if step.error), None)

    if raw.status is not None:
        status = raw.status
    elif raw.error:
        status = "error"
    elif error and not output:
        status = "error"
    elif output:
        status = "success"
    else:
        status = "unknown"

    return Outcome(status=status, output=output, error=error if status == "error" else None)


# --- entry point --------------------------------------------------------------------------------


def normalize_run(raw: RawRun) -> TraceRun:
    ordered = _sort_steps(list(raw.steps))

    steps = [
        Step(
            kind=step.kind,
            name=step.name,
            args_preview=make_preview(step.args),
            output_preview=make_preview(step.output),
            latency=_step_latency(step),
            error=step.error,
            args_full=step.args,
            output_full=step.output,
        )
        for step in ordered
    ]

    duration = _duration_ms(raw.started, raw.ended)
    if duration is None:
        measured = [step.latency for step in steps if step.latency is not None]
        duration = round(sum(measured), 3) if measured else None

    meta = dict(raw.meta)
    meta.update(
        {
            "n_steps": len(steps),
            "n_llm": sum(1 for s in steps if s.kind == "llm"),
            "n_tool": sum(1 for s in steps if s.kind == "tool"),
            "n_handoff": sum(1 for s in steps if s.kind == "handoff"),
            "n_step_errors": sum(1 for s in steps if s.error),
        }
    )

    return TraceRun(
        run_id=raw.run_id,
        source=raw.source,
        started=raw.started,
        input=to_text(raw.input, INPUT_LIMIT),
        steps=steps,
        outcome=derive_outcome(raw, steps),
        meta=meta,
        duration=duration,
    )


def normalize_runs(raws: list[RawRun]) -> list[TraceRun]:
    return [normalize_run(raw) for raw in raws]
