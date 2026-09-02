"""SQLAlchemy ORM. Tables are those named in spec 03 sec 6:

    runs(id, source, imported_at, input_json, outcome_json, meta_json)
    steps(id, run_id FK, idx, kind, name, args_json, output_json, latency_ms, error)
    labels(run_id FK, verdict[right|wrong|partial], tags_json, note, labeled_at)
    cases(id, version, run_id FK NULL, input_json, expectations_json, tags_json, created_at)
    export_versions(version, created_at, case_count, notes)

Three columns exist beyond that list, all to serve required features rather than by preference:
`runs.started`, `runs.duration_ms` and `runs.has_error` back the F3 run-list filters (source,
has-error, duration), and `labels.seconds_spent` is what the median-seconds-per-label stat in
spec 03 sec 9 is computed from. Recorded as D-009 / D-010 in PLAN.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UtcDateTime(TypeDecorator):
    """A timezone-safe datetime for SQLite.

    SQLite has no native timestamp type and silently discards `tzinfo`, which would make a run
    reloaded from disk compare unequal to the one that was written. Values are normalized to UTC and
    stored naive, then handed back as UTC-aware on read, so everything above this layer can assume
    aware datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    #: The run id carried by the trace itself (OTel traceId / LangSmith trace_id), so re-importing
    #: the same trace updates rather than duplicates.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)
    imported_at: Mapped[datetime] = mapped_column(UtcDateTime)
    started: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    has_error: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    outcome_json: Mapped[str] = mapped_column(Text, default="{}")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")

    steps: Mapped[list[Step]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="Step.idx",
        lazy="selectin",
    )
    label: Mapped[Label | None] = relationship(
        back_populates="run", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class Step(Base):
    __tablename__ = "steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(256))
    #: Full payloads, not previews - the UI expanders and regex assertions need the whole thing.
    args_json: Mapped[str] = mapped_column(Text, default="null")
    output_json: Mapped[str] = mapped_column(Text, default="null")
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps")


class Label(Base):
    __tablename__ = "labels"

    #: One label per run; re-labeling overwrites in place.
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    verdict: Mapped[str] = mapped_column(String(16), index=True)
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    note: Mapped[str] = mapped_column(Text, default="")
    labeled_at: Mapped[datetime] = mapped_column(UtcDateTime)
    #: Seconds the labeler spent on this run, measured client-side. Feeds the median stat.
    seconds_spent: Mapped[float | None] = mapped_column(Float, nullable=True)

    run: Mapped[Run] = relationship(back_populates="label")


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), index=True)
    #: NULL for hand-written cases that did not come from a trace.
    run_id: Mapped[str | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    expectations_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class ExportVersion(Base):
    __tablename__ = "export_versions"

    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    case_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
