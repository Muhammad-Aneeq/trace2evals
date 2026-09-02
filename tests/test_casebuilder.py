"""Label-derived defaults (spec 03 F4: "sensible defaults pre-filled from labels")."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from t2e.casebuilder import build_case_payload, suggest_expectations, suggest_tags
from t2e.normalizer import normalize_run
from t2e.schemas import RawRun, RawStep

BASE = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


def make_run(
    *,
    output: str = "Root cause: partial payment. Evidence: INV-2026-0881, GL-88213.",
    tools: list[tuple[str, str | None]] | None = None,
    source: str = "otel",
    handoff: bool = False,
):
    """`tools` is a list of (name, error) pairs so a failing call can be expressed."""
    steps: list[RawStep] = [
        RawStep(kind="llm", name="gpt-4o-mini", args="plan", output="planning", started=BASE)
    ]
    for index, (name, error) in enumerate(tools or []):
        steps.append(
            RawStep(
                kind="tool",
                name=name,
                args={"invoice_id": "INV-1"},
                output=None if error else {"ok": True},
                error=error,
                started=BASE + timedelta(seconds=index + 1),
            )
        )
    if handoff:
        steps.append(RawStep(kind="handoff", name="fx_specialist", started=BASE + timedelta(minutes=1)))

    return normalize_run(
        RawRun(
            run_id="r1",
            source=source,  # type: ignore[arg-type]
            started=BASE,
            ended=BASE + timedelta(seconds=6),
            input="Bank transaction BNK-1 is unmatched. Investigate.",
            output=output,
            steps=steps,
        )
    )


def kinds(expectations):
    return [item["kind"] for item in expectations]


# --- tag -> assertion mapping -------------------------------------------------------------------


def test_wrong_tool_proposes_must_call_tool_naming_the_failing_tool():
    run = make_run(tools=[("search_counterparty", None), ("get_invoice", "NotFoundError")])
    proposals = suggest_expectations(run, "wrong", ["wrong_tool"])

    assert kinds(proposals) == ["must_call_tool"]
    # The failing call is the strongest hint at what the agent should have got right.
    assert proposals[0]["tool"] == "get_invoice"
    assert "wrong_tool" in proposals[0]["note"]


def test_wrong_tool_falls_back_to_the_first_investigative_tool():
    run = make_run(tools=[("get_gl_entries", None)])
    (proposal,) = suggest_expectations(run, "wrong", ["wrong_tool"])

    assert proposal["tool"] == "get_gl_entries"


def test_escalation_tools_are_not_proposed_as_the_investigative_tool():
    """`flag_exception` is how you escalate, not the tool the agent should have investigated with."""
    run = make_run(tools=[("flag_exception", None), ("get_invoice", None)])
    (proposal,) = suggest_expectations(run, "wrong", ["wrong_tool"])

    assert proposal["tool"] == "get_invoice"


def test_bad_args_proposes_the_call_with_its_own_reasoning():
    run = make_run(tools=[("get_gl_entries", None)])
    (proposal,) = suggest_expectations(run, "wrong", ["bad_args"])

    assert proposal["kind"] == "must_call_tool"
    assert "bad_args" in proposal["note"]


def test_ungrounded_proposes_must_cite_with_a_minimum():
    run = make_run()
    (proposal,) = suggest_expectations(run, "wrong", ["ungrounded"])

    assert proposal["kind"] == "must_cite"
    assert proposal["min_count"] == 1
    assert "sources" not in proposal


def test_hallucinated_fact_pins_the_evidence_ids_seen_in_the_run():
    run = make_run(output="Matched. Evidence: INV-2026-0881, GL-88213, PO-77120.")
    (proposal,) = suggest_expectations(run, "wrong", ["hallucinated_fact"])

    assert proposal["kind"] == "must_cite"
    assert proposal["sources"] == ["INV-2026-0881", "GL-88213", "PO-77120"]


def test_hallucinated_fact_without_any_ids_falls_back_to_min_count():
    run = make_run(output="The controller approved it in March.")
    (proposal,) = suggest_expectations(run, "wrong", ["hallucinated_fact"])

    assert proposal["min_count"] == 1
    assert "sources" not in proposal


def test_no_escalation_proposes_must_escalate():
    (proposal,) = suggest_expectations(make_run(), "wrong", ["no_escalation"])

    assert proposal["kind"] == "must_escalate"
    assert "hand off" in proposal["note"]


def test_format_break_proposes_a_regex_matching_json_framing():
    run = make_run(output='{"root_cause": "partial_payment"}')
    (proposal,) = suggest_expectations(run, "wrong", ["format_break"])

    assert proposal["kind"] == "output_matches_regex"
    assert proposal["pattern"] == r"^\s*[\{\[]"


def test_format_break_on_prose_pins_an_evidence_id():
    run = make_run(output="Matched against INV-2026-0881 as expected.")
    (proposal,) = suggest_expectations(run, "wrong", ["format_break"])

    # Assert the behaviour, not the literal text: `re.escape` escapes the hyphens, so a substring
    # check on the pattern would be testing the escaping rather than the intent.
    assert re.search(proposal["pattern"], run.outcome.output)
    assert not re.search(proposal["pattern"], "a different answer entirely")


def test_other_tag_proposes_nothing_because_a_machine_cannot_infer_it():
    assert suggest_expectations(make_run(), "wrong", ["other"]) == []


def test_multiple_tags_produce_multiple_assertions_without_duplicates():
    run = make_run(tools=[("get_invoice", None)])
    proposals = suggest_expectations(
        run, "wrong", ["wrong_tool", "bad_args", "ungrounded", "no_escalation"]
    )

    # wrong_tool and bad_args both point at must_call_tool: it must appear once, not twice.
    assert kinds(proposals).count("must_call_tool") == 1
    assert set(kinds(proposals)) == {"must_call_tool", "must_cite", "must_escalate"}


def test_every_proposal_explains_itself():
    run = make_run(tools=[("get_invoice", None)])
    proposals = suggest_expectations(run, "wrong", ["wrong_tool", "ungrounded", "no_escalation"])

    assert all(item.get("note") for item in proposals)


# --- the `right` verdict ------------------------------------------------------------------------


def test_a_correct_run_becomes_a_regression_guard():
    run = make_run(tools=[("get_invoice", None)])
    proposals = suggest_expectations(run, "right", [])

    assert set(kinds(proposals)) == {"must_call_tool", "must_cite"}
    assert all("regression guard" in item["note"] for item in proposals)


def test_a_correct_run_with_no_tools_or_citations_proposes_nothing():
    run = make_run(output="Below the materiality threshold.", tools=[])
    assert suggest_expectations(run, "right", []) == []


def test_a_tagged_run_does_not_also_get_regression_guards():
    """Tag-driven assertions are the point; piling guards on top would bury them."""
    run = make_run(tools=[("get_invoice", None)])
    proposals = suggest_expectations(run, "right", ["ungrounded"])

    assert kinds(proposals) == ["must_cite"]


def test_unlabeled_run_proposes_nothing():
    assert suggest_expectations(make_run(tools=[("get_invoice", None)]), None, []) == []


# --- tags / payload -----------------------------------------------------------------------------


def test_tags_carry_provenance_for_later_slicing():
    run = make_run(source="langsmith", handoff=True)
    tags = suggest_tags(run, ["wrong_tool"])

    assert "wrong_tool" in tags
    assert "source:langsmith" in tags
    assert "multi_agent" in tags


def test_had_error_tag_is_added_for_failed_runs():
    run = make_run(output="", tools=[("propose_match", "503 from upstream")])
    assert "had_error" in suggest_tags(run, [])


def test_build_case_payload_is_ready_to_edit():
    run = make_run(tools=[("get_invoice", "NotFoundError")])
    payload = build_case_payload(run, verdict="wrong", tags=["wrong_tool"], version="v2")

    assert payload["version"] == "v2"
    assert payload["run_id"] == "r1"
    assert payload["input"].startswith("Bank transaction BNK-1")
    assert kinds(payload["expectations"]) == ["must_call_tool"]
    assert "source:otel" in payload["tags"]


def test_citation_defaults_are_capped_to_stay_usable():
    """A case demanding a dozen exact ids is unusable, so the default proposal is bounded."""
    ids = " ".join(f"INV-2026-{n:04d}" for n in range(10))
    run = make_run(output=f"Evidence: {ids}")
    (proposal,) = suggest_expectations(run, "wrong", ["hallucinated_fact"])

    assert len(proposal["sources"]) == 4
