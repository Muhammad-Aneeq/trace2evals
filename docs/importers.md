# Importers

Trace2Evals ships **exactly two** importers in v1, and that is a deliberate product decision, not a
staging post: spec 03 sec 2 lists "more than two formats" as an explicit non-goal. Two formats done
excellently beats six done adequately, because a half-right importer silently produces wrong eval cases.

Both funnel into one normalized model, so an OTel run and a LangSmith run are labeled through exactly
the same UI and export to exactly the same case format.

```
file ──▶ parser (per-format) ──▶ RawRun ──▶ redaction ──▶ normalizer ──▶ TraceRun ──▶ SQLite
                    │                                          │
                    └── ParseReport (per-record errors) ────────┘
```

## The normalized model

Fixed by spec 03 F2 and verified by `TraceRun.spec_dump()` in the snapshot tests:

```json
{
  "run_id": "4f2a9c1e8b7d6a5f3e2d1c0b9a8f7e6d",
  "source": "otel",
  "started": "2026-08-14T09:15:00+00:00",
  "input": "Bank transaction BNK-20260814-0042 ... Investigate and propose a root cause.",
  "steps": [
    {
      "kind": "llm",
      "name": "gpt-4o-mini",
      "args_preview": "system: You are a reconciliation analyst...",
      "output_preview": "assistant: I need the open invoices...",
      "latency": 1620.0,
      "error": null
    }
  ],
  "outcome": { "status": "success", "output": "Root cause: partial payment...", "error": null },
  "meta": { "trace_id": "...", "service": "exception-workbench", "n_steps": 4, "n_llm": 2 }
}
```

- `kind` is one of `llm`, `tool`, `handoff`. Nothing else is representable, on purpose.
- `latency` is **milliseconds**, or `null` when the source gave no usable timestamps.
- `*_preview` fields are truncated to 500 characters for the step cards. The **full** payloads are kept
  in `steps.args_json` / `steps.output_json` and served to the UI expanders and to assertions.
- `error` is omitted from `spec_dump()` when absent, since F2 marks it optional.

### Outcome precedence

`outcome.status` is derived in a fixed order, so the same trace always normalizes the same way:

1. an explicit status from the source wins
2. a run-level error means `error`
3. a failing step with **no** run output means `error`
4. any run output means `success`
5. otherwise `unknown`

`outcome.error` explains why the *run* failed, so it is populated only when the status is `error`. A run
that produced an answer despite a failed step stays `success` — the step keeps its own `error`, and
`meta.n_step_errors` plus the has-error filter still surface it. Without that rule you get runs marked
"success" carrying an error string, which is incoherent to label against.

## Strict-but-forgiving parsing

Required by spec 03 F1. The contract, which the fixture tests enforce:

- **No parser raises on bad trace data.** Unreadable files, invalid JSON, wrong types and missing fields
  all become entries in the `ParseReport`.
- **A bad record never aborts the file.** Every other record in the same file still imports.
- **Every error names its location.** `line 7` for JSONL, `resourceSpans[0].scopeSpans[1].spans[2]` for
  OTLP, `run <uuid>` for a LangSmith record, `<document>` / `<file>` for whole-file problems.
- **Errors carry a JSON excerpt** (clipped to 200 chars) so the problem is diagnosable without reopening
  the file.

`ParseReport` fields: `file`, `format`, `records_seen`, `runs_imported`, `steps_imported`, `errors[]`,
`warnings[]`, `redactions`, `pii_flags[]`.

## Format detection

`t2e import` sniffs by content and uses the extension only to break a tie, because a mislabelled
extension is more common than a mislabelled payload. Weighted markers: `resourceSpans`, `scopeSpans`,
`spanId`, `startTimeUnixNano` for OTel; `run_type`, `dotted_order`, `parent_run_id`, `child_run_ids` for
LangSmith. Override with `--format otel` or `--format langsmith`. Forcing the wrong parser fails loudly
in the report rather than importing nonsense.

---

## (a) OpenTelemetry JSON

Accepted shapes:

| Shape | Notes |
|---|---|
| `{"resourceSpans": [{"resource": ..., "scopeSpans": [{"spans": [...]}]}]}` | Canonical OTLP/JSON export |
| `{"spans": [...]}` | Flattened, as several collectors and debug dumps emit |
| `[...]` | A bare array of spans, or of `resourceSpans` entries |

Also tolerated: `instrumentationLibrarySpans` (the pre-1.0 name), snake_case keys
(`start_time_unix_nano`), attributes as a plain object instead of an OTLP key/value list, and epoch
timestamps in nanoseconds, microseconds, milliseconds or seconds (including as JSON strings, which OTLP
uses for int64).

`AnyValue` unwrapping covers `stringValue`, `intValue`, `doubleValue`, `boolValue`, `bytesValue`
(base64-decoded), `arrayValue` and `kvlistValue`. Attribute values that are JSON-encoded strings are
parsed back into structure, since the GenAI conventions carry prompts as flat strings.

### GenAI attribute aliases

The GenAI semantic conventions have been renamed more than once, so each concept resolves against an
ordered alias set — first match wins:

