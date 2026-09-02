"""Turning a labeled run into an eval case, with defaults derived from the label.

Spec 03 F4 asks for "sensible defaults pre-filled from labels". That phrase is the whole point of the
screen: a human has already said *what* went wrong by picking a failure tag, so the tool should propose
the assertion that would have caught it. The human edits and confirms; nothing is auto-committed.

The tag -> assertion mapping:

    wrong_tool         -> must_call_tool     (the tool it should have called, guessed from the trace)
    bad_args           -> must_call_tool     (same tool, but the args were wrong; regex on output too)
    ungrounded         -> must_cite          (evidence ids seen in this run become required sources)
    hallucinated_fact  -> must_cite          (an invented fact is an ungrounded claim with confidence)
    no_escalation      -> must_escalate
    format_break       -> output_matches_regex
    other              -> nothing proposed; the note says what a machine cannot infer

A `right` verdict proposes a regression guard instead: keep calling the tools it called, keep citing.
"""

from __future__ import annotations

import re
from typing import Any

from t2e.assertions import DEFAULT_CITATION_PATTERN, DEFAULT_ESCALATION_TOOLS
from t2e.schemas import TraceRun

#: Tools that represent escalation rather than investigation, excluded when guessing "the right tool".
_ESCALATION_TOOLS = set(DEFAULT_ESCALATION_TOOLS)

#: Cap on required citations proposed by default: a case demanding twelve ids is unusable.
_MAX_DEFAULT_CITATIONS = 4


def _tools_called(run: TraceRun) -> list[str]:
    seen: list[str] = []
    for step in run.steps:
        if step.kind == "tool" and step.name not in seen:
            seen.append(step.name)
    return seen


def _failing_tools(run: TraceRun) -> list[str]:
    return [step.name for step in run.steps if step.kind == "tool" and step.error]


def _citations_in(run: TraceRun) -> list[str]:
    """Evidence ids that actually appear in this run's output, in first-seen order."""
    found: list[str] = []
    for candidate in DEFAULT_CITATION_PATTERN.findall(run.outcome.output or ""):
        if candidate not in found:
            found.append(candidate)
    return found[:_MAX_DEFAULT_CITATIONS]


def suggest_expectations(
    run: TraceRun, verdict: str | None, tags: list[str] | None = None
) -> list[dict[str, Any]]:
    """Propose assertions for a labeled run. Every one carries a `note` explaining why it is here."""
    tags = tags or []
    proposals: list[dict[str, Any]] = []

    def add(expectation: dict[str, Any]) -> None:
        # Never propose the same assertion twice; the tag set overlaps by design.
        if expectation not in proposals:
            proposals.append(expectation)

    tools = _tools_called(run)
    investigative = [tool for tool in tools if tool not in _ESCALATION_TOOLS]

    if "wrong_tool" in tags or "bad_args" in tags:
        # A failing tool call is the strongest hint at what the agent *should* have got right.
        candidate = next(iter(_failing_tools(run)), None) or next(iter(investigative), None)
        if candidate:
            reason = (
                "the run was tagged wrong_tool: name the tool the agent should have called"
                if "wrong_tool" in tags
                else "the run was tagged bad_args: assert the call happens, then tighten the args"
            )
            add({"kind": "must_call_tool", "tool": candidate, "note": reason})

    if "ungrounded" in tags or "hallucinated_fact" in tags:
        sources = _citations_in(run)
        expectation: dict[str, Any] = {
            "kind": "must_cite",
            "note": (
                "tagged hallucinated_fact: require the evidence the claim depends on"
                if "hallucinated_fact" in tags
                else "tagged ungrounded: require at least one cited evidence id"
            ),
        }
        # Only pin specific ids when the run actually produced some; otherwise require any citation.
        if sources and "hallucinated_fact" in tags:
            expectation["sources"] = sources
        else:
            expectation["min_count"] = 1
        add(expectation)

    if "no_escalation" in tags:
        add(
            {
                "kind": "must_escalate",
                "note": "tagged no_escalation: the agent must hand off instead of guessing",
            }
        )

    if "format_break" in tags:
        add(
            {
                "kind": "output_matches_regex",
                "pattern": _suggest_format_pattern(run),
                "note": "tagged format_break: pin the shape the consumer depends on",
            }
        )

    if verdict == "right" and not proposals:
        # A correct run is worth freezing as a regression guard.
        if investigative:
            add(
                {
                    "kind": "must_call_tool",
                    "tool": investigative[0],
                    "note": "regression guard: this correct run called this tool",
                }
            )
        if _citations_in(run):
            add(
                {
                    "kind": "must_cite",
                    "min_count": 1,
                    "note": "regression guard: this correct run cited its evidence",
                }
            )

    return proposals


def _suggest_format_pattern(run: TraceRun) -> str:
    """Guess the shape the output should have had, from what it nearly was."""
    output = (run.outcome.output or "").strip()
    if output.startswith(("{", "[")):
        # It tried to be JSON, so require JSON-ish framing; a schema assertion is the stronger follow-up.
        return r"^\s*[\{\[]"
    if citations := DEFAULT_CITATION_PATTERN.findall(output):
        return rf"\b{re.escape(citations[0])}\b"
    return r"\S"


def suggest_tags(run: TraceRun, label_tags: list[str] | None = None) -> list[str]:
    """Case tags: the failure tags plus provenance, so a suite can be sliced later."""
    tags = list(label_tags or [])
    tags.append(f"source:{run.source}")
    if run.has_error:
        tags.append("had_error")
    if any(step.kind == "handoff" for step in run.steps):
        tags.append("multi_agent")
    return tags


def build_case_payload(
    run: TraceRun,
    *,
    verdict: str | None,
    tags: list[str] | None,
    version: str,
) -> dict[str, Any]:
    """The full pre-filled case a human then edits on the Cases screen."""
    return {
        "version": version,
        "run_id": run.run_id,
        "input": run.input,
        "expectations": suggest_expectations(run, verdict, tags),
        "tags": suggest_tags(run, tags),
    }
