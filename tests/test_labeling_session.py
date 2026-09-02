"""A scripted 20-run labeling session, timed.

Spec 03 sec 10 asks for this as a Playwright run in CI. It is implemented at the API level instead
(PLAN.md **D-004**) because Playwright downloads browsers at test time, which contradicts this
tool's hard offline requirement. The substitution is stated in the README rather than glossed over.

What this test *does* prove:
  * the auto-advance queue drains all 20 runs without repeating or skipping one
  * a full label round trip is orders of magnitude faster than the 10s human budget, so the tool is
    never the bottleneck in the <10s median claim
  * the session stats reported back match the labels actually committed

What it does *not* prove: how long a human takes to read a trace and decide. That number comes from
the dogfood session in the README and is self-measured, not audited.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from t2e import store
from t2e.api.app import create_app
from t2e.ingest import ingest_paths
from t2e.normalizer import normalize_run
from t2e.schemas import RawRun, RawStep
from t2e.stats import TARGET_MEDIAN_SECONDS

SESSION_SIZE = 20

#: A realistic keyboard session: mostly R, a solid minority of failures, a few partials.
SCRIPT = [
    ("right", []),
    ("right", []),
    ("wrong", ["wrong_tool"]),
    ("right", []),
    ("partial", ["format_break"]),
    ("wrong", ["hallucinated_fact", "no_escalation"]),
    ("right", []),
    ("right", []),
    ("wrong", ["bad_args"]),
    ("partial", ["ungrounded"]),
    ("right", []),
    ("wrong", ["no_escalation"]),
    ("right", []),
    ("right", []),
    ("partial", ["ungrounded", "wrong_tool"]),
    ("right", []),
    ("wrong", ["wrong_tool", "bad_args"]),
    ("right", []),
    ("right", []),
    ("partial", ["other"]),
]


@pytest.fixture
def session_client(db, fixtures_dir) -> Iterator[TestClient]:
    """The 12 fixtures give 16 runs; top up to exactly 20 so the session size is the specced one."""
    ingest_paths([fixtures_dir / "otel", fixtures_dir / "langsmith"])

    with store.session_scope() as session:
        shortfall = SESSION_SIZE - store.count_runs(session)
        base = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
        for index in range(shortfall):
            started = base + timedelta(minutes=index)
            store.save_run(
                session,
                normalize_run(
                    RawRun(
                        run_id=f"topup-{index:02d}",
                        source="otel",
                        started=started,
                        ended=started + timedelta(seconds=3),
                        input=f"Synthetic top-up run {index}: reconcile BNK-TOPUP-{index:04d}.",
                        output="Matched against INV-TOPUP. Evidence: INV-TOPUP.",
                        steps=[
                            RawStep(
                                kind="llm",
                                name="gpt-4o-mini",
                                args={"messages": [{"role": "user", "content": "reconcile"}]},
                                output="matched",
                                started=started,
                                ended=started + timedelta(seconds=1),
                            ),
                            RawStep(
                                kind="tool",
                                name="get_invoice",
                                args={"invoice_id": f"INV-TOPUP-{index:04d}"},
                                output={"gross": 100.0},
                                started=started + timedelta(seconds=1),
                                ended=started + timedelta(seconds=2),
                            ),
                        ],
                    )
                ),
            )

    with TestClient(create_app(db)) as client:
        yield client


def test_scripted_twenty_run_session(session_client):
    client = session_client
    assert len(client.get("/api/runs", params={"limit": 100}).json()) == SESSION_SIZE

    # Start where the labeler starts: whatever the queue offers first.
    current = client.get("/api/runs/next-unlabeled").json()
    assert current is not None

    visited: list[str] = []
    round_trips: list[float] = []

    for index, (verdict, tags) in enumerate(SCRIPT):
        assert current is not None, f"queue ran dry after {index} of {SESSION_SIZE} runs"
        run_id = current["run_id"]
        assert run_id not in visited, "auto-advance offered the same run twice"
        visited.append(run_id)

        # One keystroke commit, exactly as the UI does it, with a plausible human timing attached.
        started = time.perf_counter()
        response = client.post(
            f"/api/runs/{run_id}/label",
            json={
                "verdict": verdict,
                "tags": tags,
                "seconds_spent": 4.0 + (index % 5),
            },
        )
        round_trips.append(time.perf_counter() - started)

        assert response.status_code == 200
        body = response.json()
        assert body["runs_unlabeled"] == SESSION_SIZE - (index + 1)

        # Auto-advance: the next run arrives in the label response, no extra request needed.
        next_id = body["next_run_id"]
        if next_id is None:
            current = None
        else:
            current = client.get(f"/api/runs/{next_id}").json()

    assert len(visited) == SESSION_SIZE
    assert len(set(visited)) == SESSION_SIZE, "every run labeled exactly once"
    assert current is None, "the queue is drained"

    median_round_trip = statistics.median(round_trips)
    assert median_round_trip < 0.5, (
        f"median label round trip was {median_round_trip * 1000:.0f}ms; the tool must never be "
        f"the bottleneck in a {TARGET_MEDIAN_SECONDS}s human budget"
    )

    stats = client.get("/api/stats").json()
    assert stats["runs_labeled"] == SESSION_SIZE
    assert stats["runs_unlabeled"] == 0
    assert stats["labels_timed"] == SESSION_SIZE
    assert stats["median_seconds_per_label"] == pytest.approx(6.0)
    assert stats["meets_speed_target"] is True

    # Expectations are derived from SCRIPT rather than hand-tallied, so the test cannot drift from
    # the script it drives. The distribution is the artefact a team lead actually wants (sec 3).
    expected_verdicts = Counter(verdict for verdict, _ in SCRIPT)
    expected_tags = Counter(tag for _, tags in SCRIPT for tag in tags)

    assert stats["verdicts"] == dict(expected_verdicts)
    assert stats["failure_tags"] == dict(expected_tags)
    assert sum(expected_verdicts.values()) == SESSION_SIZE


def test_session_is_resumable(session_client):
    """Half a session, then re-enter: the queue must pick up where it left off, not restart."""
    client = session_client

    first_half: list[str] = []
    current = client.get("/api/runs/next-unlabeled").json()
    for _ in range(10):
        first_half.append(current["run_id"])
        body = client.post(
            f"/api/runs/{current['run_id']}/label", json={"verdict": "right", "seconds_spent": 5.0}
        ).json()
        current = client.get(f"/api/runs/{body['next_run_id']}").json()

    resumed = client.get("/api/runs/next-unlabeled").json()

    assert resumed["run_id"] not in first_half
    assert client.get("/api/stats").json()["runs_unlabeled"] == SESSION_SIZE - 10


def test_unlabeled_first_keeps_the_queue_in_front(session_client):
    """After labeling, the run list still leads with unlabeled work."""
    client = session_client
    target = client.get("/api/runs/next-unlabeled").json()["run_id"]
    client.post(f"/api/runs/{target}/label", json={"verdict": "wrong", "tags": ["wrong_tool"]})

    listed = client.get("/api/runs", params={"limit": 100}).json()
    unlabeled_positions = [i for i, r in enumerate(listed) if r["verdict"] is None]
    labeled_positions = [i for i, r in enumerate(listed) if r["verdict"] is not None]

    assert max(unlabeled_positions) < min(labeled_positions)
