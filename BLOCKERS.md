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
