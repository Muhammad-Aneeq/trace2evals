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
