# BLOCKERS.md

Every blocker encountered, with what was tried, what is needed to truly resolve it, and the workaround
shipped so downstream work continued. Nothing here silently stopped work.

---

## B-001 - No real dogfood traces at `./seed_traces/`

- **What:** The build brief says real trace exports "may be provided at `./seed_traces/`" and that if
  present they are the primary test fixtures and the dogfood target. The directory does not exist; the
  repository contained only the three spec markdown files at Phase 0.
- **Tried:** Recursive listing of the working directory (depth 2) at Phase 0 - only
  `spec_00_shared_foundations.md`, `spec_03_trace2evals.md`, `ten_projects_technical_plans.md` present.
  No archive, no hidden directory, no trace export of any kind.
- **Needed to resolve:** Real OpenTelemetry JSON and/or LangSmith JSONL exports dropped into
  `./seed_traces/` - ideally the Project 01 investigation traces spec 03 sec 10 names as the dogfood source.
- **Workaround shipped:** Hand-authored synthetic fixtures in both formats under `fixtures/otel/` and
  `fixtures/langsmith/` (6 per format, including malformed records per spec 03 sec 10), written to match the
  real wire shapes. Provenance is recorded in `fixtures/README.md`, every UI screen carries the
  `SyntheticDataBanner`, and the README states plainly that the dogfood numbers were measured on synthetic
  fixtures rather than production traces. Importers are format-driven, not fixture-driven, so real exports
  can be dropped in later with no code change.
- **Affected PLAN.md tasks:** Phase 1 fixtures, Phase 4 dogfood - implemented against synthetic data,
  not blocked.
- **Impact on claims:** The label-time and label-distribution findings in the README are self-measured on
  synthetic traces. That is weaker evidence than production traces and is labelled as such.

---

## B-004 - The "<10s median per label" claim is not verified by a human session

- **What:** Spec 03 sec 9 makes speed the product claim: "target <10s median per simple label; measure
  and show session stats." The measuring machinery is built, tested and displayed, but the target itself
  has never been tested against a human labeling session.
- **Tried:** The dogfood run (`scripts/dogfood.py`) labels all 16 fixture runs with considered
  judgements, so the *distribution* is real. It records `seconds_spent=None`, because the alternative
  was to invent per-label durations. There is no human on this machine to time, and no browser to run
  an interactive session in (**B-003**), so the keystroke-to-keystroke timing a real labeler would
  produce simply does not exist here.
- **Needed to resolve:** One person, the built UI, and 16 traces: `make serve`, label them, then read
  `t2e stats`. That is a ten-minute exercise for anyone with the repo, and it would settle the claim.
- **Workaround shipped:** The two things that *can* be measured honestly, both reported separately:
  1. **The tool's own contribution**: the median label round trip through the API is under 0.5s,
     asserted in `tests/test_labeling_session.py`. So the tool adds well under 1s to each label; the
     remaining ~9s of the budget is entirely human reading and deciding.
  2. **The measurement path end to end**: labels submitted *with* a `seconds_spent` value produce a
     correct median in `t2e stats`, `GET /api/stats` and the labeler's live panel - verified in the API
     tests, the component tests, and a live HTTP run that moved the median to 5.5s.
  `meets_speed_target` returns **null**, not `true`, when nothing has been timed. An unmeasured claim
  must never report as a passing one, and there is a test for exactly that.
- **Affected PLAN.md tasks:** Phase 4 "Record label distribution + median seconds per label" -
  distribution recorded, human median **not** recorded.
- **Impact on claims:** The README states the label distribution as a finding and states plainly that
  the <10s median is a design target with the tool-side latency measured and the human side untested.

---

## B-003 - No browser available to verify the UI interactively

- **What:** After building the SPA and serving it with `t2e label --serve`, I tried to drive the real UI
  in Chrome to confirm the keyboard flow behaves outside jsdom. The browser automation extension
  reported "Browser extension is not connected", so no interactive click/keypress verification against a
  real rendering engine was possible.
- **Tried:** `tabs_context_mcp{createIfEmpty: true}` - returned the not-connected error. Playwright was
  already ruled out for a different reason (D-004: it downloads browsers at test time, which conflicts
  with the offline requirement), so there was no second automation path available.
- **Needed to resolve:** A connected Chrome extension session, or a one-off `npx playwright install
  chromium` on a machine where the network cost is acceptable, then a short scripted session.
- **Workaround shipped:** Three layers of verification that do not need a browser:
  1. **13 component tests** (Vitest + React Testing Library, jsdom) drive the real `LabelerPage`
     component through keystrokes: `W`/`1`/`2`/`Enter` produces the correct request body, committing
     auto-advances to the next run, `X` expands a payload, `J`/`K` moves the cursor, typing in the note
     field does not fire verdicts, and commit is refused without a verdict.
  2. **36 API tests** plus a scripted 20-run session test cover every endpoint and the queue mechanics.
  3. **Live HTTP checks** against a running `t2e label --serve`: `/`, `/runs`, `/label`, `/label/<id>` and
     `/import` all return the SPA shell (so client-side deep links work), both built assets are served,
     the JS bundle contains the expected UI strings, and a label posted over real HTTP advanced the queue
     and moved the median stat.
- **Affected PLAN.md tasks:** none blocked - the Phase 2 UI tasks are delivered and tested.
- **Impact on claims:** The UI is verified by component tests and live HTTP, **not** by a human or a
  script clicking through a real browser. No screenshot is included in the README for the same reason.
  Visual rendering (Tailwind output, the frosted-glass look, layout at real viewport sizes) is therefore
  unverified. Stated in the README STATUS section.

---

## B-002 - `make` is not installed on the build machine

- **What:** Spec 00 A1 and the definition of done require a `Makefile` and a working `make dev`.
  `Get-Command make` returns nothing on this Windows 11 host (no GNU Make, no chocolatey/scoop shim).
- **Tried:** Probed `make` alongside python/uv/node/npm/git/pipx at Phase 0. `make` and `pipx` are both
  absent; everything else is present (python 3.12.10, uv 0.11.23, node 24.14.1, npm 11.11.0, git 2.53.0).
- **Needed to resolve:** Install GNU Make (`winget install GnuWin32.Make`, or run under WSL / a Linux CI
  runner where `make` is standard).
- **Workaround shipped:** The `Makefile` is written and committed with all required targets
  (`dev`, `test`, `eval`, `export`, `up`, `down`) so it works unchanged wherever `make` exists - including
  the GitHub Actions Linux runner, which is where CI verifies it. A `make.ps1` script mirrors every target
  one-for-one so the same commands are runnable on this Windows host. Both are documented in the README
  quickstart.
- **Affected PLAN.md tasks:** Phase 4 Makefile task - delivered, with the local verification done through
  `make.ps1` instead of `make`.
- **Impact on claims:** `make dev` is verified on Linux CI only; locally the equivalent verified path is
  `./make.ps1 dev`. Stated honestly in the README STATUS section.
