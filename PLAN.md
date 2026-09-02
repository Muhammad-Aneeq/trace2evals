# PLAN.md - Trace2Evals (`t2e`)

> Living working document. Ticked as tasks complete. Every deviation is appended to section 5 DECISIONS LOG.
> Status legend: `[ ]` todo | `[x]` done | `[~]` in progress | `[BLOCKED]` see BLOCKERS.md

---

## 1. PROJECT SUMMARY

Trace2Evals turns agent traces that already exist into eval cases you own. It imports exactly two
formats excellently (OpenTelemetry JSON with GenAI semantic conventions, LangSmith run-export JSONL),
normalizes them into one `TraceRun` model, and puts them through a keyboard-first labeling UI where a
human hits R/W/P plus a failure tag and auto-advances - target under 10 seconds median per simple label.
Labeled runs become versioned eval cases (capped at 5 assertion kinds) exported as `cases.jsonl`, a
generated `test_cases.py` pytest stub, and optional Promptfoo YAML. Zero LLM calls, zero telemetry, fully
offline: the wedge is portability and labeling speed, not intelligence - platform trace-to-dataset
features already exist but are locked inside their platforms.

---

## 2. FILE MAP

Complete intended repo tree. One line of purpose per file.

```
trace2evals/
├── PLAN.md                          # this document
├── PROGRESS.md                      # per-phase progress journal, updated at each phase end
├── BLOCKERS.md                      # what/tried/needed/workaround for every blocker
├── FINAL_REPORT.md                  # written last: demoable state, commands, blockers, next three
├── README.md                        # pitch, mermaid architecture, quickstart, HONEST POSITIONING, STATUS, dogfood findings
├── LICENSE                          # MIT (spec 00 A1)
├── Makefile                         # dev, test, eval, export, up, down (spec 00 A1)
├── make.ps1                         # Windows fallback for Makefile targets (make is absent locally; BLOCKERS.md)
├── docker-compose.yml               # optional local stack (spec 03 sec 12 "docker-compose optional")
├── pyproject.toml                   # uv/pip project, deps, `t2e` console entrypoint, pytest+ruff config
├── .gitignore                       # python/node/db/dist artifacts
├── .python-version                  # pin 3.12 for uv
├── .github/workflows/ci.yml         # ruff + pytest + frontend build + evals gate
│
├── docs/
│   ├── spec_00_shared_foundations.md    # ground truth (moved from repo root)
│   ├── spec_03_trace2evals.md           # ground truth (moved from repo root)
│   ├── ten_projects_technical_plans.md  # ground truth (moved from repo root)
│   ├── cases_schema.md                  # documented cases.jsonl schema + assertion kinds (spec 03 F5)
│   └── importers.md                     # what each importer accepts, field mapping, error semantics
│
├── backend/
│   └── src/t2e/
│       ├── __init__.py              # version constant
│       ├── __main__.py              # `python -m t2e` -> cli.main()
│       ├── cli.py                   # t2e import / label --serve / export --version vN / stats
│       ├── config.py                # pydantic-settings: db path, redaction toggles, host/port
│       ├── schemas.py               # Pydantic v2: TraceRun, Step, Label, Case, Assertion, ParseReport
│       ├── models.py                # SQLAlchemy ORM: runs, steps, labels, cases, export_versions
│       ├── store.py                 # engine/session factory, schema init, repository functions
│       ├── redaction.py             # regex redaction on import + PII-lookalike detection
│       ├── assertions.py            # the 5 assertion kinds: evaluation logic + helpers reused by generated tests
│       ├── stats.py                 # label distribution, median seconds/label, case counts (CI-friendly)
│       ├── parsers/
│       │   ├── __init__.py          # parser registry + format sniffing by extension/shape
│       │   ├── base.py              # ParseReport/RecordError types, strict-but-forgiving helpers
│       │   ├── otel.py              # OpenTelemetry JSON -> raw runs (GenAI semconv: gen_ai.* attrs, tool spans)
│       │   └── langsmith.py         # LangSmith run-export JSONL -> raw runs
│       ├── normalizer.py            # raw parser output -> normalized TraceRun (kind mapping, latency, previews, ordering)
│       ├── exporters/
│       │   ├── __init__.py          # format registry
│       │   ├── cases_jsonl.py       # versioned cases.jsonl writer
│       │   ├── pytest_stub.py       # generated test_cases.py (imports t2e.assertions helpers)
│       │   ├── promptfoo.py         # optional Promptfoo YAML export
│       │   └── templates.py         # string templates for generated files (no template-engine dep)
│       ├── api/
│       │   ├── __init__.py
│       │   ├── app.py               # FastAPI app factory, CORS for dev, static SPA mount
│       │   └── routes.py            # import, runs, runs/{id}, runs/{id}/label, cases, export, stats
│       └── web/                     # built SPA assets (vite build output, gitignored; served by label --serve)
│
├── frontend/
│   ├── package.json                 # vite, react, ts, tailwind, tanstack-query, vitest, RTL
│   ├── vite.config.ts               # build -> backend/src/t2e/web, dev proxy /api -> :8765
│   ├── tsconfig.json                # strict TS
│   ├── tailwind.config.js           # aurora tokens (navy #0B1E3B, emerald #10B981)
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx                 # React root + QueryClient + router
│       ├── App.tsx                  # shell: nav, SyntheticDataBanner, routes
│       ├── index.css                # tailwind layers + frosted-glass utilities + fonts
│       ├── types.ts                 # TS mirrors of backend schemas
│       ├── api.ts                   # typed fetch client for the API surface
│       ├── components/aurora/
│       │   ├── index.ts             # single import line (spec 00 A2 acceptance)
│       │   ├── tokens.ts            # navy/emerald/glass token constants
│       │   ├── Card.tsx             # frosted-glass card
│       │   ├── StatBadge.tsx        # label/value pill
│       │   ├── MetricTile.tsx       # session-stats tile
│       │   ├── ConfidencePill.tsx   # verdict/confidence pill (right/wrong/partial colors)
│       │   ├── RiskTag.tsx          # failure-tag chip
│       │   ├── TraceTimeline.tsx    # step cards with expandable payloads (the labeling centrepiece)
│       │   ├── EmptyState.tsx
│       │   ├── SyntheticDataBanner.tsx  # "All data is synthetic" warning banner
│       │   └── VerdictBar.tsx       # R/W/P + tag taxonomy + keyboard legend (build adaptation 1)
│       ├── hooks/
│       │   ├── useHotkeys.ts        # keyboard verdict/tag/navigation bindings
│       │   └── useSessionStats.ts   # client-side per-label timing -> median seconds
│       └── pages/
│           ├── ImportPage.tsx       # dropzone + per-file parse report + PII warning banner
│           ├── RunsPage.tsx         # runs table, filters (source, has-error, duration, unlabeled-first)
│           ├── LabelerPage.tsx      # TraceTimeline + VerdictBar + auto-advance + session stats
│           ├── CasesPage.tsx        # cases by version, expectation editor with assertion pickers
│           └── ExportPage.tsx       # version notes, format checkboxes, download
│
├── tests/
│   ├── conftest.py                  # tmp db, client fixtures, fixture-path helpers
│   ├── test_parsers_otel.py         # 6 OTel fixtures incl. malformed -> snapshot
│   ├── test_parsers_langsmith.py    # 6 LangSmith fixtures incl. malformed -> snapshot
│   ├── test_normalizer.py           # kind mapping, ordering, latency, preview truncation
│   ├── test_store.py                # persistence + unlabeled-first query
│   ├── test_redaction.py            # regex redaction + PII-lookalike detection
│   ├── test_assertions.py           # all 5 assertion kinds pass/fail paths
│   ├── test_api.py                  # every endpoint in spec 03 sec 7
│   ├── test_exports_golden.py       # golden-file compare: cases.jsonl, test_cases.py, promptfoo.yaml
│   ├── test_generated_pytest_stub.py# generated stub is importable and its tests execute
│   ├── test_cli.py                  # import/export/stats exit codes + CI-friendly output
│   ├── test_labeling_session.py     # scripted 20-run labeling session, timed (see DECISION D-004)
│   ├── snapshots/                   # normalization snapshots (JSON)
│   └── golden/                      # cases.jsonl, test_cases.py, promptfoo.yaml golden files
│
├── fixtures/                        # synthetic trace fixtures (marked synthetic)
│   ├── README.md                    # provenance: hand-authored synthetic, why (no seed_traces/)
│   ├── otel/                        # 6 files: clean, tool-heavy, error, handoff, minimal, malformed
│   └── langsmith/                   # 6 files: clean, tool-heavy, error, handoff, minimal, malformed
│
├── evals/                           # the brand folder (spec 00 A1) - CI eval gate
│   ├── README.md                    # how the gate works
│   ├── cases.jsonl                  # committed export from the dogfood session
│   └── test_cases.py                # committed generated stub, run by `make eval`
│
└── seed_traces/                     # real dogfood traces if provided (ABSENT -> BLOCKERS.md B-001)
```

