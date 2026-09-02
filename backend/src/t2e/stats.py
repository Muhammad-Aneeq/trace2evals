"""Label distribution, case counts, and the median-seconds-per-label speed metric.

Spec 03 sec 9 makes speed the product's claim ("target <10s median per simple label; measure and
show session stats"), so the median is computed from persisted per-label timings, not estimated.
The same numbers back `GET /api/stats`, the labeler's live session panel, and `t2e stats` in CI.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from t2e import store
from t2e.models import Case, ExportVersion, Label, Run
from t2e.schemas import FAILURE_TAGS

#: A label session is a contiguous stretch of work; a gap longer than this starts a new one.
SESSION_GAP = timedelta(minutes=30)

#: The target from spec 03 sec 9, asserted by the timing test and displayed in the UI.
TARGET_MEDIAN_SECONDS = 10.0


@dataclass
class Stats:
    runs_total: int = 0
    runs_by_source: dict[str, int] = field(default_factory=dict)
    runs_labeled: int = 0
    runs_unlabeled: int = 0
    runs_with_error: int = 0

    verdicts: dict[str, int] = field(default_factory=dict)
    failure_tags: dict[str, int] = field(default_factory=dict)

    labels_timed: int = 0
    median_seconds_per_label: float | None = None
    mean_seconds_per_label: float | None = None
    fastest_seconds: float | None = None
    slowest_seconds: float | None = None

    session_labels: int = 0
    session_median_seconds: float | None = None

    cases_total: int = 0
    cases_by_version: dict[str, int] = field(default_factory=dict)
    export_versions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def labeled_fraction(self) -> float:
        return self.runs_labeled / self.runs_total if self.runs_total else 0.0

    @property
    def meets_speed_target(self) -> bool | None:
        """None when nothing has been timed yet - an untested claim is not a passing one."""
        if self.median_seconds_per_label is None:
            return None
        return self.median_seconds_per_label < TARGET_MEDIAN_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs_total": self.runs_total,
            "runs_by_source": self.runs_by_source,
            "runs_labeled": self.runs_labeled,
            "runs_unlabeled": self.runs_unlabeled,
            "runs_with_error": self.runs_with_error,
            "labeled_fraction": round(self.labeled_fraction, 4),
            "verdicts": self.verdicts,
            "failure_tags": self.failure_tags,
            "labels_timed": self.labels_timed,
            "median_seconds_per_label": self.median_seconds_per_label,
            "mean_seconds_per_label": self.mean_seconds_per_label,
            "fastest_seconds": self.fastest_seconds,
            "slowest_seconds": self.slowest_seconds,
            "session_labels": self.session_labels,
            "session_median_seconds": self.session_median_seconds,
            "target_median_seconds": TARGET_MEDIAN_SECONDS,
            "meets_speed_target": self.meets_speed_target,
            "cases_total": self.cases_total,
            "cases_by_version": self.cases_by_version,
            "export_versions": self.export_versions,
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def collect(session: Session) -> Stats:
    """One pass over the store. Cheap enough to call on every label commit."""
    stats = Stats()

    runs = list(session.scalars(select(Run)))
    stats.runs_total = len(runs)
    stats.runs_by_source = dict(sorted(Counter(r.source for r in runs).items()))
    stats.runs_with_error = sum(1 for r in runs if r.has_error)

    labels = list(session.scalars(select(Label)))
    stats.runs_labeled = len(labels)
    stats.runs_unlabeled = stats.runs_total - stats.runs_labeled

    # Every verdict is reported, including zeros, so a distribution reads honestly.
    verdict_counts = Counter(label.verdict for label in labels)
    stats.verdicts = {
        verdict: verdict_counts.get(verdict, 0) for verdict in ("right", "wrong", "partial")
    }

    tag_counts: Counter[str] = Counter()
    for label in labels:
        for tag in store.loads(label.tags_json, []) or []:
            tag_counts[str(tag)] += 1
    stats.failure_tags = {
        tag: tag_counts[tag] for tag in FAILURE_TAGS if tag_counts.get(tag)
    }

    timings = [label.seconds_spent for label in labels if label.seconds_spent is not None]
    stats.labels_timed = len(timings)
    if timings:
        stats.median_seconds_per_label = _round(statistics.median(timings))
        stats.mean_seconds_per_label = _round(statistics.fmean(timings))
        stats.fastest_seconds = _round(min(timings))
        stats.slowest_seconds = _round(max(timings))

    session_labels = _current_session(labels)
    stats.session_labels = len(session_labels)
    session_timings = [
        label.seconds_spent for label in session_labels if label.seconds_spent is not None
    ]
    if session_timings:
        stats.session_median_seconds = _round(statistics.median(session_timings))

    cases = list(session.scalars(select(Case)))
    stats.cases_total = len(cases)
    stats.cases_by_version = dict(sorted(Counter(c.version for c in cases).items()))

    stats.export_versions = [
        {
            "version": row.version,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "case_count": row.case_count,
            "notes": row.notes,
        }
        for row in session.scalars(select(ExportVersion).order_by(ExportVersion.created_at))
    ]

    return stats


def _current_session(labels: list[Label]) -> list[Label]:
    """Labels belonging to the most recent contiguous stretch of work."""
    timed = sorted(
        (label for label in labels if label.labeled_at is not None),
        key=lambda label: label.labeled_at,
    )
    if not timed:
        return []

    current: list[Label] = [timed[-1]]
    for index in range(len(timed) - 2, -1, -1):
        if timed[index + 1].labeled_at - timed[index].labeled_at > SESSION_GAP:
            break
        current.append(timed[index])
    return list(reversed(current))


# --- CLI rendering ------------------------------------------------------------------------------


def render_text(stats: Stats) -> str:
    """Plain, greppable output for CI logs (spec 03 US4: `t2e stats` in CI)."""
    lines: list[str] = []
    lines.append("t2e stats")
    lines.append("=========")
    lines.append(f"runs                 {stats.runs_total}")
    for source, count in stats.runs_by_source.items():
        lines.append(f"  {source:<18} {count}")
    lines.append(f"labeled              {stats.runs_labeled}")
    lines.append(f"unlabeled            {stats.runs_unlabeled}")
    lines.append(f"with error           {stats.runs_with_error}")
    lines.append("")
    lines.append("verdicts")
    for verdict, count in stats.verdicts.items():
        share = f"{count / stats.runs_labeled:.0%}" if stats.runs_labeled else "-"
        lines.append(f"  {verdict:<18} {count:>4}  {share}")

    lines.append("")
    lines.append("failure tags")
    if stats.failure_tags:
        for tag, count in sorted(stats.failure_tags.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {tag:<18} {count:>4}")
    else:
        lines.append("  (none recorded)")

    lines.append("")
    lines.append("labeling speed")
    if stats.median_seconds_per_label is None:
        lines.append("  no timed labels yet")
    else:
        verdict = "PASS" if stats.meets_speed_target else "OVER TARGET"
        lines.append(f"  median             {stats.median_seconds_per_label}s  ({verdict})")
        lines.append(f"  mean               {stats.mean_seconds_per_label}s")
        lines.append(f"  fastest / slowest  {stats.fastest_seconds}s / {stats.slowest_seconds}s")
        lines.append(f"  timed labels       {stats.labels_timed}")
        lines.append(f"  target             <{TARGET_MEDIAN_SECONDS}s median")

    lines.append("")
    lines.append(f"cases                {stats.cases_total}")
    for version, count in stats.cases_by_version.items():
        lines.append(f"  {version:<18} {count}")
    if stats.export_versions:
        lines.append("")
        lines.append("exports")
        for export in stats.export_versions:
            lines.append(
                f"  {export['version']:<18} {export['case_count']} cases  {export['created_at']}"
            )
    return "\n".join(lines)

