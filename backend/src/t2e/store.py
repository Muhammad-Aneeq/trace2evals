"""Engine, schema bootstrap, and the repository functions the API and CLI share.

Every JSON column is written with `sort_keys=True` so exports and snapshots are byte-stable.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from t2e.config import Settings, get_settings
from t2e.models import Base, Case, ExportVersion, Label, Run, Step
from t2e.schemas import Outcome, TraceRun
from t2e.schemas import Step as StepSchema

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def dumps(value: Any) -> str:
    """Stable JSON. `sort_keys` is what makes golden-file comparison meaningful."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --- engine / session ---------------------------------------------------------------------------


def get_engine(settings: Settings | None = None) -> Engine:
    global _engine, _session_factory
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_engine(settings.sqlalchemy_url, future=True)

        @event.listens_for(_engine, "connect")
        def _enable_fk(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(_engine)
    return _engine


def reset_engine() -> None:
    """Drop cached engine/session state. Used by the CLI's --db and by test fixtures."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def init_db(settings: Settings | None = None) -> None:
    get_engine(settings)


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    get_engine(settings)
    assert _session_factory is not None
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- runs ---------------------------------------------------------------------------------------


def save_run(session: Session, run: TraceRun) -> Run:
    """Insert or replace a run and its steps. Re-importing the same trace id updates it in place."""
    row = session.get(Run, run.run_id)
    if row is None:
        row = Run(id=run.run_id)
        session.add(row)
    else:
        # Replace steps wholesale rather than diffing: a re-import is authoritative.
        for step in list(row.steps):
            session.delete(step)
        row.steps.clear()
        session.flush()

    row.source = run.source
    row.imported_at = _utcnow()
    row.started = run.started
    row.duration_ms = run.duration
    row.has_error = run.has_error
    row.input_json = dumps(run.input)
    row.outcome_json = dumps(run.outcome.model_dump())
    row.meta_json = dumps(run.meta)

    # Append through the relationship, not `session.add`: the collection was just cleared, so a
    # bare add would leave `row.steps` cached as empty for the rest of this session.
    for idx, step in enumerate(run.steps):
        row.steps.append(
            Step(
                idx=idx,
                kind=step.kind,
                name=step.name,
                args_json=dumps(step.args_full),
                output_json=dumps(step.output_full),
                latency_ms=step.latency,
                error=step.error,
            )
        )
    session.flush()
    return row


def get_run(session: Session, run_id: str) -> Run | None:
    return session.get(Run, run_id)


def list_runs(
    session: Session,
    *,
    source: str | None = None,
    has_error: bool | None = None,
    min_duration_ms: float | None = None,
    max_duration_ms: float | None = None,
    labeled: bool | None = None,
    unlabeled_first: bool = True,
    limit: int | None = None,
    offset: int = 0,
) -> list[Run]:
    """The F3 run list. `unlabeled_first` is the default because it is the labeling workflow."""
    stmt = select(Run).outerjoin(Label, Label.run_id == Run.id)

    if source:
        stmt = stmt.where(Run.source == source)
    if has_error is not None:
        stmt = stmt.where(Run.has_error == has_error)
    if min_duration_ms is not None:
        stmt = stmt.where(Run.duration_ms >= min_duration_ms)
    if max_duration_ms is not None:
        stmt = stmt.where(Run.duration_ms <= max_duration_ms)
    if labeled is True:
        stmt = stmt.where(Label.run_id.is_not(None))
    elif labeled is False:
        stmt = stmt.where(Label.run_id.is_(None))

    if unlabeled_first:
        # NULL label sorts first, then oldest-started first for a stable, resumable queue.
        stmt = stmt.order_by(Label.run_id.is_not(None), Run.started.is_(None), Run.started, Run.id)
    else:
        stmt = stmt.order_by(Run.started.is_(None), Run.started, Run.id)

    if offset:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.scalars(stmt).unique())


def next_unlabeled(session: Session, *, exclude: str | None = None) -> Run | None:
    """The run the labeler should show next. Drives auto-advance (F3)."""
    stmt = (
        select(Run)
        .outerjoin(Label, Label.run_id == Run.id)
        .where(Label.run_id.is_(None))
        .order_by(Run.started.is_(None), Run.started, Run.id)
    )
    if exclude:
        stmt = stmt.where(Run.id != exclude)
    return session.scalars(stmt.limit(1)).first()


def count_runs(session: Session, *, labeled: bool | None = None) -> int:
    stmt = select(func.count(Run.id)).outerjoin(Label, Label.run_id == Run.id)
    if labeled is True:
        stmt = stmt.where(Label.run_id.is_not(None))
    elif labeled is False:
        stmt = stmt.where(Label.run_id.is_(None))
    return int(session.scalar(stmt) or 0)


# --- labels -------------------------------------------------------------------------------------


def set_label(
    session: Session,
    run_id: str,
    *,
    verdict: str,
    tags: Sequence[str] = (),
    note: str = "",
    seconds_spent: float | None = None,
) -> Label:
    row = session.get(Label, run_id)
    if row is None:
        row = Label(run_id=run_id)
        session.add(row)
    row.verdict = verdict
    row.tags_json = dumps(list(tags))
    row.note = note or ""
    row.labeled_at = _utcnow()
    row.seconds_spent = seconds_spent
    session.flush()
    return row


def get_label(session: Session, run_id: str) -> Label | None:
    return session.get(Label, run_id)


def all_labels(session: Session) -> list[Label]:
    return list(session.scalars(select(Label)))


# --- cases / exports ----------------------------------------------------------------------------


def create_case(
    session: Session,
    *,
    version: str,
    run_id: str | None,
    input_value: Any,
    expectations: Sequence[dict[str, Any]],
    tags: Sequence[str] = (),
) -> Case:
    row = Case(
        version=version,
        run_id=run_id,
        input_json=dumps(input_value),
        expectations_json=dumps(list(expectations)),
        tags_json=dumps(list(tags)),
        created_at=_utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def get_case(session: Session, case_id: int) -> Case | None:
    return session.get(Case, case_id)


def list_cases(session: Session, *, version: str | None = None) -> list[Case]:
    stmt = select(Case)
    if version:
        stmt = stmt.where(Case.version == version)
    return list(session.scalars(stmt.order_by(Case.id)))


def delete_case(session: Session, case_id: int) -> bool:
    row = session.get(Case, case_id)
    if row is None:
        return False
    session.delete(row)
    return True


def record_export_version(
    session: Session, *, version: str, case_count: int, notes: str = ""
) -> ExportVersion:
    row = session.get(ExportVersion, version)
    if row is None:
        row = ExportVersion(version=version)
        session.add(row)
    row.created_at = _utcnow()
    row.case_count = case_count
    row.notes = notes or ""
    session.flush()
    return row


def list_export_versions(session: Session) -> list[ExportVersion]:
    return list(session.scalars(select(ExportVersion).order_by(ExportVersion.created_at)))


# --- row -> schema ------------------------------------------------------------------------------


def run_row_to_trace_run(row: Run) -> TraceRun:
    """Rehydrate the normalized model from storage, full payloads included."""
    steps: list[StepSchema] = []
    for step in row.steps:
        args = loads(step.args_json)
        output = loads(step.output_json)
        steps.append(
            StepSchema(
                kind=step.kind,  # type: ignore[arg-type]
                name=step.name,
                args_preview=preview(args),
                output_preview=preview(output),
                latency=step.latency_ms,
                error=step.error,
                args_full=args,
                output_full=output,
            )
        )
    outcome_data = loads(row.outcome_json, {}) or {}
    return TraceRun(
        run_id=row.id,
        source=row.source,  # type: ignore[arg-type]
        started=row.started,
        input=loads(row.input_json, "") or "",
        steps=steps,
        outcome=Outcome(**outcome_data),
        meta=loads(row.meta_json, {}) or {},
        duration=row.duration_ms,
    )


def preview(value: Any, limit: int | None = None) -> str:
    """Late import keeps this module free of a normalizer dependency cycle."""
    from t2e.normalizer import make_preview

    return make_preview(value, limit)
