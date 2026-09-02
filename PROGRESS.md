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

---

## Phase 2 - Labeling UI + keyboard flow + session stats

**Status:** complete

**Done**
- `stats.py`: verdict and failure-tag distribution, median/mean/fastest/slowest seconds per label, a
  30-minute-gap session window, and a plain-text renderer for CI.
- FastAPI layer: every endpoint in spec 03 sec 7, plus three additions recorded as D-014
  (`next-unlabeled`, label deletion for undo, and a served taxonomy). The app factory mounts the built
  SPA from inside the Python package, so `t2e label --serve` is one process.
- Aurora components in `frontend/src/components/aurora/` using the spec 00 A2 tokens (navy `#0B1E3B`,
  emerald `#10B981`, frosted glass): Card, StatBadge, MetricTile, ConfidencePill, RiskTag, EmptyState,
  SyntheticDataBanner, TraceTimeline and VerdictBar, all behind one import line.
- Five screens: Import (dropzone + per-file parse report + PII banner), Runs (all four F3 filters,
  verdict pills, tag chips, unlabeled counter), Labeler, and honest Phase-3 placeholders for Cases and
  Export.
- The keyboard flow: `R`/`W`/`P` verdicts, `1`-`7` tags, `J`/`K` step cursor, `X` expand payload, `N`
  note, `Enter` commit, `S` skip, `U` undo, `?` help. Keystrokes are suppressed while typing in a field
  and modifier combinations pass through to the browser.
- Live session stats on screen while labeling (labels done, median seconds, last label, remaining), with
  the median also persisted server-side so `t2e stats` reports measured data.
- `t2e import` and `t2e label --serve` fully wired, including the CLI's PII warning.

