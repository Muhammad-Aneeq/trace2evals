"""Normalizer unit tests: kind mapping, ordering, latency, preview truncation, outcome."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from t2e.normalizer import derive_outcome, make_preview, normalize_run, to_text
from t2e.schemas import PREVIEW_LIMIT, RawRun, RawStep


def _at(second: float) -> datetime:
    return datetime(2026, 8, 15, 9, 0, 0, tzinfo=UTC).replace(microsecond=0) + _delta(second)


def _delta(seconds: float):
    from datetime import timedelta

    return timedelta(seconds=seconds)


def _run(**kwargs) -> RawRun:
    base = {"run_id": "r1", "source": "otel"}
    return RawRun(**(base | kwargs))


# --- previews -----------------------------------------------------------------------------------


def test_preview_is_truncated_at_the_limit():
    long_text = "x" * (PREVIEW_LIMIT + 500)
    preview = make_preview(long_text)

    assert len(preview) == PREVIEW_LIMIT
    assert preview.endswith("…")


def test_preview_collapses_whitespace():
    assert make_preview("a\n\n  b\tc") == "a b c"


def test_short_text_is_untouched():
    assert make_preview("all good") == "all good"


def test_none_renders_as_empty_string():
    assert make_preview(None) == ""


def test_wrapper_keys_are_unwrapped_but_meaningful_keys_are_kept():
    assert to_text({"input": "the question"}, 100) == "the question"
    # A meaningful key stays visible: tool args are unreadable without it.
    assert to_text({"invoice_id": "INV-1"}, 100) == '{"invoice_id":"INV-1"}'


def test_chat_messages_render_as_role_lines():
    messages = [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}]
    assert to_text(messages, 200) == "system: be terse\nuser: hi"


def test_multipart_content_blocks_keep_only_text():
    messages = [{"role": "user", "content": [{"type": "text", "text": "part one"}]}]
    assert to_text(messages, 200) == "user: part one"


def test_langchain_generations_are_unwrapped():
    # LLMResult nests one list per prompt.
    assert to_text({"generations": [[{"text": "answer"}]]}, 200) == "answer"
    assert to_text({"generations": [{"text": "answer"}]}, 200) == "answer"


def test_json_fallback_is_sorted_for_stability():
    assert to_text({"b": 1, "a": 2}, 100) == '{"a":2,"b":1}'


# --- latency ------------------------------------------------------------------------------------


def test_latency_is_computed_in_milliseconds():
    run = normalize_run(
        _run(steps=[RawStep(kind="llm", name="m", started=_at(0), ended=_at(1.25))])
    )
    assert run.steps[0].latency == pytest.approx(1250.0)


def test_explicit_latency_wins_over_timestamps():
    run = normalize_run(
        _run(
            steps=[
                RawStep(kind="tool", name="t", started=_at(0), ended=_at(5), latency_ms=42.0)
            ]
        )
    )
    assert run.steps[0].latency == pytest.approx(42.0)


def test_negative_duration_is_reported_as_unknown():
    """Clock skew should yield no number rather than a nonsensical negative one."""
    run = normalize_run(
        _run(steps=[RawStep(kind="llm", name="m", started=_at(5), ended=_at(0))])
    )
    assert run.steps[0].latency is None


def test_missing_timestamps_yield_none():
    run = normalize_run(_run(steps=[RawStep(kind="llm", name="m")]))
    assert run.steps[0].latency is None


def test_run_duration_prefers_run_timestamps():
    run = normalize_run(
        _run(
            started=_at(0),
            ended=_at(10),
            steps=[RawStep(kind="llm", name="m", started=_at(1), ended=_at(2))],
        )
    )
    assert run.duration == pytest.approx(10_000.0)


def test_run_duration_falls_back_to_the_sum_of_step_latencies():
    run = normalize_run(
        _run(
            steps=[
                RawStep(kind="llm", name="m", started=_at(0), ended=_at(1)),
                RawStep(kind="tool", name="t", started=_at(1), ended=_at(1.5)),
            ]
        )
    )
    assert run.duration == pytest.approx(1500.0)


# --- ordering -----------------------------------------------------------------------------------


def test_steps_are_ordered_by_start_time():
    run = normalize_run(
        _run(
            steps=[
                RawStep(kind="tool", name="second", started=_at(2)),
                RawStep(kind="llm", name="first", started=_at(1)),
            ]
        )
    )
    assert [s.name for s in run.steps] == ["first", "second"]


def test_order_key_beats_timestamps():
    """dotted_order is authoritative: it disambiguates identical timestamps."""
    run = normalize_run(
        _run(
            steps=[
                RawStep(kind="tool", name="b", started=_at(1), order_key="20260815T02"),
                RawStep(kind="llm", name="a", started=_at(1), order_key="20260815T01"),
            ]
        )
    )
    assert [s.name for s in run.steps] == ["a", "b"]


def test_input_order_is_preserved_when_nothing_else_sorts():
    run = normalize_run(
        _run(steps=[RawStep(kind="llm", name="x"), RawStep(kind="tool", name="y")])
    )
    assert [s.name for s in run.steps] == ["x", "y"]


# --- outcome ------------------------------------------------------------------------------------


def test_explicit_status_wins_over_derivation():
    """Output present would normally derive `success`; an explicit status overrides that."""
    outcome = derive_outcome(_run(status="unknown", output="text"), [])
    assert outcome.status == "unknown"
    assert outcome.output == "text"


def test_run_level_error_means_error():
    outcome = derive_outcome(_run(error="boom", output="partial text"), [])
    assert outcome.status == "error"
    assert outcome.error == "boom"


def test_failing_step_with_no_output_means_error():
    run = normalize_run(_run(steps=[RawStep(kind="tool", name="t", error="tool blew up")]))
    assert run.outcome.status == "error"
    assert run.outcome.error == "tool blew up"


def test_recovered_step_failure_stays_successful_but_stays_visible():
    """A run that produced an answer despite a failed step is a success with the failure exposed."""
    run = normalize_run(
        _run(output="the answer", steps=[RawStep(kind="tool", name="t", error="404")])
    )
    assert run.outcome.status == "success"
    assert run.outcome.error is None  # the run did not fail
    assert run.has_error  # but something inside it did
    assert run.meta["n_step_errors"] == 1


def test_no_output_and_no_error_is_unknown():
    assert normalize_run(_run()).outcome.status == "unknown"


# --- meta counters ------------------------------------------------------------------------------


def test_meta_counts_each_step_kind():
    run = normalize_run(
        _run(
            meta={"trace_id": "t"},
            steps=[
                RawStep(kind="llm", name="a"),
                RawStep(kind="tool", name="b"),
                RawStep(kind="tool", name="c"),
                RawStep(kind="handoff", name="d"),
            ],
        )
    )
    assert run.meta["n_steps"] == 4
    assert run.meta["n_llm"] == 1
    assert run.meta["n_tool"] == 2
    assert run.meta["n_handoff"] == 1
    assert run.meta["trace_id"] == "t"  # parser-supplied keys survive


def test_full_payloads_are_kept_alongside_previews():
    payload = {"invoice_id": "INV-1", "nested": {"deep": [1, 2, 3]}}
    run = normalize_run(_run(steps=[RawStep(kind="tool", name="t", args=payload)]))

    assert run.steps[0].args_full == payload
    assert "INV-1" in run.steps[0].args_preview


def test_spec_dump_emits_exactly_the_f2_contract():
    run = normalize_run(
        _run(steps=[RawStep(kind="llm", name="m", args="in", output="out", error="bad")])
    )
    dumped = run.spec_dump()

    assert set(dumped) == {
        "run_id",
        "source",
        "started",
        "input",
        "steps",
        "outcome",
        "meta",
    }
    assert set(dumped["steps"][0]) == {
        "kind",
        "name",
        "args_preview",
        "output_preview",
        "latency",
        "error",
    }


def test_spec_dump_omits_error_when_absent():
    run = normalize_run(_run(steps=[RawStep(kind="llm", name="m")]))
    assert "error" not in run.spec_dump()["steps"][0]