---

## 3. PHASES

### PHASE 0 - Read specs, plan, scaffold

**Objective:** ground truth absorbed, PLAN.md written, repo skeleton that installs and tests clean.

- [x] Read `spec_00_shared_foundations.md` fully
- [x] Read `spec_03_trace2evals.md` fully
- [x] Read `ten_projects_technical_plans.md` (Shared Foundations + Project 3)
- [x] Inspect `./seed_traces/` -> **absent**; log B-001, plan synthetic fixtures (adaptation 3)
- [x] Verify toolchain: python 3.12.10 ok, uv 0.11.23 ok, node 24.14.1 ok, npm 11.11.0 ok, git 2.53 ok, `make` **absent** -> B-002
- [x] Write this PLAN.md
- [x] `git init`, `.gitignore`, MIT LICENSE, move specs into `docs/`
- [x] `pyproject.toml` with `t2e` entrypoint; `uv sync` succeeds
- [x] Create BLOCKERS.md (B-001 seed_traces, B-002 make) and PROGRESS.md
- [x] Commit: "Phase 0: specs read, PLAN.md, repo scaffold"

**Test plan:** `uv run pytest` collects zero tests without error; `uv run t2e --help` prints the four commands.
**Risk:** none material; the only unknown is fixture realism, addressed in Phase 1.

