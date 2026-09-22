# Trace2Evals — Overview

A short orientation doc. Deep detail lives in [README.md](README.md), [PLAN.md](PLAN.md) and
[BLOCKERS.md](BLOCKERS.md).

---

## What it is

A local-first tool (`t2e`) that turns **agent traces you already have** into an **eval suite you own**.

Import traces → label them fast by keyboard → export `cases.jsonl` plus a runnable pytest file.

## The problem it solves

When an AI agent misbehaves in production, the trace already contains everything needed to write a
regression test: the input, the tool calls, the arguments, the final answer. Most teams read it once,
fix the bug, and throw the trace away. The same failure comes back later with nothing guarding it.

**Purpose: make "production failure → permanent test case" a three-keystroke operation** instead of a
half-hour of manual test authoring.

## What it does

| Step | What happens |
|---|---|
| **Import** | Reads OpenTelemetry JSON (GenAI semconv) or LangSmith run-export JSONL. Malformed records are *reported*, not silently dropped. |
| **Redact** | Emails, phones, SSNs, IBANs, API keys and bearer tokens are replaced on import, before anything reaches a screen. Card numbers are Luhn-checked so real reference numbers survive. |
| **Label** | A keyboard-first UI: verdict (right/wrong/partial) + failure tag + commit, then it auto-advances to the next unlabeled run. |
| **Build cases** | Each labeled run becomes a versioned eval case. Assertions are **derived from the tags you pressed** — no hand-authoring. |
| **Export** | `cases.jsonl`, a generated `test_cases.py`, and optionally `promptfooconfig.yaml`. |

**Failure taxonomy** (closed set in v1): `wrong_tool`, `bad_args`, `ungrounded`, `no_escalation`,
`format_break`, `hallucinated_fact`, `other`.

**Tag → assertion mapping**, e.g. `ungrounded` → `must_cite`, `no_escalation` → `must_escalate`,
`wrong_tool` → `must_call_tool`.

## How it works

```
trace files  →  parsers  →  redaction  →  normalizer  →  SQLite (./.t2e/t2e.db)
                                                            ↓
                                              FastAPI  ←→  React SPA (labeler)
                                                            ↓
                                     cases.jsonl · test_cases.py · promptfooconfig.yaml
```

- **`backend/src/t2e/`** — pure Python core: `parsers/`, `redaction.py`, `normalizer.py`, `store.py`,
  `casebuilder.py`, `assertions.py`, `exporters/`, `api/`, `cli.py`. No vendor SDKs.
- **`frontend/src/`** — React + Tailwind SPA; builds into the Python package so one process serves
  both API and UI.
- **Everything is local.** SQLite in your working directory, zero telemetry, **no LLM calls at all**.
  The only network access in the repo is `uv sync` and `npm install`.

## Design constraints worth knowing

- **No LLM calls by design** — the tool runs offline, on a plane.
- **Portable output** — plain JSONL + plain pytest. Stop using `t2e` and your suite still runs.
- **Honest metrics** — `meets_speed_target` returns `null`, never `true`, until something is actually
  timed. Unmeasured claims are not allowed to report as passing ones.
- **All bundled fixtures are synthetic.** Every screen carries a synthetic-data banner.

---

## How to run it

`make` is absent on Windows — use `./make.ps1 <target>`, which mirrors every Makefile target.

```bash
./make.ps1 install     # uv sync --extra dev + npm install   (only step needing network)
./make.ps1 build       # build the SPA into the Python package
```

```bash
uv run t2e import fixtures/otel fixtures/langsmith
#  -> 16 runs from 12 files; 10 record errors; 5 redactions

uv run t2e label --serve          # http://127.0.0.1:8765
uv run t2e export --version v1 --format jsonl,pytest,promptfoo --out exports
uv run t2e stats
```

### Keyboard flow

| Key | Action |
|---|---|
| `R` `W` `P` | verdict: right / wrong / partial |
| `1`–`7` | toggle a failure tag |
| `J` `K` | move step cursor · `X` expand payload |
| `N` | focus note · `Enter` commit + auto-advance |
| `S` `U` `?` | skip / undo / help |

## How to test

```bash
./make.ps1 test          # ruff + pytest + tsc --strict + vitest
./make.ps1 eval          # evals/ suite-integrity gate
./make.ps1 dogfood       # re-run the full labeling loop end to end
```

Or individually:

```bash
uv run ruff check .                     # lint
uv run pytest                           # backend
npm --prefix frontend run typecheck     # tsc --strict
npm --prefix frontend run test          # component tests
uv run python scripts/check_evals_current.py   # committed evals still match dogfood output
```

**Verified state (2026-09-21):** 305 backend tests pass, 13 component tests pass, ruff and
`tsc --strict` clean, evals gate green. The full import → label → build → export loop was driven
against a live server in a real browser: the UI renders with zero JS errors and the keyboard flow,
auto-advance and live session timing all work.

## Known limits

File import only (no live trace collection), two input formats, no auto-labeling, no clustering, no
auth, no hosted collaboration. Those are explicit v2 items, not bugs — see
[BLOCKERS.md](BLOCKERS.md) and the HONEST POSITIONING section of the README.