**Verified by running**
- `uv run pytest` - **171 passed** (36 API tests, a scripted 20-run session test, plus Phase 1's suite).
- `npm run typecheck` - clean under `strict` with `noUncheckedIndexedAccess`.
- `npm test` - **13 passed**: the component-level labeling flow (D-004), driving the real `LabelerPage`
  through keystrokes and asserting the request body, auto-advance, payload expansion, cursor movement,
  and that typing in the note field does not fire verdicts.
- `npm run build` - clean; 240 kB JS / 18.7 kB CSS into `backend/src/t2e/web/`.
- **End-to-end against a live server**, not just the test client: `t2e import fixtures/otel
  fixtures/langsmith` imported 16 runs with 10 reported record errors and 5 redactions; `t2e label
  --serve` came up with `ui_built: true`; `/`, `/runs`, `/label`, `/label/<id>` and `/import` all served
  the SPA shell (client-side deep links work); both assets served; a label posted over real HTTP
  returned the next run for auto-advance, decremented the unlabeled count, and moved the median stat.
  The PII fixture served through the API contains `[REDACTED:email]` and no raw address.

**Measurements**
- Median label round trip through the API: **well under 0.5s** (asserted in
  `tests/test_labeling_session.py`), so the tool contributes almost nothing to the 10s human budget.
- The scripted 20-run session drains the queue with no repeats and no skips, and is resumable mid-session.

**Blocked / not verified**
- **B-003**: the browser automation extension was not connected, so the UI has not been driven in a real
  browser. Component tests and live HTTP checks cover behaviour; visual rendering is unverified, which is
  also why the README ships without a screenshot.

**Next**
- Phase 3: the 5 assertion kinds, the case builder with label-derived defaults, the three exporters with
  golden files, and `t2e export` / `t2e stats`.

---

## Phase 3 - Case builder + exports + pytest stub + CLI

**Status:** complete

**Done**
- `assertions.py`: exactly five kinds, no sixth. Each is a pure function over an `AgentRun` that a
  user's adapter returns (a string, a dict, or the dataclass all work). `must_escalate` has documented
  signal precedence (explicit flag > escalation tool call > output keywords) because text matching is
  the weakest evidence. `output_matches_schema` implements a JSON Schema subset in-tree (D-017) and
  fails loudly on an unsupported keyword rather than silently checking less.
- `casebuilder.py`: the tag -> assertion mapping that makes spec 03 F4's "sensible defaults pre-filled
  from labels" real. A failing tool call is used to guess *which* tool a `wrong_tool` case should
  require; `hallucinated_fact` pins the evidence ids the run actually produced; a `right` verdict
  proposes regression guards instead. Every proposal carries a `note` saying why it is there.
- Three exporters: `cases.jsonl` (sorted keys, LF, pinned `schema_version`), the generated
  `test_cases.py`, and Promptfoo YAML that states its own weaknesses in its header.
- Case and export endpoints, including `suggest`, `PATCH` and `DELETE` for the editor.
- `CasesPage` with assertion pickers per kind, and `ExportPage` with format checkboxes and in-browser
  blob downloads (nothing is uploaded to produce a file).
- `t2e export` and `t2e stats` finished; `docs/cases_schema.md` documents the export contract.

**Verified by running**
- `uv run pytest` - **305 passed**: 40 assertion tests, 21 case-builder tests, 22 export golden tests,
  21 case/export API tests, 22 CLI tests, and 8 tests that run the generated suite.
- **The generated stub really runs.** With a correct adapter, `pytest` on the generated directory
  reports **12 passed**; with a deliberately broken adapter it fails and names all five assertion
  kinds; with no adapter it errors on the missing fixture instead of passing vacuously; with an empty
  cases file it refuses to run; with a foreign `schema_version` it demands a re-export.
- `uv run ruff check .` - All checks passed. `npm run typecheck` / `npm test` (13) / `npm run build` -
  all clean.
- **End-to-end at the CLI**: `t2e import` (16 runs) -> label -> build cases -> `t2e export --version v1
  --format jsonl,pytest,promptfoo` wrote all three files -> `t2e stats` reported the distribution and a
  6.15s median. Exit codes verified: 0 on success, 1 for an unknown version, 2 for a bad format.

**Bugs found and fixed while testing**
- `tests/golden/test_cases.py` was being **collected and run by pytest** (6 errors), because the golden
  artefact is itself a pytest module. Fixed with `collect_ignore_glob` (D-019). This would have broken
  `make test` for anyone who cloned the repo.
- An unused `Body` import and an unsorted import block in `routes.py`.

**Measurements**
- Export sizes for a 2-case v1 suite: `cases.jsonl` 1,180 bytes, `test_cases.py` 3,619 bytes,
  `promptfooconfig.yaml` 2,129 bytes.

**Next**
- Phase 4: dogfood the fixtures through the tool, then README, Makefile, CI, docker-compose and
  FINAL_REPORT.

---

## Phase 4 - Redaction + dogfood + README + docs

**Status:** complete, with one item honestly blocked (B-004)

**Done**
- **Zero-telemetry audit**, as promised in the plan: the backend contains no HTTP client and no
  outbound URL beyond the local server address and the dev CORS origin; the frontend has exactly one
  `fetch`, always on a same-origin relative path; there is no analytics, telemetry, CDN or external
  font anywhere in the tree. Redaction (delivered in Phase 1 per D-011) is confirmed to run before
  normalization, so a secret cannot escape through a preview.
- **Dogfood** via `scripts/dogfood.py` - committed and reproducible, not a one-off. It imports both
  formats, applies 16 considered judgements (each with a note explaining the call), builds a case from
  every labeled run, exports v1 into `evals/`, and prints stats.
- `evals/` wired as the CI gate with a `conftest.py` whose `run_agent` fixture skips rather than
  faking an agent: 17 structural checks pass, 17 agent checks skip.
- `Makefile` (13 targets) + `make.ps1` mirror, `.github/workflows/ci.yml` (four jobs, including one
  whose only purpose is to exercise the `Makefile` that B-002 prevented verifying locally),
  `docker-compose.yml` + `Dockerfile`.
- `README.md` with the pitch, a mermaid architecture diagram, quickstart, the keyboard table, an
  HONEST POSITIONING section naming Langfuse/LangSmith/Braintrust/Foundry and saying plainly when to
  use theirs instead, the dogfood findings, a privacy section, and a STATUS table of all four blockers.
- `docs/cases_schema.md`, `evals/README.md`, `FINAL_REPORT.md`.

**Dogfood findings (the actual numbers)**
- 16 runs labeled: **10 right (62%), 4 partial (25%), 2 wrong (12%)**.
- Failure tags across the 6 flagged runs: `ungrounded` 4, `no_escalation` 3, `wrong_tool` 1,
  `bad_args` 1, `hallucinated_fact` 1, `format_break` 0, `other` 0.
- **The interesting result:** the dominant failure was not a wrong tool call but an unsupported claim.
  Three of the four `ungrounded` runs reached the *correct* conclusion and then asserted it with no
  cited evidence - a distribution that a pass/fail accuracy metric would have hidden entirely.
- The exported suite: 16 cases, 27 assertions - `must_cite` in 14, `must_call_tool` in 10,
  `must_escalate` in 3, and no case with zero expectations.

**Verified by running**
- `uv run pytest` - **305 passed**; `uv run ruff check .` - clean.
- `npm run typecheck`, `npm test` (13 passed), `npm run build` - clean.
- `uv run python scripts/dogfood.py` - full loop, 16 runs -> 16 cases -> `evals/cases.jsonl` (8,500
  bytes) + `evals/test_cases.py` (3,620 bytes).
- `uv run pytest evals/` and `./make.ps1 eval` - 17 passed, 17 skipped.
- `./make.ps1 help` - all targets listed.
- Assertion-kind counts recomputed from the exported file rather than tallied by hand (my hand count
  was wrong by one, and the README/evals docs were corrected to match the file).

**Blocked**
- **B-004**: no human labeling session could be timed (no human, no browser). The dogfood records
  `seconds_spent=None` rather than inventing durations, so `t2e stats` prints "no timed labels yet".
  What *is* measured and reported: the tool's own median label round trip is under 0.5s, so the tool
  contributes well under a second of the 10s budget. The `<10s median` target itself remains untested.

**Definition of done**
- Fully verified except three spec 00 launch-checklist items that need a browser or a camera:
  screenshot, demo video, launch post. All three are marked unticked with reasons in PLAN.md section 6
  rather than quietly claimed.
