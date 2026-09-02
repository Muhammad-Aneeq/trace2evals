# PROGRESS.md

Journal of what actually happened, updated at the end of every phase. Claims here are things that were run,
not things that were intended.

---

## Phase 0 - Read specs, plan, scaffold

**Status:** complete

**Done**
- Read all three ground-truth documents in full: `spec_00_shared_foundations.md` (portfolio rules, A2 design
  tokens, F stack lock, E definition of done), `spec_03_trace2evals.md` (the spec: F1-F6, data model,
  API surface, testing, privacy, milestones), and the Project 3 + Shared Foundations sections of
  `ten_projects_technical_plans.md`.
- Inspected the working directory: no `./seed_traces/`, no application code - the repo contained only the
  three spec files. Logged as **B-001** with a synthetic-fixture workaround.
- Verified the toolchain: python 3.12.10, uv 0.11.23, node 24.14.1, npm 11.11.0, git 2.53.0 all present;
  `make` and `pipx` absent. Logged `make` as **B-002** with a `make.ps1` mirror workaround.
- Wrote `PLAN.md`: project summary, full file map, four phases with spec-quoted acceptance criteria and
  per-phase test plans, external-dependency table with fallbacks, and a decisions log (D-001 to D-008).
- Wrote `BLOCKERS.md` (B-001, B-002) and this journal.

- Scaffolded the repo: `git init` (branch `main`), `.gitignore`, MIT `LICENSE`, `.python-version` (3.12),
  specs moved into `docs/`, directory skeleton for backend/frontend/tests/fixtures/evals/CI, and a
  `pyproject.toml` declaring the `t2e` console entrypoint with a hatchling build over `backend/src/t2e`.
- Wrote the final CLI argument surface (`cli.py`, stdlib argparse) with all four commands from spec 03 F6.
  Command bodies are honest stubs in `cli_commands.py` that exit 70 rather than fake success; they are
  filled in as their layers land.
- README skeleton written in the spec 00 A1 mandated section order (it is also required for the build
  backend to resolve metadata).

**Verified by running**
- `uv sync --extra dev` - resolves and installs cleanly (fastapi 0.121, pydantic 2.12, sqlalchemy 2.0.52,
  uvicorn 0.52, pytest 9.0, ruff 0.16). Zero LLM or cloud dependencies in the tree.
- `uv run t2e --help` - prints all four commands (`import`, `label`, `export`, `stats`). **Acceptance met.**
- `uv run pytest --collect-only` - exits 5 ("no tests collected"), i.e. collection works and there are
  legitimately no tests yet. **Acceptance met.**

**Measurements**
- None yet. First numbers land in Phase 1 (parser snapshot counts) and Phase 2 (label timing).

**Next**
- Phase 1: schemas, ORM/store, both parsers, normalizer, 12 synthetic fixtures, snapshot tests.

---

## Phase 1 - Parsers + normalizer + store + fixtures

**Status:** complete

**Done**
- `schemas.py` with the F2 contract pinned: `Step`, `TraceRun`, `Outcome`, plus `RawStep`/`RawRun` as the
  parser-to-normalizer intermediate and `ParseReport`/`RecordError` for per-record error reporting.
  `spec_dump()` on `Step`/`TraceRun` emits *exactly* the F2 fields, so the contract is asserted
  independently of the storage extras.
- `models.py` + `store.py`: the five specced tables, plus repository functions for save/list/filter,
  unlabeled-first ordering, `next_unlabeled` (auto-advance), labels, cases and export versions.
- **OTel importer**: OTLP `resourceSpans` walk plus the two flatter shapes, full `AnyValue` decoding,
  tolerant GenAI attribute alias tables, span-event prompts, `status.code`/`exception`-event errors, and
  span classification into llm / tool / handoff with the root agent span treated as the run container.
- **LangSmith importer**: JSONL (and whole-file array) records, `run_type` mapping, root-chain-as-container,
  `dotted_order` ordering, and `parent_run_id` walking for exports with no `trace_id`.
- `normalizer.py` as the single place that decides previews, latency, ordering and outcome, so both
  formats normalize identically. Renders chat messages and LangChain `generations` readably.
- `redaction.py` implemented in full and wired *before* normalization (D-011), with a Luhn check so
  16-digit reference numbers are not mistaken for card numbers.
- `ingest.py`: the shared parse -> redact -> normalize -> store pipeline (D-012).
- 12 synthetic fixtures (6 per format) covering clean, tool-heavy, tool-error, handoff, minimal and
  malformed cases, with provenance in `fixtures/README.md` and the mapping tables in `docs/importers.md`.

**Verified by running**
- `uv run pytest` - **135 passed**, covering 12 snapshot-tested normalizations, the malformed-record
  contract for both formats, 27 normalizer unit tests, 20 store tests, 22 redaction tests and 13 ingest
  tests. Snapshots re-run clean after regeneration, so they are stable rather than self-confirming.
- `uv run ruff check .` - **All checks passed.**

**Bugs found and fixed while testing** (each was a real defect, not a test artefact)
- SQLite silently discards `tzinfo`, so a reloaded run compared unequal to the one written. Fixed with a
  `UtcDateTime` type decorator (D-013).
- On re-import, clearing the steps relationship left it cached as empty, so replacement steps were
  invisible for the rest of the session. Fixed by appending through the relationship.
- A trace of pure infrastructure spans was imported as an empty, unlabelable run; it is now reported as
  an error instead.
- Tool-arg previews unwrapped single-key dicts, turning `{"po":"PO-76550"}` into a contextless
  `"PO-76550"`. Now only genuine wrapper keys are unwrapped.
- LangSmith `{"generations": [...]}` outputs rendered as raw JSON instead of the completion text.

**Measurements**
- 12 fixtures parse to **16 runs and 45 steps**. All 10 reported record errors come from the two
  malformed fixtures (5 each), and both of those still import 2 intact runs apiece - which is exactly the
  strict-but-forgiving contract holding.
- Full suite runtime: ~1.4s.

**Next**
- Phase 2: FastAPI routes, the aurora components, and the keyboard labeling flow with session stats.