---

### PHASE 1 - Parsers + normalizer + store + fixtures

**Objective:** both importers ingest real-shaped files into a normalized, persisted `TraceRun` model with a
per-record error report.

Acceptance criteria quoted from spec:
> F1 Importers: (a) OpenTelemetry JSON (GenAI semantic-convention aware: model calls, tool spans),
> (b) LangSmith run export JSONL. **Strict-but-forgiving parsing with per-record error report.** (spec 03 sec 4)

> F2 Normalized TraceRun model: {run_id, source, started, input, steps[ {kind: llm|tool|handoff, name,
> args_preview, output_preview, latency, error?} ], outcome, meta}. (spec 03 sec 4)

> Parser fixtures: **6 real-shaped sample files per format incl. malformed records; snapshot-tested
> normalization** (spec 03 sec 10)

- [x] `schemas.py`: `Step`, `TraceRun`, `ParseReport`, `RecordError` - field names exactly as F2
- [x] `models.py` + `store.py`: tables `runs, steps, labels, cases, export_versions` exactly as spec 03 sec 6
- [x] `parsers/base.py`: `ParseReport` accumulation; a bad record never aborts the file
- [x] `parsers/otel.py`: resourceSpans/scopeSpans/spans walk; `gen_ai.*` attrs -> llm steps;
      tool spans -> tool steps; span links/parent -> handoff; nanosecond timestamps -> latency ms
