"""The API surface from spec 03 sec 7.

    POST /api/import              GET  /api/runs?filters      GET  /api/runs/{id}
    POST /api/runs/{id}/label     POST /api/cases             GET  /api/cases?version
    POST /api/export              GET  /api/stats

Everything is local: the server binds loopback by default and makes no outbound requests.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from t2e import stats as stats_module
from t2e import store
from t2e.ingest import ingest_text
from t2e.models import Run
from t2e.schemas import ASSERTION_KINDS, FAILURE_TAGS, ParseReport

router = APIRouter(prefix="/api")


# --- response shapes ----------------------------------------------------------------------------


class RunSummary(BaseModel):
    """A row in the run list. Deliberately light: no payloads, so the table stays fast."""

    run_id: str
    source: str
    started: str | None
    duration: float | None
    has_error: bool
    n_steps: int
    input_preview: str
    verdict: str | None
    tags: list[str]
    note: str


class StepDetail(BaseModel):
    kind: str
    name: str
    args_preview: str
    output_preview: str
    latency: float | None
    error: str | None
    #: Full payloads for the expanders. Previews alone would make the timeline useless for labeling.
    args: Any = None
    output: Any = None


class RunDetail(BaseModel):
    run_id: str
    source: str
    started: str | None
    duration: float | None
    input: str
    outcome: dict[str, Any]
    meta: dict[str, Any]
    steps: list[StepDetail]
    verdict: str | None
    tags: list[str]
    note: str
    seconds_spent: float | None


class LabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["right", "wrong", "partial"]
    tags: list[str] = Field(default_factory=list)
    note: str = ""
    #: Measured client-side from when the run was shown. Feeds the median-seconds stat.
    seconds_spent: float | None = None

    def validated_tags(self) -> list[str]:
        unknown = [tag for tag in self.tags if tag not in FAILURE_TAGS]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown failure tags: {', '.join(unknown)}. "
                f"The v1 taxonomy is closed: {', '.join(FAILURE_TAGS)}",
            )
        # De-duplicate but keep the taxonomy's canonical order, so stored tags are comparable.
        return [tag for tag in FAILURE_TAGS if tag in set(self.tags)]


class LabelResponse(BaseModel):
    run_id: str
    verdict: str
    tags: list[str]
    #: The next run to show, so the client can auto-advance without a second round trip.
    next_run_id: str | None
    runs_unlabeled: int


# --- helpers ------------------------------------------------------------------------------------


def _summary(row: Run) -> RunSummary:
    meta = store.loads(row.meta_json, {}) or {}
    label = row.label
    return RunSummary(
        run_id=row.id,
        source=row.source,
        started=row.started.isoformat() if row.started else None,
        duration=row.duration_ms,
        has_error=bool(row.has_error),
        n_steps=int(meta.get("n_steps", len(row.steps))),
        input_preview=store.preview(store.loads(row.input_json, "")),
        verdict=label.verdict if label else None,
        tags=(store.loads(label.tags_json, []) if label else []) or [],
        note=(label.note if label else "") or "",
    )


def _detail(row: Run) -> RunDetail:
    run = store.run_row_to_trace_run(row)
    label = row.label
    return RunDetail(
        run_id=run.run_id,
        source=run.source,
        started=run.started.isoformat() if run.started else None,
        duration=run.duration,
        input=run.input,
        outcome=run.outcome.model_dump(),
        meta=run.meta,
        steps=[
            StepDetail(
                kind=step.kind,
                name=step.name,
                args_preview=step.args_preview,
                output_preview=step.output_preview,
                latency=step.latency,
                error=step.error,
                args=step.args_full,
                output=step.output_full,
            )
            for step in run.steps
        ],
        verdict=label.verdict if label else None,
        tags=(store.loads(label.tags_json, []) if label else []) or [],
        note=(label.note if label else "") or "",
        seconds_spent=label.seconds_spent if label else None,
    )


# --- import -------------------------------------------------------------------------------------


@router.post("/import", response_model=list[ParseReport])
async def import_traces(
    files: Annotated[list[UploadFile], File(description="Trace exports to import")],
    fmt: Annotated[Literal["auto", "otel", "langsmith"], Query(alias="format")] = "auto",
    redact: Annotated[bool, Query()] = True,
) -> list[ParseReport]:
    """Import uploaded trace files. One report per file, so a bad file never hides a good one."""
    reports: list[ParseReport] = []
    with store.session_scope() as session:
        for upload in files:
            raw = await upload.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                report = ParseReport(file=upload.filename or "<upload>", format=fmt)
                report.records_seen += 1
                report.add_error("<file>", "file is not valid UTF-8 text")
                reports.append(report)
                continue
            reports.append(
                ingest_text(
                    session,
                    text,
                    file_label=upload.filename or "<upload>",
                    fmt=fmt,
                    redact=redact,
                )
            )
    return reports


# --- runs ---------------------------------------------------------------------------------------


@router.get("/runs", response_model=list[RunSummary])
def list_runs(
    source: Annotated[Literal["otel", "langsmith"] | None, Query()] = None,
    has_error: Annotated[bool | None, Query()] = None,
    min_duration_ms: Annotated[float | None, Query(ge=0)] = None,
    max_duration_ms: Annotated[float | None, Query(ge=0)] = None,
    labeled: Annotated[bool | None, Query()] = None,
    unlabeled_first: Annotated[bool, Query()] = True,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[RunSummary]:
    with store.session_scope() as session:
        rows = store.list_runs(
            session,
            source=source,
            has_error=has_error,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
            labeled=labeled,
            unlabeled_first=unlabeled_first,
            limit=limit,
            offset=offset,
        )
        return [_summary(row) for row in rows]


@router.get("/runs/next-unlabeled", response_model=RunDetail | None)
def next_unlabeled(exclude: Annotated[str | None, Query()] = None) -> RunDetail | None:
    """Declared before `/runs/{run_id}` so the literal path is not swallowed by the parameter."""
    with store.session_scope() as session:
        row = store.next_unlabeled(session, exclude=exclude)
        return _detail(row) if row else None


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(run_id: str) -> RunDetail:
    with store.session_scope() as session:
        row = store.get_run(session, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no run with id {run_id!r}")
        return _detail(row)


@router.post("/runs/{run_id}/label", response_model=LabelResponse)
def label_run(run_id: str, payload: LabelRequest) -> LabelResponse:
    tags = payload.validated_tags()
    with store.session_scope() as session:
        if store.get_run(session, run_id) is None:
            raise HTTPException(status_code=404, detail=f"no run with id {run_id!r}")

        store.set_label(
            session,
            run_id,
            verdict=payload.verdict,
            tags=tags,
            note=payload.note,
            seconds_spent=payload.seconds_spent,
        )
        # Resolve the next target here: auto-advance must not cost the client a round trip.
        following = store.next_unlabeled(session, exclude=run_id)
        return LabelResponse(
            run_id=run_id,
            verdict=payload.verdict,
            tags=tags,
            next_run_id=following.id if following else None,
            runs_unlabeled=store.count_runs(session, labeled=False),
        )


@router.delete("/runs/{run_id}/label", status_code=204)
def clear_label(run_id: str) -> None:
    """Undo a label. Needed because a fast keyboard flow will inevitably mislabel something."""
    with store.session_scope() as session:
        label = store.get_label(session, run_id)
        if label is None:
            raise HTTPException(status_code=404, detail=f"run {run_id!r} is not labeled")
        session.delete(label)


# --- taxonomy / stats ---------------------------------------------------------------------------


@router.get("/taxonomy")
def taxonomy() -> dict[str, list[str]]:
    """The closed vocabularies, so the UI never hard-codes a list that could drift away."""
    return {
        "verdicts": ["right", "wrong", "partial"],
        "failure_tags": list(FAILURE_TAGS),
        "assertion_kinds": list(ASSERTION_KINDS),
    }


@router.get("/stats")
def get_stats() -> dict[str, Any]:
    with store.session_scope() as session:
        return stats_module.collect(session).to_dict()


# --- cases / export (filled in by Phase 3) ------------------------------------------------------


@router.post("/cases", status_code=501)
def create_case(payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="case builder lands in Phase 3; see PLAN.md")


@router.get("/cases", status_code=501)
def list_cases(version: Annotated[str | None, Query()] = None) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="case builder lands in Phase 3; see PLAN.md")


@router.post("/export", status_code=501)
def export(payload: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="exporters land in Phase 3; see PLAN.md")
