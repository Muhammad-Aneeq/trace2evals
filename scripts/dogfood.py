"""Reproducible dogfood run: import the fixtures, label them, build cases, export v1.

Spec 03 sec 10 requires the tool to be used on real traces before launch, with findings in the README.
No real traces were provided (BLOCKERS.md **B-001**), so this runs the full loop over the synthetic
fixtures instead.

The verdicts and tags below are **considered judgements about the actual content of each fixture**, not
random filler - each one has a note explaining the call, and several are deliberately unflattering to
the agent being labeled. That is the part of a dogfood that carries information: the label distribution
and the failure taxonomy.

What this script deliberately does **not** fabricate is `seconds_spent`. A human labeling session was
never timed (BLOCKERS.md **B-004**), so no per-label duration is recorded and `t2e stats` honestly
reports "no timed labels yet" rather than a made-up median.

Run with:  uv run python scripts/dogfood.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from t2e import exporters, store  # noqa: E402
from t2e.casebuilder import suggest_expectations, suggest_tags  # noqa: E402
from t2e.ingest import ingest_paths  # noqa: E402
from t2e.stats import collect, render_text  # noqa: E402

#: (run_id, verdict, tags, note) - one considered judgement per imported run.
JUDGEMENTS: list[tuple[str, str, list[str], str]] = [
    # --- OpenTelemetry fixtures ---
    (
        "4f2a9c1e8b7d6a5f3e2d1c0b9a8f7e6d",
        "right",
        [],
        "Correct partial-payment diagnosis; residual arithmetic checks out and every claim cites an id.",
    ),
    (
        "7c1d5e9a3f8b2d6c4a0e7f1b8d3c5a92",
        "right",
        [],
        "Correctly rejected the duplicate: distinct POs and consecutive retainer periods, both cited.",
    ),
    (
        "9e4b7d2c6a1f5e8b3d0c9a2f7e4b1d6c",
        "wrong",
        ["hallucinated_fact", "no_escalation", "ungrounded"],
        "The lookup returned NotFoundError and the agent invented a Denver facilities team and a "
        "regional controller approval. Nothing in the trace supports either. It should have escalated.",
    ),
    (
        "1a2b3c4d5e6f70819a2b3c4d5e6f7081",
        "right",
        [],
        "Routed to the FX specialist, computed the revaluation delta, and escalated to treasury with "
        "the rate source cited. Correct behaviour including the handoff.",
    ),
    (
        "2b3c4d5e6f708192ab3c4d5e6f708192",
        "right",
        [],
        "Counterparty matched on sort-code/account at 0.94 and reported the basis of the match.",
    ),
    (
        "5f6e7d8c9b0a1234f5e6d7c8b9a01234",
        "partial",
        ["ungrounded"],
        "The materiality arithmetic is right (55.00 < 100.00), but 'auto-write-off is appropriate' is a "
        "policy claim with no cited authority. Right answer, unsupported reasoning.",
    ),
    (
        "aaaa1111bbbb2222cccc3333dddd4444",
        "right",
        [],
        "Credit note correctly matched to the invoice on shared PO and counterparty, both cited.",
    ),
    (
        "eeee5555ffff6666aaaa7777bbbb8888",
        "partial",
        ["ungrounded"],
        "'Yes - immaterial, auto write-off' is probably correct but cites no threshold and no evidence. "
        "Not defensible to an auditor as written.",
    ),
    # --- LangSmith fixtures ---
    (
        "3f8c1a90-0001-4a11-9c01-aa0000000001",
        "right",
        [],
        "Matched on amount plus counterparty, and explicitly noted that the reference field was blank "
        "rather than quietly ignoring it.",
    ),
    (
        "4a9d2b01-0002-4b22-8d02-bb0000000001",
        "wrong",
        ["wrong_tool", "bad_args", "no_escalation"],
        "Queried the GL by invoice id when the claim was about a bank payment, then searched the bank "
        "feed with a single-day window. Two empty results became 'the supplier is likely mistaken' "
        "instead of a wider search or an escalation.",
    ),
    (
        "5b0e3c12-0003-4c33-9e03-cc0000000001",
        "partial",
        ["no_escalation"],
        "The upstream ledger returned 503 and the agent correctly did not invent an answer - but it "
        "also never escalated, so the break silently went nowhere. Failing safe is not the same as "
        "failing usefully.",
    ),
    (
        "6c1f4d23-0004-4d44-8f04-dd0000000001",
        "right",
        [],
        "Found the end-dated schedule, explained why August produced no reversal, escalated to the "
        "close checklist owner, and cited both ids.",
    ),
    (
        "7d2a5e34-0005-4e55-9a05-ee0000000001",
        "partial",
        ["ungrounded"],
        "Correct call on materiality but no cited threshold or policy; same weakness as the OTel "
        "materiality run.",
    ),
    (
        "7d2a5e34-0005-4e55-9a05-ee0000000002",
        "right",
        [],
        "Identified the instalment schedule and correctly reported the residual as expected, with ids.",
    ),
    (
        "8e3b6f45-0006-4f66-8b06-ff0000000001",
        "right",
        [],
        "Refused to approve the write-off while the dispute was open and escalated to the AR manager. "
        "This is the behaviour the no_escalation tag exists to contrast with.",
    ),
    (
        "9f4c7a56-0007-4a77-9c07-aa1000000009",
        "right",
        [],
        "Exact match confirmed on amount, date and PO, all cited.",
    ),
]


def main() -> int:
    fixtures = REPO_ROOT / "fixtures"

    print("=" * 78)
    print("STEP 1 - import both formats")
    print("=" * 78)
    reports = ingest_paths([fixtures / "otel", fixtures / "langsmith"])
    imported = sum(report.runs_imported for report in reports)
    errors = sum(len(report.errors) for report in reports)
    redactions = sum(report.redactions for report in reports)
    print(f"{imported} runs from {len(reports)} files; {errors} record errors; {redactions} redactions")

    print()
    print("=" * 78)
    print("STEP 2 - label every run")
    print("=" * 78)
    with store.session_scope() as session:
        known = {row.id for row in store.list_runs(session)}
        judged = {run_id for run_id, *_ in JUDGEMENTS}

        missing = judged - known
        unjudged = known - judged
        if missing:
            print(f"WARNING: judgements for runs that were not imported: {sorted(missing)}")
        if unjudged:
            print(f"WARNING: imported runs with no judgement: {sorted(unjudged)}")

        for run_id, verdict, tags, note in JUDGEMENTS:
            if run_id not in known:
                continue
            store.set_label(
                session,
                run_id,
                verdict=verdict,
                tags=tags,
                note=note,
                # Deliberately None: no human session was timed (B-004). Better an absent
                # measurement than an invented one.
                seconds_spent=None,
            )
            print(f"  {verdict:8} {','.join(tags) or '-':40} {run_id[:16]}")

    print()
    print("=" * 78)
    print("STEP 3 - build a case from every labeled run")
    print("=" * 78)
    with store.session_scope() as session:
        existing = {case.run_id for case in store.list_cases(session, version="v1")}
        built = skipped = 0
        for row in store.list_runs(session, labeled=True, unlabeled_first=False):
            if row.id in existing:
                continue
            run = store.run_row_to_trace_run(row)
            label = row.label
            tags = store.loads(label.tags_json, []) or []
            expectations = suggest_expectations(run, label.verdict, tags)
            if not expectations:
                # A correct run with nothing to guard produces no useful case; say so rather than
                # exporting an assertion-free case that would pass forever.
                skipped += 1
                print(f"  skipped {row.id[:16]} ({label.verdict}): no assertion could be derived")
                continue
            store.create_case(
                session,
                version="v1",
                run_id=row.id,
                input_value=run.input,
                expectations=expectations,
                tags=suggest_tags(run, tags),
            )
            built += 1
            kinds = ", ".join(item["kind"] for item in expectations)
            print(f"  built   {row.id[:16]} ({label.verdict}): {kinds}")
        print(f"{built} case(s) built, {skipped} run(s) yielded no assertions")

    print()
    print("=" * 78)
    print("STEP 4 - export v1 into evals/")
    print("=" * 78)
    with store.session_scope() as session:
        cases = store.list_cases(session, version="v1")
        result = exporters.write(
            cases,
            version="v1",
            formats=["jsonl", "pytest"],
            out_dir=REPO_ROOT / "evals",
        )
        store.record_export_version(
            session,
            version="v1",
            case_count=len(cases),
            notes="dogfood run over the synthetic fixtures (see scripts/dogfood.py)",
        )
    for entry in result["files"]:
        print(f"  {entry['file']}  ({entry['bytes']} bytes)")

    print()
    print("=" * 78)
    print("STEP 5 - stats")
    print("=" * 78)
    with store.session_scope() as session:
        print(render_text(collect(session)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
