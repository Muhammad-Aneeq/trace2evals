"""Store: round-trip persistence, the F3 filters, and unlabeled-first ordering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from t2e import store
from t2e.normalizer import normalize_run
from t2e.schemas import RawRun, RawStep

BASE = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)


def make_run(
    run_id: str,
    *,
    source: str = "otel",
    minutes: int = 0,
    duration_s: float = 1.0,
    error: str | None = None,
    steps: list[RawStep] | None = None,
) -> object:
    started = BASE + timedelta(minutes=minutes)
    return normalize_run(
        RawRun(
            run_id=run_id,
            source=source,  # type: ignore[arg-type]
            started=started,
            ended=started + timedelta(seconds=duration_s),
            input=f"input for {run_id}",
            output=None if error else f"output for {run_id}",
            error=error,
            steps=steps
            or [
                RawStep(
                    kind="llm",
                    name="gpt-4o-mini",
                    args={"messages": [{"role": "user", "content": "hello"}]},
                    output="hi",
                    started=started,
                    ended=started + timedelta(milliseconds=500),
                )
            ],
        )
    )


# --- round trip ---------------------------------------------------------------------------------


def test_save_and_reload_preserves_the_model(session):
    original = make_run("r1")
    store.save_run(session, original)

    row = store.get_run(session, "r1")
    assert row is not None
    reloaded = store.run_row_to_trace_run(row)

    assert reloaded.run_id == original.run_id
    assert reloaded.source == original.source
    assert reloaded.started == original.started
    assert reloaded.input == original.input
    assert reloaded.outcome.model_dump() == original.outcome.model_dump()
    assert [s.spec_dump() for s in reloaded.steps] == [s.spec_dump() for s in original.steps]


def test_full_payloads_survive_the_round_trip(session):
    payload = {"invoice_id": "INV-1", "nested": {"deep": [1, 2, 3]}}
    run = make_run(
        "r1", steps=[RawStep(kind="tool", name="get_invoice", args=payload, output={"ok": True})]
    )
    store.save_run(session, run)

    reloaded = store.run_row_to_trace_run(store.get_run(session, "r1"))
    assert reloaded.steps[0].args_full == payload
    assert reloaded.steps[0].output_full == {"ok": True}


def test_reimport_replaces_rather_than_duplicates(session):
    store.save_run(session, make_run("r1"))
    store.save_run(
        session,
        make_run("r1", steps=[RawStep(kind="tool", name="only_step", args={"a": 1})]),
    )

    assert store.count_runs(session) == 1
    row = store.get_run(session, "r1")
    assert [s.name for s in row.steps] == ["only_step"]


def test_step_order_is_stable_across_reload(session):
    steps = [
        RawStep(kind="llm", name="one", started=BASE),
        RawStep(kind="tool", name="two", started=BASE + timedelta(seconds=1)),
        RawStep(kind="llm", name="three", started=BASE + timedelta(seconds=2)),
    ]
    store.save_run(session, make_run("r1", steps=steps))

    row = store.get_run(session, "r1")
    assert [s.idx for s in row.steps] == [0, 1, 2]
    assert [s.name for s in row.steps] == ["one", "two", "three"]


def test_json_columns_are_written_with_sorted_keys(session):
    """Byte-stable JSON is what makes golden-file comparison meaningful."""
    steps = [RawStep(kind="tool", name="t", args={"b": 1, "a": 2})]
    store.save_run(session, make_run("r1", steps=steps))

    row = store.get_run(session, "r1")
    assert row.steps[0].args_json == '{"a": 2, "b": 1}'


# --- filters (spec 03 F3) -----------------------------------------------------------------------


@pytest.fixture
def populated(session):
    store.save_run(session, make_run("otel-fast", source="otel", minutes=0, duration_s=0.5))
    store.save_run(session, make_run("otel-slow", source="otel", minutes=1, duration_s=9.0))
    store.save_run(
        session, make_run("ls-error", source="langsmith", minutes=2, error="it broke")
    )
    store.save_run(session, make_run("ls-ok", source="langsmith", minutes=3, duration_s=2.0))
    return session


def test_filter_by_source(populated):
    ids = [r.id for r in store.list_runs(populated, source="langsmith")]
    assert sorted(ids) == ["ls-error", "ls-ok"]


def test_filter_by_has_error(populated):
    assert [r.id for r in store.list_runs(populated, has_error=True)] == ["ls-error"]
    assert "ls-error" not in [r.id for r in store.list_runs(populated, has_error=False)]


def test_filter_by_duration_window(populated):
    ids = [r.id for r in store.list_runs(populated, min_duration_ms=1500)]
    assert sorted(ids) == ["ls-ok", "otel-slow"]

    ids = [r.id for r in store.list_runs(populated, max_duration_ms=1000)]
    assert "otel-fast" in ids
    assert "otel-slow" not in ids


def test_filters_combine(populated):
    ids = [r.id for r in store.list_runs(populated, source="otel", min_duration_ms=1000)]
    assert ids == ["otel-slow"]


def test_filter_by_labeled_state(populated):
    store.set_label(populated, "otel-fast", verdict="right")

    assert [r.id for r in store.list_runs(populated, labeled=True)] == ["otel-fast"]
    assert "otel-fast" not in [r.id for r in store.list_runs(populated, labeled=False)]


def test_pagination(populated):
    page = store.list_runs(populated, limit=2)
    assert len(page) == 2
    rest = store.list_runs(populated, limit=2, offset=2)
    assert len(rest) == 2
    assert {r.id for r in page}.isdisjoint({r.id for r in rest})


# --- unlabeled-first ordering -------------------------------------------------------------------


def test_unlabeled_runs_sort_before_labeled_ones(populated):
    store.set_label(populated, "otel-fast", verdict="right")

    ids = [r.id for r in store.list_runs(populated, unlabeled_first=True)]
    assert ids[-1] == "otel-fast"
    # Within the unlabeled block, oldest first, so the queue is resumable.
    assert ids[:3] == ["otel-slow", "ls-error", "ls-ok"]


def test_unlabeled_first_can_be_turned_off(populated):
    store.set_label(populated, "otel-fast", verdict="right")

    ids = [r.id for r in store.list_runs(populated, unlabeled_first=False)]
    assert ids == ["otel-fast", "otel-slow", "ls-error", "ls-ok"]


def test_next_unlabeled_walks_the_queue(populated):
    assert store.next_unlabeled(populated).id == "otel-fast"

    store.set_label(populated, "otel-fast", verdict="right")
    assert store.next_unlabeled(populated).id == "otel-slow"


def test_next_unlabeled_can_exclude_the_current_run(populated):
    assert store.next_unlabeled(populated, exclude="otel-fast").id == "otel-slow"


def test_next_unlabeled_returns_none_when_done(session):
    store.save_run(session, make_run("only"))
    store.set_label(session, "only", verdict="wrong")

    assert store.next_unlabeled(session) is None


# --- labels -------------------------------------------------------------------------------------


def test_label_round_trip(session):
    store.save_run(session, make_run("r1"))
    store.set_label(
        session,
        "r1",
        verdict="wrong",
        tags=["wrong_tool", "bad_args"],
        note="queried the wrong index",
        seconds_spent=6.5,
    )

    label = store.get_label(session, "r1")
    assert label.verdict == "wrong"
    assert store.loads(label.tags_json) == ["wrong_tool", "bad_args"]
    assert label.note == "queried the wrong index"
    assert label.seconds_spent == pytest.approx(6.5)
    assert label.labeled_at is not None


def test_relabeling_overwrites_in_place(session):
    store.save_run(session, make_run("r1"))
    store.set_label(session, "r1", verdict="right")
    store.set_label(session, "r1", verdict="partial", tags=["format_break"])

    assert len(store.all_labels(session)) == 1
    assert store.get_label(session, "r1").verdict == "partial"


def test_deleting_a_run_deletes_its_label_and_steps(session):
    store.save_run(session, make_run("r1"))
    store.set_label(session, "r1", verdict="right")

    session.delete(store.get_run(session, "r1"))
    session.flush()

    assert store.count_runs(session) == 0
    assert store.all_labels(session) == []


def test_counts_by_labeled_state(populated):
    store.set_label(populated, "otel-fast", verdict="right")

    assert store.count_runs(populated) == 4
    assert store.count_runs(populated, labeled=True) == 1
    assert store.count_runs(populated, labeled=False) == 3
