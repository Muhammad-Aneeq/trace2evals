# FINAL_REPORT.md — Trace2Evals (`t2e`)

Written at the end of the build. What is actually complete and demoable, the exact commands to run it,
what is still blocked, and the three things I would build next.

---

## 1. What is complete and demoable

The full product loop works offline, end to end: **import → label → build cases → export**.

| Spec item | State | Evidence |
|---|---|---|
| **F1** Two importers, strict-but-forgiving, per-record error report | Complete | 12 fixtures snapshot-tested; malformed files import their good records and report every bad one with a locator |
| **F2** Normalized `TraceRun` model | Complete | Field contract asserted via `spec_dump()`, independently of storage extras |
| **F3** Labeling UI: filters → timeline → R/W/P + tags → auto-advance | Complete | 36 API tests, 13 component tests driving real keystrokes, timed 20-run session |
| **F4** Case builder with label-derived defaults | Complete | 21 tests over the tag → assertion mapping |
| **F5** Exports: `cases.jsonl` + pytest stub + Promptfoo | Complete | Golden files for all three, **plus the generated suite proven to run** |
| **F6** CLI: `import` / `label --serve` / `export --version` / `stats` | Complete | 22 CLI tests incl. exit codes |
| **sec 11** Local-first, zero telemetry, redaction, PII banner | Complete | 22 redaction tests; grep audit found one `fetch`, same-origin only |
| **sec 10** Dogfood before launch | Done on synthetic fixtures | `scripts/dogfood.py`, findings in README |

**Numbers:** 305 backend tests, 13 frontend component tests, ruff clean, `tsc --strict` clean
(with `noUncheckedIndexedAccess`), 17-passing/17-skipping evals gate. Zero runtime dependencies beyond
FastAPI/SQLAlchemy/Pydantic — **no LLM, no cloud, no vendor SDK**.

**Five real bugs were found by the tests and fixed**, each documented in PROGRESS.md: SQLite silently
dropping `tzinfo`; a stale relationship cache making re-imported steps invisible; infrastructure-only
traces importing as empty unlabelable runs; over-eager preview unwrapping that hid tool-arg keys; and
pytest collecting the golden `test_cases.py` artefact and erroring on 6 tests (which would have broken
`make test` on a fresh clone).

---

## 2. Exact run commands

From the repository root. Only step 1 needs network.

```bash
# 1. install
uv sync --extra dev
npm --prefix frontend install
#    or: make install   |   Windows: ./make.ps1 install

# 2. import the bundled synthetic traces (both formats)
uv run t2e import fixtures/otel fixtures/langsmith
#    -> 16 runs from 12 files; 10 record errors; 5 redactions
#    -> WARNING: payloads looked like PII (credit_card, email, iban, phone)

# 3. build the UI, then label
npm --prefix frontend run build
uv run t2e label --serve
#    -> http://127.0.0.1:8765   (R/W/P, 1-7 for tags, Enter to commit and advance, ? for help)

# 4. export a suite you own
uv run t2e export --version v1 --format jsonl,pytest,promptfoo --out exports

# 5. CI summary
uv run t2e stats
```

### Reproduce the dogfood and the eval gate

```bash
uv run python scripts/dogfood.py      # import + label 16 runs + build cases + export into evals/
uv run pytest evals/                  # 17 passed, 17 skipped (no agent in this repo)
```

### Everything green

```bash
make test        # ruff + pytest + tsc + vitest
./make.ps1 test  # same, on Windows
```

### Verified working in this environment

- `uv sync --extra dev`, `uv run pytest` (305 passed), `uv run ruff check .` (clean)
- `npm run typecheck`, `npm test` (13 passed), `npm run build`
- `uv run t2e --help | import | label --serve | export | stats`, with exit codes checked
- `./make.ps1 help | eval`
- A **live server**: `/api/health` → `ui_built: true`; `/`, `/runs`, `/label`, `/label/<id>`, `/import`
  all serve the SPA shell; a label posted over real HTTP advanced the queue and moved the median stat;
  the PII fixture serves `[REDACTED:email]` with no raw address

### Not verified in this environment

