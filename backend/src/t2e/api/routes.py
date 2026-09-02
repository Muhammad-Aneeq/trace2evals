"""The API surface from spec 03 sec 7.

    POST /api/import              GET  /api/runs?filters      GET  /api/runs/{id}
    POST /api/runs/{id}/label     POST /api/cases             GET  /api/cases?version
    POST /api/export              GET  /api/stats

Everything is local: the server binds loopback by default and makes no outbound requests.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from t2e import casebuilder, exporters, store
from t2e import stats as stats_module
from t2e.ingest import ingest_text
from t2e.models import Case, Run
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


# --- cases --------------------------------------------------------------------------------------


class CaseOut(BaseModel):
    id: int
    version: str
    run_id: str | None
    input: Any
    expectations: list[dict[str, Any]]
    tags: list[str]
    created_at: str | None


class CaseCreate(BaseModel):
    """Create a case from a labeled run, or by hand. `run_id` NULL is the manual path (spec 03 F4)."""

    model_config = ConfigDict(extra="forbid")

    version: str = "v1"
    run_id: str | None = None
    #: Omitted when building from a run: the run's input is used.
    input: Any = None
    #: Omitted when building from a run: defaults are derived from the label.
    expectations: list[dict[str, Any]] | None = None
    tags: list[str] | None = None

    def validated_expectations(self) -> list[dict[str, Any]] | None:
        if self.expectations is None:
            return None
        unknown = sorted(
            {
                str(item.get("kind"))
                for item in self.expectations
                if item.get("kind") not in ASSERTION_KINDS
            }
        )
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown assertion kind(s): {', '.join(unknown)}. "
                f"v1 supports exactly five: {', '.join(ASSERTION_KINDS)}",
            )
        return self.expectations


def _case_out(row: Case) -> CaseOut:
    return CaseOut(
        id=row.id,
        version=row.version,
        run_id=row.run_id,
        input=store.loads(row.input_json, ""),
        expectations=store.loads(row.expectations_json, []) or [],
        tags=store.loads(row.tags_json, []) or [],
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


@router.get("/cases/suggest/{run_id}")
def suggest_case(run_id: str) -> dict[str, Any]:
    """The pre-filled case for a run, so the editor opens with defaults rather than blank fields."""
    with store.session_scope() as session:
        row = store.get_run(session, run_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no run with id {run_id!r}")
        label = row.label
        run = store.run_row_to_trace_run(row)
        return casebuilder.build_case_payload(
            run,
            verdict=label.verdict if label else None,
            tags=(store.loads(label.tags_json, []) if label else []) or [],
            version="v1",
        )


@router.post("/cases", response_model=CaseOut, status_code=201)
def create_case(payload: CaseCreate) -> CaseOut:
    expectations = payload.validated_expectations()

    with store.session_scope() as session:
        case_input = payload.input
        tags = payload.tags

        if payload.run_id:
            row = store.get_run(session, payload.run_id)
            if row is None:
                raise HTTPException(status_code=404, detail=f"no run with id {payload.run_id!r}")
            run = store.run_row_to_trace_run(row)
            label = row.label
            label_tags = (store.loads(label.tags_json, []) if label else []) or []

            # Anything the caller omitted is filled from the label (spec 03 F4).
            if case_input is None:
                case_input = run.input
            if expectations is None:
                expectations = casebuilder.suggest_expectations(
                    run, label.verdict if label else None, label_tags
                )
            if tags is None:
                tags = casebuilder.suggest_tags(run, label_tags)
        elif case_input is None:
            raise HTTPException(
                status_code=422, detail="a manual case (no run_id) needs an `input`"
            )

        created = store.create_case(
            session,
            version=payload.version,
            run_id=payload.run_id,
            input_value=case_input,
            expectations=expectations or [],
            tags=tags or [],
        )
        return _case_out(created)


@router.get("/cases", response_model=list[CaseOut])
def list_cases(version: Annotated[str | None, Query()] = None) -> list[CaseOut]:
    with store.session_scope() as session:
        return [_case_out(row) for row in store.list_cases(session, version=version)]


@router.patch("/cases/{case_id}", response_model=CaseOut)
def update_case(case_id: int, payload: CaseCreate) -> CaseOut:
    """Edit a case's expectations, tags or input. The editor is the point of the Cases screen."""
    expectations = payload.validated_expectations()

    with store.session_scope() as session:
        row = store.get_case(session, case_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no case with id {case_id}")

        if payload.input is not None:
            row.input_json = store.dumps(payload.input)
        if expectations is not None:
            row.expectations_json = store.dumps(expectations)
        if payload.tags is not None:
            row.tags_json = store.dumps(payload.tags)
        row.version = payload.version
        session.flush()
        return _case_out(row)


@router.delete("/cases/{case_id}", status_code=204)
def delete_case(case_id: int) -> None:
    with store.session_scope() as session:
        if not store.delete_case(session, case_id):
            raise HTTPException(status_code=404, detail=f"no case with id {case_id}")


# --- export -------------------------------------------------------------------------------------


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    #: Comma-separated: jsonl, pytest, promptfoo.
    format: str = "jsonl,pytest"
    notes: str = ""
    #: When false the files are returned in the response instead of written to disk.
    write_to_disk: bool = False
    out_dir: str = "exports"


@router.post("/export")
def export(payload: ExportRequest) -> dict[str, Any]:
    try:
        formats = exporters.parse_formats(payload.format)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with store.session_scope() as session:
        cases = store.list_cases(session, version=payload.version)
        if not cases:
            raise HTTPException(
                status_code=404,
                detail=f"no cases at version {payload.version!r}; build some on the Cases screen first",
            )

        if payload.write_to_disk:
            result = exporters.write(
                cases, version=payload.version, formats=formats, out_dir=payload.out_dir
            )
        else:
            rendered = exporters.render(cases, version=payload.version, formats=formats)
            result = {
                "version": payload.version,
                "case_count": len(cases),
                "formats": formats,
                "files": [
                    {"file": name, "bytes": len(text.encode("utf-8")), "content": text}
                    for name, text in rendered.items()
                ],
            }

        store.record_export_version(
            session,
            version=payload.version,
            case_count=len(cases),
            notes=payload.notes,
        )
        return result
