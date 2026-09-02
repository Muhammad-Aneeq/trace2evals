"""Pydantic v2 models.

The normalized model is fixed by spec 03 F2 and must not drift:

    {run_id, source, started, input,
     steps[ {kind: llm|tool|handoff, name, args_preview, output_preview, latency, error?} ],
     outcome, meta}

`Step`/`TraceRun` carry a few extra storage/UI fields (full payloads, duration) beyond that
contract. `spec_dump()` on either emits *exactly* the F2 shape and is what the snapshot tests
assert against, so the contract is verified independently of the storage extras.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- vocabularies -------------------------------------------------------------------------------

StepKind = Literal["llm", "tool", "handoff"]
Source = Literal["otel", "langsmith"]
Verdict = Literal["right", "wrong", "partial"]
OutcomeStatus = Literal["success", "error", "unknown"]

#: The failure taxonomy is closed in v1 (spec 03 F3).
FAILURE_TAGS: tuple[str, ...] = (
    "wrong_tool",
    "bad_args",
    "ungrounded",
    "no_escalation",
    "format_break",
    "hallucinated_fact",
    "other",
)

#: The assertion language is capped at 5 kinds in v1 (spec 03 sec 14 risk register).
ASSERTION_KINDS: tuple[str, ...] = (
    "must_call_tool",
    "must_escalate",
    "must_cite",
    "output_matches_regex",
    "output_matches_schema",
)

#: Step payloads are previews by contract; full payloads are kept in the store for the UI expanders.
PREVIEW_LIMIT = 500
#: A run's input is what eval cases are built from, so it gets a much larger budget than a preview.
INPUT_LIMIT = 4000
#: A run's final output feeds regex/schema assertions, so it is kept effectively whole.
OUTPUT_LIMIT = 20_000


# --- normalized model (spec 03 F2) --------------------------------------------------------------


class Step(BaseModel):
    """One step in a run. The first six fields are the F2 contract."""

    model_config = ConfigDict(extra="forbid")

    kind: StepKind
    name: str
    args_preview: str = ""
    output_preview: str = ""
    #: Wall-clock duration in milliseconds. None when the source gave no usable timestamps.
    latency: float | None = None
    error: str | None = None

    # --- beyond the F2 contract: kept for storage and the UI payload expanders ---
    args_full: Any = None
    output_full: Any = None

    def spec_dump(self) -> dict[str, Any]:
        """Exactly the F2 step shape. `error` is omitted when absent (F2 marks it optional)."""
        out: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "args_preview": self.args_preview,
            "output_preview": self.output_preview,
            "latency": self.latency,
        }
        if self.error is not None:
            out["error"] = self.error
        return out


class Outcome(BaseModel):
    """How the run ended. Serialized into `runs.outcome_json`."""

    model_config = ConfigDict(extra="forbid")

    status: OutcomeStatus = "unknown"
    output: str = ""
    error: str | None = None


class TraceRun(BaseModel):
    """A normalized run. The eight F2 fields are the contract; `duration` is a storage extra."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    source: Source
    started: datetime | None = None
    input: str = ""
    steps: list[Step] = Field(default_factory=list)
    outcome: Outcome = Field(default_factory=Outcome)
    meta: dict[str, Any] = Field(default_factory=dict)

    # --- beyond the F2 contract: powers the duration filter in F3 ---
    duration: float | None = None

    def spec_dump(self) -> dict[str, Any]:
        """Exactly the F2 run shape - what the parser snapshot tests compare."""
        return {
            "run_id": self.run_id,
            "source": self.source,
            "started": self.started.isoformat() if self.started else None,
            "input": self.input,
            "steps": [s.spec_dump() for s in self.steps],
            "outcome": self.outcome.model_dump(),
            "meta": self.meta,
        }

    @property
    def has_error(self) -> bool:
        return self.outcome.status == "error" or any(s.error for s in self.steps)


# --- intermediate model: what parsers emit, before normalization ---------------------------------


class RawStep(BaseModel):
    """A step as the parser found it: full payloads, raw timestamps, no truncation yet."""

    model_config = ConfigDict(extra="forbid")

    kind: StepKind
    name: str
    args: Any = None
    output: Any = None
    started: datetime | None = None
    ended: datetime | None = None
    #: Set only when the source reported a duration directly instead of timestamps.
    latency_ms: float | None = None
    error: str | None = None
    #: Ordering hint that beats timestamps when present (e.g. LangSmith `dotted_order`).
    order_key: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RawRun(BaseModel):
    """A run as the parser found it. `normalizer.normalize_run` turns this into a `TraceRun`."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    source: Source
    started: datetime | None = None
    ended: datetime | None = None
    input: Any = None
    output: Any = None
    error: str | None = None
    #: Explicit status from the source, when it gave one; otherwise derived during normalization.
    status: OutcomeStatus | None = None
    steps: list[RawStep] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


# --- parse reporting (spec 03 F1: "per-record error report") -------------------------------------


class RecordError(BaseModel):
    """One record that could not be used. Never fatal: the rest of the file still imports."""

    model_config = ConfigDict(extra="forbid")

    #: Where the bad record lives, e.g. `line 7` or `resourceSpans[0].scopeSpans[0].spans[2]`.
    locator: str
    reason: str
    #: A short, redaction-safe excerpt to make the problem diagnosable.
    excerpt: str = ""

    def spec_dump(self) -> dict[str, Any]:
        return self.model_dump()


class ParseReport(BaseModel):
    """Per-file outcome of a parse: what worked, what didn't, and what was redacted."""

    model_config = ConfigDict(extra="forbid")

    file: str
    format: str
    records_seen: int = 0
    runs_imported: int = 0
    steps_imported: int = 0
    errors: list[RecordError] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    #: Count of redactions applied on import (spec 03 sec 11).
    redactions: int = 0
    #: Pattern names whose matches looked like PII, driving the warning banner.
    pii_flags: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.runs_imported > 0

    def add_error(self, locator: str, reason: str, excerpt: str = "") -> None:
        self.errors.append(
            RecordError(locator=locator, reason=reason, excerpt=_clip(excerpt, 200))
        )


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