- `make dev` / `make test` via GNU `make` — absent locally (**B-002**), verified on Linux CI instead
- The UI in a real browser (**B-003**) — no screenshot ships for this reason
- `docker compose up` — Docker was not available; the `Dockerfile` and compose file are unexercised

---

## 3. Remaining blockers, with the one-line fix for each

| # | Blocker | One-line fix |
|---|---|---|
| **B-001** | No real traces at `./seed_traces/`; fixtures are synthetic | Drop real OTel/LangSmith exports into `seed_traces/` and run `uv run t2e import seed_traces/` — the importers are format-driven, so no code changes. |
| **B-002** | `make` absent locally; `Makefile` verified on CI only | `winget install GnuWin32.Make` (or run under WSL), then `make test`. |
| **B-003** | No browser; UI unverified visually, no screenshot | Run `make serve`, open `http://127.0.0.1:8765`, label a few runs, and capture a screenshot for the README. |
| **B-004** | `<10s median per label` untested against a human | One person, `make serve`, 16 traces, then `uv run t2e stats` — a ten-minute exercise that settles the claim. |
| — | `docker compose` unexercised | Run `make up` on a machine with Docker and fix whatever surfaces. |

All four blockers are **environmental, not architectural**: each is resolved by supplying something the
build environment lacked, not by changing the design. Nothing is blocked on a decision.

Every PLAN.md task is ticked. The two Phase 4 items that could not be completed honestly — a human-timed
labeling session and a real-trace dogfood — are marked with pointers to B-004 and B-001 rather than
being quietly checked off.

---

## 4. The three things I would build next

### 1. A real-trace dogfood, and let it break the importers

This is the highest-value next step by a distance, and it is a *validation* task, not a feature. The
fixtures are hand-authored, which means they are honest about the formats **as I understand them** — and
that is exactly the assumption most likely to be wrong. Real exports carry things I did not invent:
truncated payloads, unicode edge cases, 400-step runs, provider-specific attribute spellings, spans with
clock skew. I would import a week of production traces, expect the parse report to be ugly, and turn
every genuine miss into a fixture plus an alias-table entry. Concretely: it would also let B-004 be
answered properly — 50 real traces, one human, one timed session, and the headline claim is either true
or it is not.

### 2. Near-duplicate failure clustering

The dogfood already showed the need. `ungrounded` appeared in 4 of 6 flagged runs and those runs are
*variations of one problem*: the agent asserting a conclusion without citing evidence. Labeling all four
separately is wasted human effort, and exporting four near-identical cases inflates a suite without
adding coverage. I would cluster on a cheap structural signature — tool-call sequence, verdict, tag set,
plus a shingled hash of the output — and offer "3 similar unlabeled runs: apply this label to all?" in
the labeler, with one case exported per cluster and the members recorded as `variants`. This is the
single change that would most improve the labels-per-hour number, and it needs no LLM.

### 3. A trace-diff view for regression triage

The current tool answers "was this run right?". The question a team actually asks next is "what changed
between the run that worked last week and the one that broke today?". Since runs are already normalized
into one step model, a side-by-side diff of two runs — aligned on tool-call sequence, highlighting a
diverging step, a new error, or a dropped citation — is mostly a UI problem over data that already
exists. It would also make the exported suite self-explaining: a case could carry a pointer to the
passing run it was derived from, so a failure shows the delta rather than just a red assertion.

**Deliberately not next:** LLM label suggestions. It is the flashiest v2 item and the spec allows it
(human-confirmed), but it trades away the property that makes this tool defensible — that it runs fully
offline with no model dependency and no inference cost. I would only add it behind a flag, after
clustering, and never as a default.

---

## 5. Honest summary

The tool does what the spec asked, offline, with tests that verify behaviour rather than restating the
implementation — including a test that runs the generated pytest suite to prove the export is real
rather than merely well-formatted text.

Two claims are weaker than they would first appear, and both are stated in the README rather than buried
here: the dogfood ran on **synthetic** traces, and the **<10s median is a design target**, with the
tool's own sub-half-second contribution measured but the human side never timed. `meets_speed_target`
returns `null` rather than `true` until something is actually measured — an unmeasured claim reporting as
a passing one is precisely the failure mode this tool exists to prevent, and it would have been
hypocritical to ship it any other way.