- [x] `parsers/langsmith.py`: JSONL run records; `run_type` (llm/tool/chain) -> kind; nested inputs/outputs;
      `error` field preserved
- [x] `parsers/__init__.py`: sniff format by extension + shape, explicit `--format` override
- [x] `normalizer.py`: group spans into runs by trace_id/root, order steps, truncate previews, derive outcome
- [x] Redaction implemented in full and wired at the import call site - moved earlier, see D-011
- [x] 6 OTel fixtures + 6 LangSmith fixtures (synthetic, marked) incl. one malformed each
- [x] `fixtures/README.md` provenance note
- [x] Tests: parser snapshots both formats, malformed-record handling, normalizer unit tests, store tests
- [x] `ingest.py` pipeline (parse -> redact -> normalize -> store) shared by CLI and API - see D-012
- [x] `docs/importers.md`: accepted shapes, GenAI alias tables, classification order, error semantics
- [x] Commit: "Phase 1: importers, normalizer, store, fixtures"

**Test plan:** `test_parsers_otel.py` / `test_parsers_langsmith.py` snapshot every fixture's normalized
output to `tests/snapshots/`; malformed fixtures assert `report.errors` is non-empty AND the good records
in the same file still imported. `test_normalizer.py` covers kind mapping, step ordering, latency math,
preview truncation. `test_store.py` covers round-trip and unlabeled-first ordering.
**Risk:** OTel GenAI semconv attribute names have shifted across versions -> map a tolerant alias set and
document it in `docs/importers.md`.

---

### PHASE 2 - Labeling UI + keyboard flow + session stats

**Objective:** the product. Run list -> timeline -> keystroke verdict -> auto-advance, with visible speed stats.

Acceptance criteria quoted from spec:
> F3 Labeling UI: run list (filters: source, has-error, duration, unlabeled-first) -> run detail:
> TraceTimeline (step cards, expandable payloads) -> verdict bar: R/W/P keys + failure tags (taxonomy:
> wrong_tool, bad_args, ungrounded, no_escalation, format_break, hallucinated_fact, other+note) ->
> **auto-advance to next unlabeled.** (spec 03 sec 4)

> Speed is the feature: **target <10s median per simple label; measure and show session stats.** (spec 03 sec 9)

- [x] `api/routes.py`: `POST /api/import`, `GET /api/runs?filters`, `GET /api/runs/{id}`,
      `POST /api/runs/{id}/label`, `GET /api/stats` (spec 03 sec 7), plus `GET /api/runs/next-unlabeled`,
      `DELETE /api/runs/{id}/label` (undo) and `GET /api/taxonomy` - see D-014
- [x] `api/app.py`: app factory + static SPA mount + dev CORS
- [x] `stats.py`: verdict/tag distribution, median seconds per label, CI-friendly text rendering
- [x] Frontend scaffold: vite + react + ts + tailwind with aurora tokens
- [x] `components/aurora/*`: Card, StatBadge, MetricTile, ConfidencePill, RiskTag, TraceTimeline,
      EmptyState, SyntheticDataBanner, VerdictBar (adaptation 1: built locally, spec 00 A2 tokens)
- [x] `ImportPage`: dropzone + per-file parse report
- [x] `RunsPage`: table with verdict pills, tag chips, unlabeled counter, all four filters
- [x] `LabelerPage`: TraceTimeline centre, VerdictBar bottom, keyboard legend, payload expanders
- [x] `useHotkeys`: R/W/P verdicts, 1-7 failure tags, J/K navigate, X expand, N note, Enter commit,
      S skip, U undo, ? legend
- [x] `useSessionStats`: per-label elapsed -> labels done + median seconds, displayed live
- [x] Auto-advance to next unlabeled after commit (`next_run_id` rides the label response)
- [x] Tests: 36 API endpoint tests; 13 component-level labeling flow tests (D-004); timed 20-run session
- [x] `t2e import` and `t2e label --serve` wired and verified against a live server
- [x] Commit: "Phase 2: labeling UI, keyboard flow, session stats"

