# Trace2Evals (`t2e`)

**Your production agent failures are your best test cases. This turns them into eval cases you own.**

> ⚠️ **All data in this repository is synthetic.** No real traces were provided
> (see [BLOCKERS.md](BLOCKERS.md) B-001); fixtures under `fixtures/` are hand-authored to match real
> wire formats.

> 🚧 **This README is under construction.** It is completed in Phase 4 of [PLAN.md](PLAN.md) with the
> architecture diagram, quickstart, honest positioning, dogfood findings, and status. Current build state
> is tracked in [PROGRESS.md](PROGRESS.md).

---

## What it does

Import agent traces from OpenTelemetry JSON or LangSmith run exports, label them fast in a keyboard-first
UI (Right / Wrong / Partial plus a failure-tag taxonomy), and export versioned, framework-neutral eval
cases: `cases.jsonl`, a generated `test_cases.py` pytest stub, and optional Promptfoo YAML.

Runs fully offline. No LLM calls, no telemetry, no network at runtime.

## Status

See [PROGRESS.md](PROGRESS.md) for what is built and [BLOCKERS.md](BLOCKERS.md) for what is not.
