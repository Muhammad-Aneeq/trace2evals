"""Verify that `evals/cases.jsonl` still matches what `scripts/dogfood.py` produces.

Why this exists: a stale suite committed in `evals/` is a quiet lie about what was actually labeled.
If someone edits a judgement in `dogfood.py`, or changes the case builder, and forgets to re-export,
the repo keeps claiming the old labels.

Why it is not just `git diff --exit-code`: every case carries a `created_at` timestamp, so a re-export
always differs textually even when nothing substantive changed. Comparing raw bytes would fail on every
CI run and quickly get switched off - a check that cries wolf is worse than no check.

So this compares everything *except* the per-run timestamp: the labels, the derived expectations, the
tags, the inputs, the ids and the schema version.

    uv run python scripts/check_evals_current.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Both paths: `t2e` lives under backend/src, and the judgement list lives in the sibling dogfood script.
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))
sys.path.insert(0, str(REPO_ROOT))

#: Fields that legitimately differ between two runs of the same dogfood.
VOLATILE_FIELDS = ("created_at",)

COMMITTED = REPO_ROOT / "evals" / "cases.jsonl"


def load(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def substantive(records: list[dict]) -> list[dict]:
    """Strip the volatile fields so the comparison is about content, not clock time."""
    return [
        {key: value for key, value in record.items() if key not in VOLATILE_FIELDS}
        for record in records
    ]


def main() -> int:
    if not COMMITTED.is_file():
        print(f"FAIL: {COMMITTED.relative_to(REPO_ROOT)} is missing; run `make dogfood`")
        return 1

    from scripts.dogfood import JUDGEMENTS
    from t2e import exporters, store
    from t2e.casebuilder import suggest_expectations, suggest_tags
    from t2e.config import Settings, set_settings
    from t2e.ingest import ingest_paths

    # Re-run the dogfood against a throwaway database so the developer's own ./.t2e is untouched.
    # `ignore_cleanup_errors` because Windows keeps the SQLite file handle briefly after dispose.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            store.reset_engine()
            set_settings(Settings(db_path=Path(tmp) / "check.db"))
            store.init_db()

            ingest_paths([REPO_ROOT / "fixtures" / "otel", REPO_ROOT / "fixtures" / "langsmith"])

            with store.session_scope() as session:
                for run_id, verdict, tags, note in JUDGEMENTS:
                    if store.get_run(session, run_id) is None:
                        print(
                            f"FAIL: dogfood judges run {run_id!r}, which the fixtures do not produce"
                        )
                        return 1
                    store.set_label(
                        session, run_id, verdict=verdict, tags=tags, note=note, seconds_spent=None
                    )

            with store.session_scope() as session:
                for row in store.list_runs(session, labeled=True, unlabeled_first=False):
                    run = store.run_row_to_trace_run(row)
                    label = row.label
                    label_tags = store.loads(label.tags_json, []) or []
                    expectations = suggest_expectations(run, label.verdict, label_tags)
                    if not expectations:
                        continue
                    store.create_case(
                        session,
                        version="v1",
                        run_id=row.id,
                        input_value=run.input,
                        expectations=expectations,
                        tags=suggest_tags(run, label_tags),
                    )

                regenerated = exporters.cases_jsonl.render(store.list_cases(session, version="v1"))
        finally:
            # Release the SQLite handle before the temp directory is removed.
            store.reset_engine()

    expected = substantive(load(COMMITTED))
    actual = substantive([json.loads(line) for line in regenerated.splitlines() if line.strip()])

    if expected == actual:
        print(f"OK: evals/cases.jsonl is current ({len(expected)} cases, timestamps ignored)")
        return 0

    print("FAIL: evals/cases.jsonl is stale - re-run `make dogfood` and commit the result.")
    print(f"  committed: {len(expected)} case(s)   regenerated: {len(actual)} case(s)")

    by_id = {record.get("case_id"): record for record in expected}
    for record in actual:
        case_id = record.get("case_id")
        if case_id not in by_id:
            print(f"  + {case_id} is new")
        elif by_id[case_id] != record:
            print(f"  ~ {case_id} differs:")
            for key in sorted(set(record) | set(by_id[case_id])):
                if record.get(key) != by_id[case_id].get(key):
                    print(f"      {key}: committed={by_id[case_id].get(key)!r}")
                    print(f"      {key}: current  ={record.get(key)!r}")
    for case_id in by_id:
        if case_id not in {record.get("case_id") for record in actual}:
            print(f"  - {case_id} no longer produced")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