**Test plan:** `test_api.py` exercises each endpoint incl. filter combinations. Frontend flow test
(Vitest + React Testing Library) simulates keypress -> verdict posted -> advanced to next unlabeled.
`test_labeling_session.py` scripts 20 label commits through the API and asserts median server-side
handling time leaves ample headroom under the 10s human budget (recorded in PROGRESS.md).
**Risk:** Playwright browser download is a network dependency that conflicts with the offline requirement
-> D-004 chooses component-level + API-level timing instead; noted honestly in README STATUS.

---

### PHASE 3 - Case builder + exports + pytest stub + CLI

**Objective:** labeled runs become versioned, portable eval cases and a runnable pytest file.

Acceptance criteria quoted from spec:
> F4 Case builder: from a labeled run, define {input, expected_behavior (assertions: must_call_tool X,
> must_escalate, must_cite, output_matches regex/schema), tags, version}. **Sensible defaults pre-filled
> from labels.** (spec 03 sec 4)

> F5 Exports: cases.jsonl (versioned, schema documented) + generated `test_cases.py` pytest stub
> (assertion helpers included) + optional Promptfoo-format export. (spec 03 sec 4)

> F6 CLI: `t2e import <file>`, `t2e label --serve` (launches UI), `t2e export --version v3`, `t2e stats`. (spec 03 sec 4)

> Over-building the assertion language -> **v1 = 5 assertion kinds max** (spec 03 sec 14)

- [ ] `assertions.py`: exactly 5 kinds - `must_call_tool`, `must_escalate`, `must_cite`,
      `output_matches_regex`, `output_matches_schema` - with evaluation logic + public helpers
- [ ] Defaults engine: derive pre-filled assertions from verdict + failure tags
      (e.g. `wrong_tool` -> `must_call_tool`, `no_escalation` -> `must_escalate`, `ungrounded` -> `must_cite`)
- [ ] `POST /api/cases` (from run | manual), `GET /api/cases?version`, `POST /api/export {version, format}`
- [ ] `CasesPage` expectation editor with assertion pickers; `ExportPage` version notes + format checkboxes
- [ ] `exporters/cases_jsonl.py` + `docs/cases_schema.md`
- [ ] `exporters/pytest_stub.py`: generated `test_cases.py` importing `t2e.assertions` helpers
- [ ] `exporters/promptfoo.py`
- [ ] `cli.py`: all four commands; `stats` prints CI-friendly output and a non-zero exit on empty dataset
- [ ] Golden files + tests; generated stub is executed by pytest to prove it runs
- [ ] Commit: "Phase 3: case builder, exports, pytest stub, CLI"

**Test plan:** `test_assertions.py` covers pass and fail for each of the 5 kinds.
`test_exports_golden.py` byte-compares all three export formats against `tests/golden/`.
`test_generated_pytest_stub.py` writes the stub to a tmp dir and runs pytest on it in-process.
`test_cli.py` asserts exit codes and stable stdout for `stats`.
**Risk:** golden files churn on any schema tweak -> schema version field in every case record; regenerate
goldens deliberately via a documented make target, never silently.

---

### PHASE 4 - Redaction + dogfood + README + docs

**Objective:** privacy pass done, the tool used on its own fixtures, findings written down honestly.

Acceptance criteria quoted from spec:
> local-first by design; no telemetry; **redaction helper (regex patterns) on import; warning banner when
> payloads look like PII.** (spec 03 sec 11)

> Dogfood requirement: Project 01's investigation traces labeled with this tool before launch;
> **findings in README** (spec 03 sec 10)

- [ ] `redaction.py`: default patterns (email, phone, credit-card-like, SSN-like, API keys, IBAN),
      config-extensible, applied at import; counts surfaced in the parse report
