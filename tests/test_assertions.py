"""All five assertion kinds, pass and fail paths, plus the v1 cap itself."""

from __future__ import annotations

import pytest

from t2e.assertions import (
    AgentRun,
    assert_all,
    check,
    check_all,
    must_call_tool,
    must_cite,
    must_escalate,
    output_matches_regex,
    output_matches_schema,
)
from t2e.schemas import ASSERTION_KINDS


def test_v1_is_capped_at_five_assertion_kinds():
    """spec 03 sec 14: "v1 = 5 assertion kinds max". A sixth needs a spec argument, not a commit."""
    assert len(ASSERTION_KINDS) == 5
    assert set(ASSERTION_KINDS) == {
        "must_call_tool",
        "must_escalate",
        "must_cite",
        "output_matches_regex",
        "output_matches_schema",
    }


# --- adapter input flexibility ------------------------------------------------------------------


def test_adapter_may_return_a_string_a_dict_or_an_agent_run():
    assert AgentRun.from_any("just text").output == "just text"

    from_dict = AgentRun.from_any(
        {"output": "x", "tool_calls": ["get_invoice"], "citations": ["INV-1"], "escalated": True}
    )
    assert from_dict.tool_calls == ["get_invoice"]
    assert from_dict.escalated is True

    passthrough = AgentRun(output="y")
    assert AgentRun.from_any(passthrough) is passthrough


def test_tool_calls_accept_objects_as_well_as_names():
    run = AgentRun.from_any({"output": "", "tool_calls": [{"name": "get_invoice"}, "flag_exception"]})
    assert run.tool_calls == ["get_invoice", "flag_exception"]


def test_unsupported_adapter_return_is_a_type_error():
    with pytest.raises(TypeError):
        AgentRun.from_any(42)


# --- 1. must_call_tool --------------------------------------------------------------------------


def test_must_call_tool_passes_when_called():
    run = AgentRun(tool_calls=["search_counterparty", "get_invoice"])
    assert must_call_tool(run, "get_invoice")


def test_must_call_tool_fails_when_absent_and_says_what_was_called():
    run = AgentRun(tool_calls=["get_gl_entries"])
    outcome = must_call_tool(run, "get_bank_transactions")

    assert not outcome
    assert "get_bank_transactions" in outcome.message
    assert "get_gl_entries" in outcome.message


def test_must_call_tool_fails_clearly_when_no_tools_were_called():
    outcome = must_call_tool(AgentRun(), "get_invoice")
    assert not outcome
    assert "no tools" in outcome.message


def test_must_call_tool_allow_any_accepts_a_list():
    run = AgentRun(tool_calls=["get_gl_entries"])
    assert must_call_tool(run, "get_invoice, get_gl_entries", allow_any=True)
    assert not must_call_tool(run, "get_invoice, get_period_summary", allow_any=True)


# --- 2. must_escalate ---------------------------------------------------------------------------


def test_explicit_escalation_flag_wins_over_everything():
    assert must_escalate(AgentRun(escalated=True, output="no keywords here"))
    # An adapter that says "did not escalate" is authoritative even if the text sounds like it did.
    assert not must_escalate(AgentRun(escalated=False, output="I will escalate this"))


def test_escalation_tool_call_counts():
    outcome = must_escalate(AgentRun(tool_calls=["get_invoice", "flag_exception"]))
    assert outcome
    assert "flag_exception" in outcome.message


def test_escalation_language_is_the_last_resort():
    outcome = must_escalate(AgentRun(output="Insufficient evidence; referring for human review."))
    assert outcome
    assert "escalation" in outcome.message


def test_must_escalate_fails_on_a_confident_unescalated_answer():
    """The failure this assertion exists to catch: the agent guessed instead of asking."""
    run = AgentRun(
        output="The payment relates to PO-99001 approved by the regional controller.",
        tool_calls=["get_invoice"],
    )
    outcome = must_escalate(run)

    assert not outcome
    assert "no escalation signal" in outcome.message


def test_escalation_tools_can_be_overridden():
    run = AgentRun(tool_calls=["raise_to_treasury"])
    assert not must_escalate(run)
    assert must_escalate(run, tools=["raise_to_treasury"], keywords=[])


