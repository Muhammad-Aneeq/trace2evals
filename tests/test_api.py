"""Every endpoint in spec 03 sec 7, plus the filters and auto-advance behaviour F3 requires."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from t2e.api.app import create_app
from t2e.ingest import ingest_paths


@pytest.fixture
def client(db) -> Iterator[TestClient]:
    with TestClient(create_app(db)) as test_client:
        yield test_client


@pytest.fixture
def loaded(client, fixtures_dir) -> TestClient:
    ingest_paths([fixtures_dir / "otel", fixtures_dir / "langsmith"])
    return client


# --- health / taxonomy --------------------------------------------------------------------------


def test_health(client):
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert "db" in body


def test_taxonomy_is_served_so_the_ui_never_hardcodes_it(client):
    body = client.get("/api/taxonomy").json()

    assert body["verdicts"] == ["right", "wrong", "partial"]
    assert body["failure_tags"] == [
        "wrong_tool",
        "bad_args",
        "ungrounded",
        "no_escalation",
        "format_break",
        "hallucinated_fact",
        "other",
    ]
    assert len(body["assertion_kinds"]) == 5, "spec 03 sec 14 caps v1 at 5 assertion kinds"


# --- POST /api/import ---------------------------------------------------------------------------


def test_import_uploads_both_formats(client, fixtures_dir):
    files = [
        (
            "files",
            (
                "otel.json",
                (fixtures_dir / "otel" / "01_clean_reconciliation.json").read_bytes(),
                "application/json",
            ),
        ),
        (
            "files",
            (
                "ls.jsonl",
                (fixtures_dir / "langsmith" / "01_clean_reconciliation.jsonl").read_bytes(),
                "application/x-ndjson",
            ),
        ),
    ]
    reports = client.post("/api/import", files=files).json()

    assert len(reports) == 2, "one report per file"
    assert {r["format"] for r in reports} == {"otel", "langsmith"}
    assert all(r["runs_imported"] == 1 for r in reports)
    assert client.get("/api/runs").json()


def test_import_reports_malformed_records_without_failing_the_request(client, fixtures_dir):
    files = [
        (
            "files",
            (
                "bad.jsonl",
                (fixtures_dir / "langsmith" / "06_malformed_mixed.jsonl").read_bytes(),
                "application/x-ndjson",
            ),
        )
    ]
    response = client.post("/api/import", files=files)

    assert response.status_code == 200
    (report,) = response.json()
    assert report["runs_imported"] == 2
    assert report["errors"]


def test_import_surfaces_the_pii_warning(client, fixtures_dir):
    files = [
        (
            "files",
            (
                "pii.json",
                (fixtures_dir / "otel" / "02_tool_heavy_with_pii.json").read_bytes(),
                "application/json",
            ),
        )
    ]
    (report,) = client.post("/api/import", files=files).json()

    assert report["redactions"] > 0
    assert "email" in report["pii_flags"]


def test_import_rejects_non_utf8_gracefully(client):
    files = [("files", ("binary.json", b"\xff\xfe\x00\x01", "application/json"))]
    (report,) = client.post("/api/import", files=files).json()

    assert report["runs_imported"] == 0
    assert "not valid UTF-8" in report["errors"][0]["reason"]


# --- GET /api/runs ------------------------------------------------------------------------------


def test_run_list_returns_summaries(loaded):
    runs = loaded.get("/api/runs").json()

    assert len(runs) == 16
    first = runs[0]
    assert set(first) == {
        "run_id",
        "source",
        "started",
        "duration",
        "has_error",
        "n_steps",
        "input_preview",
        "verdict",
        "tags",
        "note",
    }
    assert first["verdict"] is None


@pytest.mark.parametrize("source", ["otel", "langsmith"])
def test_filter_by_source(loaded, source):
    runs = loaded.get("/api/runs", params={"source": source}).json()

    assert runs
    assert {r["source"] for r in runs} == {source}


def test_filter_by_has_error(loaded):
    runs = loaded.get("/api/runs", params={"has_error": True}).json()

    assert runs
    assert all(r["has_error"] for r in runs)


def test_filter_by_duration(loaded):
    runs = loaded.get("/api/runs", params={"min_duration_ms": 5000}).json()

    assert runs
    assert all(r["duration"] >= 5000 for r in runs)


def test_filter_by_labeled_state(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]
    loaded.post(f"/api/runs/{target}/label", json={"verdict": "right"})

    labeled = loaded.get("/api/runs", params={"labeled": True}).json()
    assert [r["run_id"] for r in labeled] == [target]

    unlabeled = loaded.get("/api/runs", params={"labeled": False}).json()
    assert target not in [r["run_id"] for r in unlabeled]


def test_unlabeled_first_is_the_default(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]
    loaded.post(f"/api/runs/{target}/label", json={"verdict": "wrong", "tags": ["wrong_tool"]})

    runs = loaded.get("/api/runs").json()
    assert runs[-1]["run_id"] == target, "labeled runs sink to the bottom of the queue"


def test_pagination(loaded):
    page = loaded.get("/api/runs", params={"limit": 5}).json()
    assert len(page) == 5

    rest = loaded.get("/api/runs", params={"limit": 5, "offset": 5}).json()
    assert {r["run_id"] for r in page}.isdisjoint({r["run_id"] for r in rest})


def test_invalid_filter_value_is_rejected(loaded):
    assert loaded.get("/api/runs", params={"source": "braintrust"}).status_code == 422
    assert loaded.get("/api/runs", params={"min_duration_ms": -5}).status_code == 422


# --- GET /api/runs/{id} -------------------------------------------------------------------------


def test_run_detail_includes_full_payloads_for_the_expanders(loaded):
    detail = loaded.get("/api/runs/4f2a9c1e8b7d6a5f3e2d1c0b9a8f7e6d").json()

    assert detail["source"] == "otel"
    assert [s["kind"] for s in detail["steps"]] == ["llm", "tool", "tool", "llm"]

    tool_step = detail["steps"][1]
    assert tool_step["name"] == "search_counterparty"
    assert tool_step["args"]["name"] == "ORBITAL LOGISTICS LTD", "full payload, not just a preview"
    assert tool_step["args_preview"]

    assert detail["outcome"]["status"] == "success"
    assert detail["meta"]["service"] == "exception-workbench"


def test_unknown_run_is_404(client):
    response = client.get("/api/runs/does-not-exist")

    assert response.status_code == 404
    assert "no run with id" in response.json()["detail"]


# --- POST /api/runs/{id}/label ------------------------------------------------------------------


def test_label_a_run(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]

    body = loaded.post(
        f"/api/runs/{target}/label",
        json={
            "verdict": "wrong",
            "tags": ["wrong_tool", "bad_args"],
            "note": "queried the GL by invoice id",
            "seconds_spent": 7.4,
        },
    ).json()

    assert body["verdict"] == "wrong"
    assert body["tags"] == ["wrong_tool", "bad_args"]

    detail = loaded.get(f"/api/runs/{target}").json()
    assert detail["verdict"] == "wrong"
    assert detail["note"] == "queried the GL by invoice id"
    assert detail["seconds_spent"] == pytest.approx(7.4)


def test_label_response_carries_the_next_run_for_auto_advance(loaded):
    queue = [r["run_id"] for r in loaded.get("/api/runs").json()]

    body = loaded.post(f"/api/runs/{queue[0]}/label", json={"verdict": "right"}).json()

    assert body["next_run_id"] == queue[1], "auto-advance must not need a second round trip"
    assert body["runs_unlabeled"] == len(queue) - 1


def test_next_run_is_null_when_the_queue_is_empty(loaded):
    for run in loaded.get("/api/runs").json():
        body = loaded.post(f"/api/runs/{run['run_id']}/label", json={"verdict": "right"}).json()

    assert body["next_run_id"] is None
    assert body["runs_unlabeled"] == 0


def test_relabeling_overwrites(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]

    loaded.post(f"/api/runs/{target}/label", json={"verdict": "right"})
    loaded.post(f"/api/runs/{target}/label", json={"verdict": "partial", "tags": ["format_break"]})

    detail = loaded.get(f"/api/runs/{target}").json()
    assert detail["verdict"] == "partial"
    assert detail["tags"] == ["format_break"]


def test_tags_are_normalised_to_taxonomy_order(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]

    body = loaded.post(
        f"/api/runs/{target}/label",
        json={"verdict": "wrong", "tags": ["ungrounded", "wrong_tool", "ungrounded"]},
    ).json()

    assert body["tags"] == ["wrong_tool", "ungrounded"], "canonical order, de-duplicated"


def test_unknown_failure_tag_is_rejected(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]

    response = loaded.post(
        f"/api/runs/{target}/label", json={"verdict": "wrong", "tags": ["vibes_off"]}
    )

    assert response.status_code == 422
    assert "vibes_off" in response.json()["detail"]


def test_unknown_verdict_is_rejected(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]
    assert loaded.post(f"/api/runs/{target}/label", json={"verdict": "maybe"}).status_code == 422


def test_labeling_a_missing_run_is_404(client):
    response = client.post("/api/runs/nope/label", json={"verdict": "right"})
    assert response.status_code == 404


def test_label_can_be_cleared(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]
    loaded.post(f"/api/runs/{target}/label", json={"verdict": "right"})

    assert loaded.delete(f"/api/runs/{target}/label").status_code == 204
    assert loaded.get(f"/api/runs/{target}").json()["verdict"] is None
    assert loaded.delete(f"/api/runs/{target}/label").status_code == 404


# --- GET /api/runs/next-unlabeled ---------------------------------------------------------------


def test_next_unlabeled_returns_a_full_detail(loaded):
    detail = loaded.get("/api/runs/next-unlabeled").json()

    assert detail is not None
    assert detail["steps"], "the labeler needs the timeline immediately"


def test_next_unlabeled_can_exclude_the_current_run(loaded):
    first = loaded.get("/api/runs/next-unlabeled").json()["run_id"]
    second = loaded.get("/api/runs/next-unlabeled", params={"exclude": first}).json()["run_id"]

    assert first != second


def test_next_unlabeled_literal_path_is_not_shadowed_by_the_id_route(loaded):
    """Route order matters: `/runs/next-unlabeled` must not be read as `/runs/{run_id}`."""
    assert loaded.get("/api/runs/next-unlabeled").status_code == 200


# --- GET /api/stats -----------------------------------------------------------------------------


def test_stats_reports_distribution_and_speed(loaded):
    runs = loaded.get("/api/runs").json()
    for run, verdict, tags, seconds in (
        (runs[0], "right", [], 4.0),
        (runs[1], "wrong", ["wrong_tool"], 8.0),
        (runs[2], "partial", ["ungrounded", "no_escalation"], 6.0),
    ):
        loaded.post(
            f"/api/runs/{run['run_id']}/label",
            json={"verdict": verdict, "tags": tags, "seconds_spent": seconds},
        )

    body = loaded.get("/api/stats").json()

    assert body["runs_total"] == 16
    assert body["runs_labeled"] == 3
    assert body["runs_unlabeled"] == 13
    assert body["verdicts"] == {"right": 1, "wrong": 1, "partial": 1}
    assert body["failure_tags"] == {"wrong_tool": 1, "ungrounded": 1, "no_escalation": 1}
    assert body["median_seconds_per_label"] == pytest.approx(6.0)
    assert body["labels_timed"] == 3
    assert body["meets_speed_target"] is True
    assert body["runs_by_source"] == {"langsmith": 8, "otel": 8}


def test_speed_target_is_unproven_rather_than_passing_when_nothing_is_timed(loaded):
    target = loaded.get("/api/runs").json()[0]["run_id"]
    loaded.post(f"/api/runs/{target}/label", json={"verdict": "right"})

    body = loaded.get("/api/stats").json()

    assert body["labels_timed"] == 0
    assert body["median_seconds_per_label"] is None
    assert body["meets_speed_target"] is None, "an unmeasured claim must not report as passing"


def test_stats_on_an_empty_store(client):
    body = client.get("/api/stats").json()

    assert body["runs_total"] == 0
    assert body["verdicts"] == {"right": 0, "wrong": 0, "partial": 0}
    assert body["meets_speed_target"] is None


# --- case and export endpoints are live (covered in depth in test_api_cases.py) -----------------


def test_case_and_export_endpoints_are_implemented(client):
    assert client.get("/api/cases").status_code == 200
    # An export with nothing to export is a 404, not a silent empty file.
    assert client.post("/api/export", json={"version": "v1"}).status_code == 404