- [ ] PII-lookalike detector -> warning banner in `ImportPage` and CLI import output
- [ ] `test_redaction.py`: each pattern redacts; redaction is idempotent; no false-positive on ordinary text
- [ ] Confirm zero telemetry / zero network calls in the runtime path (grep audit, documented)
- [ ] **Dogfood:** import all fixtures, label them with the tool itself, build cases, export v1
- [ ] Record label distribution + median seconds per label -> README findings section
- [ ] Commit dogfood artifacts to `evals/cases.jsonl` + `evals/test_cases.py`; wire `make eval`
- [ ] README: one-line pitch, mermaid architecture, quickstart, HONEST POSITIONING, synthetic banner,
      STATUS from BLOCKERS.md, dogfood findings
- [ ] `docs/importers.md`, `docs/cases_schema.md`, `evals/README.md`
- [ ] `Makefile` + `make.ps1` (dev/test/eval/export/up/down); `.github/workflows/ci.yml`; `docker-compose.yml`
- [ ] Verify definition of done item by item
- [ ] `FINAL_REPORT.md`
- [ ] Commit: "Phase 4: redaction, dogfood, README, docs"

**Test plan:** full offline loop as a single scripted run - `t2e import` both formats -> label via API ->
build cases -> `t2e export --version v1` -> run the generated `evals/test_cases.py` -> `t2e stats`. Golden
tests and the whole suite green with no network access.
**Risk:** dogfooding on synthetic fixtures is weaker evidence than real traces -> state plainly in README
that fixtures are synthetic (B-001) and report the label-time measurement as self-measured, not audited.

---

## 4. EXTERNAL DEPENDENCIES

Near-zero by design - no LLM, no cloud, no vendor SDK. Everything below is a local package or already installed.

| Dependency | Purpose | Risk | Fallback |
|---|---|---|---|
| Python 3.12 + uv | runtime + packaging | none (verified 3.12.10 / uv 0.11.23) | `pip install -e .` |
| FastAPI + Uvicorn | local API server | none | - |
| Pydantic v2 / pydantic-settings | schemas + config | none | - |
| SQLAlchemy + SQLite | store (stdlib sqlite3 driver) | none | raw sqlite3 |
| pytest | tests + generated stub runtime | none | - |
| ruff | lint (spec 00 A1 CI) | none | skip lint in CI |
| Node 24 + npm + Vite/React/TS/Tailwind | labeling SPA | npm install needs network **once** | if npm install fails: log blocker, ship API + CLI, serve a minimal no-build HTML labeler as stub |
| Vitest + React Testing Library | frontend flow test | dev-only | backend-side scripted session test alone |
| **No LLM provider** | - | - | n/a, forbidden by adaptation 2 |
| **`make`** | `make dev` in definition of done | **absent locally (B-002)** | `make.ps1` mirrors every target; Makefile still shipped and CI-verified on Linux |
| **`./seed_traces/`** | dogfood input | **absent (B-001)** | hand-authored synthetic fixtures in both formats, clearly marked |
| Playwright | spec's CI labeling timing test | browser download = network, conflicts with offline goal | D-004: component + API-level timing instead |

Network is required exactly once (`npm install`, `uv sync`) and never at runtime.

---

## 5. DECISIONS LOG

Append-only. Every deviation from spec or judgment call, with one line of reasoning.

- **D-001** Ground-truth specs live at repo root, not `docs/` as the brief stated -> moved them into `docs/`
  so the brief's paths resolve; content untouched.
- **D-002** aurora-ui is built as local components in `frontend/src/components/aurora/` rather than a
  workspace package (build adaptation 1) -> this repo is standalone; a published package would be an
  unbuildable dependency.
- **D-003** Redaction module is created in Phase 1 as a wired pass-through and completed in Phase 4 ->
  keeps the brief's phase order while avoiding a rework of the import call path.
- **D-004** Labeler UX self-test uses Vitest + React Testing Library (component-level keyboard flow) plus
  an API-level timed 20-run session, instead of spec 03 sec 10's Playwright suite -> Playwright requires
  downloading browsers at test time, which contradicts the hard offline requirement; the timing claim is
  therefore reported as self-measured and the substitution is stated in README STATUS.