# --- 3. must_cite -------------------------------------------------------------------------------


def test_must_cite_uses_adapter_citations_when_present():
    assert must_cite(AgentRun(citations=["INV-2026-0881"]))


def test_must_cite_falls_back_to_evidence_ids_in_the_output():
    run = AgentRun(output="Residual 1,187.50 remains. Evidence: INV-2026-0881, GL-88213.")
    outcome = must_cite(run, min_count=2)

    assert outcome
    assert "2 citation" in outcome.message


def test_must_cite_fails_on_an_ungrounded_answer():
    outcome = must_cite(AgentRun(output="This is a partial payment, clearly."))
    assert not outcome
    assert "found none" in outcome.message


def test_must_cite_with_required_sources_names_what_is_missing():
    run = AgentRun(output="Matched against INV-2026-0881.")
    outcome = must_cite(run, ["INV-2026-0881", "GL-88213"])

    assert not outcome
    assert "GL-88213" in outcome.message
    assert "INV-2026-0881" not in outcome.message.split("missing citation(s):")[1]


def test_must_cite_with_required_sources_passes_when_all_present():
    run = AgentRun(output="Evidence: INV-2026-0881, GL-88213, PO-77120.")
    assert must_cite(run, ["INV-2026-0881", "GL-88213"])


def test_min_count_higher_than_available_fails():
    run = AgentRun(output="Evidence: INV-1.")
    assert not must_cite(run, min_count=3)


# --- 4. output_matches_regex --------------------------------------------------------------------


def test_regex_pass_and_fail():
    run = AgentRun(output="Root cause: partial payment")
    assert output_matches_regex(run, r"partial payment")
    assert not output_matches_regex(run, r"duplicate")


def test_regex_flags():
    run = AgentRun(output="ROOT CAUSE: PARTIAL PAYMENT")
    assert not output_matches_regex(run, r"partial payment")
    assert output_matches_regex(run, r"partial payment", flags="i")


def test_regex_dotall_flag_spans_lines():
    run = AgentRun(output="line one\nline two")
    assert output_matches_regex(run, r"one.*two", flags="s")


def test_invalid_regex_fails_loudly_rather_than_passing():
    """An authoring mistake must never be indistinguishable from a passing assertion."""
    outcome = output_matches_regex(AgentRun(output="anything"), r"([unclosed")

    assert not outcome
    assert "invalid regex" in outcome.message


def test_regex_failure_message_includes_the_output():
    outcome = output_matches_regex(AgentRun(output="the actual answer"), r"nope")
    assert "the actual answer" in outcome.message


# --- 5. output_matches_schema -------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "required": ["root_cause", "evidence"],
    "properties": {
        "root_cause": {"type": "string", "enum": ["partial_payment", "duplicate", "fx"]},
        "evidence": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
}


def test_schema_pass():
    output = '{"root_cause": "partial_payment", "evidence": ["INV-1"], "confidence": 0.86}'
    assert output_matches_schema(AgentRun(output=output), SCHEMA)


def test_schema_tolerates_a_fenced_code_block():
    """Models wrap JSON in fences constantly; failing on that would be noise, not signal."""
    output = '```json\n{"root_cause": "duplicate", "evidence": ["INV-2"]}\n```'
    assert output_matches_schema(AgentRun(output=output), SCHEMA)


def test_schema_fails_on_non_json():
    outcome = output_matches_schema(AgentRun(output="Root cause: partial payment"), SCHEMA)
    assert not outcome
    assert "not valid JSON" in outcome.message


def test_schema_reports_missing_required_property():
    outcome = output_matches_schema(AgentRun(output='{"root_cause": "fx"}'), SCHEMA)
    assert not outcome
    assert "missing required property 'evidence'" in outcome.message


def test_schema_reports_wrong_type_with_a_path():
    outcome = output_matches_schema(
        AgentRun(output='{"root_cause": "fx", "evidence": "INV-1"}'), SCHEMA
    )
    assert not outcome
    assert "$.evidence: expected array, got string" in outcome.message


