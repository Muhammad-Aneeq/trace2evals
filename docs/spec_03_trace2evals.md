# SPEC 03 · TRACE2EVALS
### Track 1 · Framework-agnostic · 4 weeks · Python + FastAPI + Vite/React (labeling UI) + CLI
> **Prereq:** read `spec_00_shared_foundations.md` first (shared `ax-template`, `aurora-ui`, `ledgerfab`; NDA & cost rules; dependency graph).

## 1. Overview & Positioning
Best practice says every production agent failure should become a permanent eval case; the tooling for that conversion lives inside walled platforms (Langfuse/LangSmith/Braintrust in-product; Foundry's converter platform-locked). Trace2Evals is the standalone, cross-format, portable-output companion: import traces from anywhere, label them fast in a purpose-built UI, export framework-neutral eval cases you own. Honest positioning stated in README; the wedge is portability + the labeling UX.

## 2. Goals / Non-goals
GOALS: two importers done excellently (OTel JSON, LangSmith export JSONL); a labeling UI fast enough that 50 traces take <30 minutes; exports that run anywhere (JSONL + pytest stub); CLI for CI.
NON-GOALS (v1): live trace collection (file import only); auto-labeling (v2, human-confirmed); hosting a service; more than two formats.

## 3. Users & Stories
- AI engineer: "turn last week's failures into a regression suite in an afternoon, without platform lock-in."
- Team lead: "a labeled failure taxonomy tells me where the agent actually breaks."
Stories: US1 drag a trace export → normalized runs appear. US2 step through a run's timeline; label Right/Wrong/Partial + failure tags in keystrokes. US3 export v-tagged JSONL + generated pytest file. US4 `t2e stats` in CI prints label distribution + case counts.

## 4. Feature Specification
### MVP
F1 Importers: (a) OpenTelemetry JSON (GenAI semantic-convention aware: model calls, tool spans), (b) LangSmith run export JSONL. Strict-but-forgiving parsing with per-record error report.
F2 Normalized TraceRun model: {run_id, source, started, input, steps[ {kind: llm|tool|handoff, name, args_preview, output_preview, latency, error?} ], outcome, meta}.
F3 Labeling UI: run list (filters: source, has-error, duration, unlabeled-first) → run detail: TraceTimeline (step cards, expandable payloads) → verdict bar: R/W/P keys + failure tags (taxonomy: wrong_tool, bad_args, ungrounded, no_escalation, format_break, hallucinated_fact, other+note) → auto-advance to next unlabeled.
F4 Case builder: from a labeled run, define {input, expected_behavior (assertions: must_call_tool X, must_escalate, must_cite, output_matches regex/schema), tags, version}. Sensible defaults pre-filled from labels.
F5 Exports: cases.jsonl (versioned, schema documented) + generated `test_cases.py` pytest stub (assertion helpers included) + optional Promptfoo-format export.
F6 CLI: `t2e import <file>`, `t2e label --serve` (launches UI), `t2e export --version v3`, `t2e stats`.
### v2
Foundry trace importer; LLM label-suggestions (human confirms); near-duplicate failure clustering; direct FinAgent-Evals case format export.

## 5. System Architecture
```
[CLI] ──┐
        ├─ core lib (parsers → normalizer → store → exporters)
[SPA] ⇄ FastAPI (runs, labels, cases) ⇄ SQLite
```
Everything file-and-local-first; no external services required.

## 6. Data Model
- runs(id, source, imported_at, input_json, outcome_json, meta_json)
- steps(id, run_id FK, idx, kind, name, args_json, output_json, latency_ms, error)
- labels(run_id FK, verdict[right|wrong|partial], tags_json, note, labeled_at)
- cases(id, version, run_id FK NULL, input_json, expectations_json, tags_json, created_at)
- export_versions(version, created_at, case_count, notes)

## 7. API Surface
POST /api/import · GET /api/runs?filters · GET /api/runs/{id} · POST /api/runs/{id}/label · POST /api/cases (from run | manual) · GET /api/cases?version · POST /api/export {version, format}.

## 8. LLM Usage
None required in MVP (deliberately: the tool must run offline). v2 suggestion mode uses OpenAI mini-class with structured output; suggestions rendered as pre-ticked labels requiring confirmation; never auto-applied.

## 9. Frontend Spec (aurora-ui)
Screens: (1) Import (dropzone, per-file parse report) · (2) Runs table (verdict pills, tag chips, unlabeled counter) · (3) Run Detail / Labeler (TraceTimeline center; verdict bar bottom; keyboard legend; payload expanders) · (4) Cases (by version; expectation editor with assertion pickers) · (5) Export (version notes, format checkboxes, download).
Speed is the feature: target <10s median per simple label; measure and show session stats.

## 10. Evals & Testing
- Parser fixtures: 6 real-shaped sample files per format incl. malformed records; snapshot-tested normalization
- Export snapshot tests (JSONL + pytest stub golden files)
- Labeler UX self-test: scripted 20-run labeling session timed in CI (Playwright) < threshold
- Dogfood requirement: Project 01's investigation traces labeled with this tool before launch; findings in README

## 11. Security & Privacy
Traces may contain sensitive text in real use → local-first by design; no telemetry; redaction helper (regex patterns) on import; warning banner when payloads look like PII.

## 12. Deployment & Costs
pipx/uv install for CLI; `t2e label --serve` runs UI locally; docker-compose optional. LLM cost: $0 in MVP.

## 13. Milestones (4 weeks @10h)
W1 parsers + normalizer + store + fixtures
W2 Labeling UI + keyboard flow + stats
W3 Case builder + exports + pytest stub + CLI
W4 Dogfood on Project 01 traces, redaction pass, README, demo video ("50 failures → regression suite in 25 minutes")

## 14. Risks
- Platform features improve and shrink the wedge → keep positioning honest: portability + neutrality; ship Foundry importer v2 to widen it
- Format drift in exports → parser versioning + fixture updates as chore cadence
- Over-building the assertion language → v1 = 5 assertion kinds max

## 15. Launch Content Hooks
"Your production failures are your best test cases: here's the tool" · Timed labeling demo · Failure-taxonomy post (share Project 01's real distribution) · "Own your evals: portability as a principle."