| Concept | Aliases tried, in order |
|---|---|
| operation | `gen_ai.operation.name`, `gen_ai.operation`, `operation.name` |
| model | `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.model`, `llm.model_name`, `llm.request.model` |
| prompt | `gen_ai.prompt`, `gen_ai.input.messages`, `gen_ai.request.messages`, `llm.prompts`, `llm.input_messages`, `input.value` |
| completion | `gen_ai.completion`, `gen_ai.output.messages`, `gen_ai.response.text`, `gen_ai.response.messages`, `llm.completions`, `llm.output_messages`, `output.value` |
| tool name | `gen_ai.tool.name`, `tool.name`, `gen_ai.tool.call.name` |
| tool args | `gen_ai.tool.call.arguments`, `gen_ai.tool.arguments`, `gen_ai.tool.input`, `tool.arguments`, `tool.input`, `input.value` |
| tool result | `gen_ai.tool.call.result`, `gen_ai.tool.output`, `gen_ai.tool.result`, `tool.result`, `tool.output`, `output.value` |
| agent | `gen_ai.agent.name`, `agent.name`, `gen_ai.agent.id` |
| tokens | `gen_ai.usage.input_tokens` / `prompt_tokens`, `gen_ai.usage.output_tokens` / `completion_tokens` |

Newer semconv moves message content into **span events**; `gen_ai.user.message`,
`gen_ai.system.message`, `gen_ai.assistant.message` and `gen_ai.choice` are read as a fallback when the
attribute form is absent.

### Span classification

Checked in this order, first match wins:

1. **tool** — operation in {`execute_tool`, `execute_tool_call`, `tool`, `tool_call`}, or a tool-name
   attribute is present, or the span name starts with `execute_tool` / `tool.` / `tool `
2. **handoff** — operation in {`invoke_agent`, `create_agent`, `handoff`, `transfer_to_agent`}, or
   `handoff` / `transfer_to` appears in the span name. **Exception:** the outermost `invoke_agent` span
   *is the run*, so it becomes the container, not a step. A nested one is a real delegation.
3. **llm** — operation in {`chat`, `text_completion`, `completion`, `generate_content`, `embeddings`,
   `generate`}, or a model / prompt / completion attribute is present
4. **not a step** — anything else (HTTP, DB, framework plumbing) is dropped

Spans are grouped into runs by `traceId`, falling back to `spanId`, then to a
`<filename>-<index>` synthetic id. The root is the span whose `parentSpanId` is absent from the group.
A trace containing no GenAI spans at all is reported as an error rather than imported as an empty run —
there would be nothing in it to label.

Errors come from `status.code == 2` (accepted as `2`, `"2"`, `"STATUS_CODE_ERROR"`, `"ERROR"`), from
`status.message`, and from `exception` events. The exception event wins when present because
`exception.message` is almost always more specific than `status.message`.

---

## (b) LangSmith run export JSONL

One JSON run record per line. A whole-file JSON array is also accepted, since exports are sometimes
wrapped. Blank lines and `//` comment lines are skipped without complaint.

### Run-type mapping

| `run_type` | Becomes |
|---|---|
| `llm`, `chat_model`, `embedding` | `llm` step |
| `tool`, `retriever` | `tool` step |
| `chain`, `agent` — **nested** | `handoff` step |
| `chain`, `agent` — **at the root** | the run container itself, not a step |
| `prompt`, `parser` | skipped as formatting noise; counted in `meta.skipped_records` |
| anything else | reported as an error, that record skipped, run still imported |

A root `chain` supplies the run's `input`, `outcome` and `started`. A root `llm` or `tool` — a
single-call run — is both the container *and* a step, which is the honest reading of that shape.

### Grouping and ordering

Records group by `trace_id`. Exports predating that field fall back to walking `parent_run_id` up to a
root (cycle-guarded), then to a `<filename>-<index>` synthetic id.

Step ordering prefers `dotted_order`, because it is the export's own canonical sequence and disambiguates
records whose timestamps coincide — which happens constantly in concurrent tool fan-out. Timestamps are
the fallback, then original file order.

### Payload extraction

`inputs` and `outputs` are taken whole as the step's args and output. For previews, the renderer unwraps
the shapes LangChain actually emits: `{"messages": [{"role", "content"}]}` becomes `role: content` lines,
multi-part content blocks keep only their text parts, and `LLMResult.generations` (which nests one list
per prompt) is flattened to its text. A lone wrapper key such as `{"output": ...}` is unwrapped, but a
meaningful key is kept — `{"invoice_id": "INV-1"}` reads far better than a bare `INV-1`.

Errors are read from the record's `error` field at both run and step level.

---

## Adding a real trace export

Drop files into `seed_traces/` and run `t2e import seed_traces/`. Directories are expanded recursively
over `.json`, `.jsonl` and `.ndjson`, sorted for determinism, and de-duplicated. Re-importing the same
trace id updates that run in place rather than creating a duplicate, so imports are idempotent.

If a real export exposes a shape these parsers mishandle, the fix belongs in the alias tables above plus
a new fixture in `fixtures/`, never in a special case at the call site.