def test_schema_enforces_enum_min_items_and_bounds():
    bad_enum = output_matches_schema(
        AgentRun(output='{"root_cause": "aliens", "evidence": ["INV-1"]}'), SCHEMA
    )
    assert "not one of" in bad_enum.message

    empty_array = output_matches_schema(
        AgentRun(output='{"root_cause": "fx", "evidence": []}'), SCHEMA
    )
    assert "at least 1 item" in empty_array.message

    out_of_range = output_matches_schema(
        AgentRun(output='{"root_cause": "fx", "evidence": ["INV-1"], "confidence": 1.5}'), SCHEMA
    )
    assert "above the maximum" in out_of_range.message


def test_schema_distinguishes_booleans_from_numbers():
    """bool is an int subclass in Python; JSON Schema treats them as different types."""
    outcome = output_matches_schema(
        AgentRun(output='{"n": true}'), {"type": "object", "properties": {"n": {"type": "number"}}}
    )
    assert not outcome
    assert "got boolean" in outcome.message


def test_unsupported_schema_keyword_is_reported_not_ignored():
    """Silently skipping a keyword would make the assertion quietly weaker than it looks."""
    outcome = output_matches_schema(
        AgentRun(output="{}"), {"type": "object", "patternProperties": {"^x": {}}}
    )
    assert not outcome
    assert "unsupported JSON Schema keyword" in outcome.message
    assert "patternProperties" in outcome.message


def test_nested_object_validation():
    schema = {
        "type": "object",
        "properties": {"meta": {"type": "object", "required": ["id"]}},
    }
    outcome = output_matches_schema(AgentRun(output='{"meta": {}}'), schema)
    assert "$.meta: missing required property 'id'" in outcome.message


# --- dispatch -----------------------------------------------------------------------------------


def test_check_dispatches_each_kind():
    run = AgentRun(
        output='{"ok": true}',
        tool_calls=["get_invoice", "flag_exception"],
        citations=["INV-1"],
    )
    expectations = [
        {"kind": "must_call_tool", "tool": "get_invoice"},
        {"kind": "must_escalate"},
        {"kind": "must_cite", "min_count": 1},
        {"kind": "output_matches_regex", "pattern": "ok"},
        {"kind": "output_matches_schema", "schema": {"type": "object", "required": ["ok"]}},
    ]

    outcomes = check_all(run, expectations)
    assert len(outcomes) == 5
    assert all(outcomes), [o.message for o in outcomes if not o]


def test_unknown_kind_fails_and_lists_the_five():
    outcome = check(AgentRun(), {"kind": "vibes_are_off"})
    assert not outcome
    assert "unknown assertion kind" in outcome.message
    assert "must_call_tool" in outcome.message


def test_missing_required_parameter_is_reported():
    outcome = check(AgentRun(), {"kind": "must_call_tool"})
    assert not outcome
    assert "missing required parameter 'tool'" in outcome.message


def test_note_is_not_treated_as_a_parameter():
    """Cases carry a `note` explaining why an assertion exists; it must not break dispatch."""
    outcome = check(
        AgentRun(tool_calls=["get_invoice"]),
        {"kind": "must_call_tool", "tool": "get_invoice", "note": "because the tag said so"},
    )
    assert outcome


# --- assert_all ---------------------------------------------------------------------------------


def test_assert_all_is_silent_when_everything_passes():
    assert_all(AgentRun(tool_calls=["get_invoice"]), [{"kind": "must_call_tool", "tool": "get_invoice"}])


def test_assert_all_reports_every_failure_at_once():
    with pytest.raises(AssertionError) as excinfo:
        assert_all(
            AgentRun(output="ungrounded guess"),
            [
                {"kind": "must_call_tool", "tool": "get_invoice"},
                {"kind": "must_cite"},
                {"kind": "must_escalate"},
            ],
            case_id="v1-0007",
        )

    message = str(excinfo.value)
    assert "case v1-0007" in message
    assert "3 of 3 expectation(s) failed" in message
    # Each failure is named, so one run tells you everything that is wrong.
    for kind in ("must_call_tool", "must_cite", "must_escalate"):
        assert kind in message


def test_assert_all_with_no_expectations_passes_but_asserts_nothing():
    """Documented behaviour: the generated suite has a separate guard against empty expectations."""
    assert_all(AgentRun(), [])