- **D-005** No `ledgerfab` and no LangChain/LangGraph despite spec 00 F's stack lock -> spec 03 sec 8 requires
  zero LLM usage in the MVP and this tool parses files rather than orchestrating agents; the stack lock's
  agent-orchestration clause has no surface area here. Build adaptation 2 makes this explicit.
- **D-006** SQLite DB defaults to `./.t2e/t2e.db` under the working directory -> local-first, per-project,
  no global state, trivially deletable.
- **D-007** Vite builds into `backend/src/t2e/web/` so `t2e label --serve` serves the SPA from the installed
  package with no separate dev server in the shipped path.
- **D-008** Generated `test_cases.py` imports helpers from `t2e.assertions` rather than inlining them ->
  one implementation tested once; the stub stays readable. A `--standalone` inline variant is noted as
  future work, not v1 scope.
- **D-009** Added three columns beyond spec 03 sec 6's list: `runs.started`, `runs.duration_ms`,
  `runs.has_error` -> F3 requires filtering the run list by source, has-error and duration, which is not
  answerable from the specced columns without parsing JSON text in SQL.
- **D-010** Added `labels.seconds_spent` -> spec 03 sec 9 requires a *measured* median seconds per label;
  without persisting the per-label elapsed time the stat could only ever be a guess.
- **D-011** Redaction was implemented in full in Phase 1 rather than stubbed and completed in Phase 4,
  amending D-003 -> it is ~150 lines and belongs *before* normalization so previews are derived from
  already-redacted payloads. A stub would have been rewritten, and a secret could have leaked into a
  preview in the meantime. Phase 4 still owns the PII banner in the UI, the dogfood and the README.
- **D-012** The import pipeline lives in `ingest.py`, not in `parsers/__init__.py` as the file map first
  had it -> keeps `t2e.parsers` a pure registry of format readers and gives the CLI and the API one
  shared definition of "import this file".
- **D-014** Added three endpoints beyond spec 03 sec 7: `GET /api/runs/next-unlabeled` (the labeler needs
  the next run's full detail to auto-advance), `DELETE /api/runs/{id}/label` (a fast keyboard flow will
  mislabel something, so undo is a correctness feature, not a nicety), and `GET /api/taxonomy` (so the UI
  never hard-codes a vocabulary that could drift from the server).
- **D-015** The label response carries `next_run_id` rather than making the client ask for it -> auto-
  advance must not cost a second round trip, because that latency lands directly in the <10s median claim.
- **D-016** `outcome.error` is populated only when the run's status is `error`; a run that recovered from
  a failing step stays `success` -> a record marked "success" while carrying an error string is incoherent
  to label against. The step keeps its own error, and `meta.n_step_errors` still surfaces it.
- **D-013** SQLite drops `tzinfo`, so datetime columns use a `UtcDateTime` type decorator that stores
  naive UTC and returns UTC-aware -> without it a run reloaded from disk compares unequal to the one
  written, which broke a round-trip test and would have corrupted exported timestamps.

---

## 6. DEFINITION OF DONE TRACKER

Checked off in Phase 4 against spec 00 sec E + spec 03.

- [ ] pipx/uv-installable CLI
- [ ] `t2e label --serve` launches the UI locally
- [ ] `make dev` works (+ `make.ps1` fallback, B-002)
- [ ] Both importers pass fixture snapshot tests incl. malformed-record handling
- [ ] Full offline loop: import -> label -> build cases -> export `cases.jsonl` + `test_cases.py`
- [ ] Golden-file tests pass
- [ ] Session stats visible (labels done, median seconds per label)
- [ ] Redaction helper works; PII-lookalike warning shows
- [ ] Dogfood completed; findings in README
- [ ] README: pitch, mermaid diagram, quickstart, HONEST POSITIONING, synthetic banner, STATUS
- [ ] PLAN.md fully ticked or unticked tasks marked BLOCKED with a reason
- [ ] FINAL_REPORT.md written
