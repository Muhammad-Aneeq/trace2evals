"""The case-builder and export endpoints: `POST /api/cases`, `GET /api/cases?version`, `POST /api/export`."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import yaml
from fastapi.testclient import TestClient

from t2e import store
from t2e.api.app import create_app
from t2e.ingest import ingest_paths

#: The OTel fixture where the tool fails and the agent invents an approver instead of escalating.
HALLUCINATION_RUN = "9e4b7d2c6a1f5e8b3d0c9a2f7e4b1d6c"
#: The clean partial-payment run.
CLEAN_RUN = "4f2a9c1e8b7d6a5f3e2d1c0b9a8f7e6d"


@pytest.fixture
def client(db, fixtures_dir) -> Iterator[TestClient]:
    ingest_paths([fixtures_dir / "otel", fixtures_dir / "langsmith"])
    with TestClient(create_app(db)) as test_client:
        yield test_client


def label(client: TestClient, run_id: str, verdict: str, tags: list[str] | None = None) -> None:
    response = client.post(
        f"/api/runs/{run_id}/label",
        json={"verdict": verdict, "tags": tags or [], "seconds_spent": 6.0},
    )
    assert response.status_code == 200, response.text


# --- suggestion ---------------------------------------------------------------------------------


def test_suggest_prefills_from_the_label(client):
    label(client, HALLUCINATION_RUN, "wrong", ["no_escalation", "hallucinated_fact"])

    payload = client.get(f"/api/cases/suggest/{HALLUCINATION_RUN}").json()

    assert payload["run_id"] == HALLUCINATION_RUN
    assert payload["input"].startswith("Transaction BNK-20260814-0067")

    kinds = {item["kind"] for item in payload["expectations"]}
    assert kinds == {"must_escalate", "must_cite"}
    assert all(item.get("note") for item in payload["expectations"])
    assert "no_escalation" in payload["tags"]
    assert "source:otel" in payload["tags"]


def test_suggest_on_an_unlabeled_run_proposes_nothing(client):
    payload = client.get(f"/api/cases/suggest/{CLEAN_RUN}").json()
    assert payload["expectations"] == []


def test_suggest_404s_for_an_unknown_run(client):
    assert client.get("/api/cases/suggest/nope").status_code == 404


# --- creation -----------------------------------------------------------------------------------


def test_create_case_from_a_labeled_run_uses_the_defaults(client):
    label(client, HALLUCINATION_RUN, "wrong", ["no_escalation"])

    response = client.post("/api/cases", json={"version": "v1", "run_id": HALLUCINATION_RUN})

    assert response.status_code == 201
    case = response.json()
    assert case["run_id"] == HALLUCINATION_RUN
    assert case["input"].startswith("Transaction BNK-20260814-0067")
    assert [item["kind"] for item in case["expectations"]] == ["must_escalate"]
    assert "no_escalation" in case["tags"]


def test_caller_supplied_expectations_override_the_defaults(client):
    label(client, HALLUCINATION_RUN, "wrong", ["no_escalation"])

    case = client.post(
        "/api/cases",
        json={
            "version": "v1",
            "run_id": HALLUCINATION_RUN,
            "expectations": [{"kind": "must_call_tool", "tool": "get_invoice"}],
            "tags": ["hand-edited"],
        },
    ).json()

    assert [item["kind"] for item in case["expectations"]] == ["must_call_tool"]
    assert case["tags"] == ["hand-edited"]


def test_a_manual_case_needs_no_run(client):
    case = client.post(
        "/api/cases",
        json={
            "version": "v1",
            "input": "A hand-written case about materiality.",
            "expectations": [{"kind": "output_matches_regex", "pattern": "threshold"}],
        },
    ).json()

    assert case["run_id"] is None
    assert case["input"] == "A hand-written case about materiality."


def test_a_manual_case_without_input_is_rejected(client):
    response = client.post("/api/cases", json={"version": "v1"})

    assert response.status_code == 422
    assert "needs an `input`" in response.json()["detail"]


def test_creating_from_an_unknown_run_is_404(client):
    assert client.post("/api/cases", json={"run_id": "nope"}).status_code == 404


def test_an_unknown_assertion_kind_is_rejected_with_the_five(client):
    response = client.post(
        "/api/cases",
        json={"input": "x", "expectations": [{"kind": "must_be_vibey"}]},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "must_be_vibey" in detail
    assert "v1 supports exactly five" in detail


# --- listing / editing --------------------------------------------------------------------------


def test_cases_are_listed_and_filtered_by_version(client):
    label(client, CLEAN_RUN, "right")
    client.post("/api/cases", json={"version": "v1", "run_id": CLEAN_RUN})
    client.post("/api/cases", json={"version": "v2", "input": "later case", "expectations": []})

    assert len(client.get("/api/cases").json()) == 2
    assert len(client.get("/api/cases", params={"version": "v1"}).json()) == 1
    assert client.get("/api/cases", params={"version": "v2"}).json()[0]["input"] == "later case"


def test_a_case_can_be_edited(client):
    created = client.post(
        "/api/cases", json={"input": "original", "expectations": []}
    ).json()

    updated = client.patch(
        f"/api/cases/{created['id']}",
        json={
            "version": "v2",
            "input": "revised",
            "expectations": [{"kind": "must_cite", "min_count": 2}],
            "tags": ["edited"],
        },
    ).json()

    assert updated["input"] == "revised"
    assert updated["version"] == "v2"
    assert updated["expectations"][0]["min_count"] == 2
    assert updated["tags"] == ["edited"]


def test_editing_an_unknown_case_is_404(client):
    assert client.patch("/api/cases/999", json={"version": "v1"}).status_code == 404


def test_a_case_can_be_deleted(client):
    created = client.post("/api/cases", json={"input": "x", "expectations": []}).json()

    assert client.delete(f"/api/cases/{created['id']}").status_code == 204
    assert client.get("/api/cases").json() == []
    assert client.delete(f"/api/cases/{created['id']}").status_code == 404


# --- export -------------------------------------------------------------------------------------


@pytest.fixture
def with_cases(client) -> TestClient:
    label(client, HALLUCINATION_RUN, "wrong", ["no_escalation", "hallucinated_fact"])
    label(client, CLEAN_RUN, "right")
    client.post("/api/cases", json={"version": "v1", "run_id": HALLUCINATION_RUN})
    client.post("/api/cases", json={"version": "v1", "run_id": CLEAN_RUN})
    return client


def test_export_returns_the_files_in_the_response_by_default(with_cases):
    body = with_cases.post(
        "/api/export", json={"version": "v1", "format": "jsonl,pytest"}
    ).json()

    assert body["case_count"] == 2
    names = {entry["file"] for entry in body["files"]}
    assert names == {"cases.jsonl", "test_cases.py"}

    jsonl = next(entry["content"] for entry in body["files"] if entry["file"] == "cases.jsonl")
    assert jsonl.count("\n") == 2
    assert '"schema_version"' in jsonl


def test_export_can_write_to_disk(with_cases, tmp_path):
    out = tmp_path / "exports"
    body = with_cases.post(
        "/api/export",
        json={
            "version": "v1",
            "format": "jsonl,pytest,promptfoo",
            "write_to_disk": True,
            "out_dir": str(out),
            "notes": "first cut",
        },
    ).json()

    assert body["out_dir"] == str(out)
    assert (out / "cases.jsonl").is_file()
    assert (out / "test_cases.py").is_file()

    config = yaml.safe_load((out / "promptfooconfig.yaml").read_text(encoding="utf-8"))
    assert len(config["tests"]) == 2


def test_export_records_the_version_and_its_notes(with_cases):
    with_cases.post("/api/export", json={"version": "v1", "notes": "first cut"})

    stats = with_cases.get("/api/stats").json()
    assert stats["cases_total"] == 2
    assert stats["cases_by_version"] == {"v1": 2}
    assert stats["export_versions"][0]["version"] == "v1"
    assert stats["export_versions"][0]["case_count"] == 2
    assert stats["export_versions"][0]["notes"] == "first cut"


def test_exporting_an_empty_version_is_404_not_an_empty_file(with_cases):
    response = with_cases.post("/api/export", json={"version": "v9"})

    assert response.status_code == 404
    assert "no cases at version 'v9'" in response.json()["detail"]


def test_an_unknown_export_format_is_rejected(with_cases):
    response = with_cases.post("/api/export", json={"version": "v1", "format": "parquet"})

    assert response.status_code == 422
    assert "unknown export format" in response.json()["detail"]


def test_requesting_pytest_implies_the_cases_file(with_cases):
    body = with_cases.post("/api/export", json={"version": "v1", "format": "pytest"}).json()

    assert {entry["file"] for entry in body["files"]} == {"cases.jsonl", "test_cases.py"}


def test_re_exporting_the_same_version_updates_rather_than_duplicates(with_cases):
    with_cases.post("/api/export", json={"version": "v1", "notes": "first"})
    with_cases.post("/api/export", json={"version": "v1", "notes": "second"})

    versions = with_cases.get("/api/stats").json()["export_versions"]
    assert len(versions) == 1
    assert versions[0]["notes"] == "second"


# --- the full offline loop ----------------------------------------------------------------------


def test_import_label_build_export_round_trip(client, tmp_path):
    """The whole product in one test: import -> label -> case -> export -> re-read."""
    from t2e.exporters import cases_jsonl

    label(client, HALLUCINATION_RUN, "wrong", ["no_escalation", "hallucinated_fact"])
    client.post("/api/cases", json={"version": "v1", "run_id": HALLUCINATION_RUN})

    out = tmp_path / "exports"
    client.post(
        "/api/export",
        json={"version": "v1", "format": "jsonl,pytest", "write_to_disk": True, "out_dir": str(out)},
    )

    records = cases_jsonl.parse((out / "cases.jsonl").read_text(encoding="utf-8"))
    assert len(records) == 1
    record = records[0]
    assert record["run_id"] == HALLUCINATION_RUN
    assert {item["kind"] for item in record["expectations"]} == {"must_escalate", "must_cite"}

    # The exported case is traceable back to the run it came from.
    with store.session_scope() as session:
        assert store.get_run(session, record["run_id"]) is not None
