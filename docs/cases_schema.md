# `cases.jsonl` schema

The export format is the product. Everything else in this tool is machinery for producing this file, so
it is specified rather than left implicit (spec 03 F5: "cases.jsonl (versioned, schema documented)").

**Current `schema_version`: `1`**

One JSON object per line, UTF-8, LF newlines, keys sorted, trailing newline. Sorted keys and LF are what
make the golden-file tests meaningful and keep diffs readable.

## Record

```json
{
  "schema_version": 1,
  "case_id": "v1-0001",
  "version": "v1",
  "run_id": "4f2a9c1e8b7d6a5f3e2d1c0b9a8f7e6d",
  "input": "Bank transaction BNK-20260814-0042 for 4,812.50 GBP has no matching GL entry...",
  "expectations": [
    { "kind": "must_call_tool", "tool": "get_invoice", "note": "tagged wrong_tool" },
    { "kind": "must_cite", "min_count": 1, "note": "tagged ungrounded" }
  ],
  "tags": ["wrong_tool", "ungrounded", "source:otel"],
  "created_at": "2026-08-20T14:30:00+00:00"
}
```

| Field | Type | Notes |
|---|---|---|
| `schema_version` | integer | Pinned by `t2e.CASE_SCHEMA_VERSION`. Bumped only on a breaking change. A reader that does not recognise it should refuse the file, not guess. |
| `case_id` | string | `<version>-<4-digit id>`, stable within a version. This is what a failing test names. |
| `version` | string | The suite version, e.g. `v1`. Free-form; `vN` is the convention. |
| `run_id` | string or **null** | The trace this case came from. `null` for a hand-written case. |
| `input` | string | What the agent is given. Normalized from the trace's input. |
| `expectations` | array | Zero or more assertion records (below). Zero means the case asserts nothing — the generated suite has a test that fails on this. |
| `tags` | array of string | Failure tags plus provenance (`source:otel`, `had_error`, `multi_agent`, `manual`), for slicing a suite later. |
| `created_at` | ISO-8601 string or null | UTC. |

## Assertion records

Exactly **five** kinds exist in v1, and that cap is deliberate (spec 03 sec 14 names over-building the
assertion language as a risk). Every kind accepts an optional `note` explaining why the assertion is
there — usually which failure tag produced it.

### `must_call_tool`

```json
{ "kind": "must_call_tool", "tool": "get_invoice", "allow_any": false }
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `tool` | string | required | Tool name. With `allow_any`, a comma-separated list. |
| `allow_any` | boolean | `false` | When true, any one of the listed tools satisfies the assertion. |

### `must_escalate`

```json
{ "kind": "must_escalate", "tools": ["flag_exception"], "keywords": ["escalate"] }
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `tools` | array | a built-in list | Tool names that count as escalation. |
| `keywords` | array | a built-in list | Output phrases that count, as a last resort. |

Signal precedence: an explicit `escalated` flag from your adapter wins, then an escalation tool call,
then output keywords. Text matching is the weakest evidence, so it is checked last.

### `must_cite`

```json
{ "kind": "must_cite", "min_count": 1 }
{ "kind": "must_cite", "sources": ["INV-2026-0881", "GL-88213"] }
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `sources` | array | — | Every id listed must appear. Use for a specific hallucination. |
| `min_count` | integer | `1` | Used when `sources` is absent: at least this many citation-shaped ids. |

Citations come from your adapter's `citations` list if it provides one; otherwise ids matching
`\b[A-Z]{2,6}-[A-Z0-9]{2,}(?:-[A-Z0-9]+)*\b` are extracted from the output.

### `output_matches_regex`

```json
{ "kind": "output_matches_regex", "pattern": "\\bSCHED-1188\\b", "flags": "i" }
```

| Param | Type | Default | Notes |
|---|---|---|---|
| `pattern` | string | required | Python regex. `re.search`, not `fullmatch`. |
| `flags` | string | `""` | Any of `i` (ignorecase), `m` (multiline), `s` (dotall). |

An invalid pattern **fails** the assertion rather than passing it — an authoring mistake must never be
indistinguishable from a green check.

### `output_matches_schema`

```json
{
  "kind": "output_matches_schema",
  "schema": {
    "type": "object",
    "required": ["root_cause", "evidence"],
    "properties": {
      "root_cause": { "type": "string", "enum": ["partial_payment", "duplicate", "fx"] },
      "evidence": { "type": "array", "minItems": 1, "items": { "type": "string" } }
    }
  }
}
```

The output must parse as JSON (a fenced ```` ```json ```` block is tolerated, because models emit them
constantly) and satisfy the schema.

**Supported JSON Schema subset**, implemented in-tree so the tool keeps its zero-runtime-dependency
promise: `type`, `required`, `properties`, `items`, `enum`, `minimum`, `maximum`, `minItems`,
`minLength`. Nested objects and arrays validate recursively, and failures report a path
(`$.evidence[0]`).

Any **unsupported keyword fails the assertion with an explicit message** rather than being ignored. An
assertion that silently checks less than it appears to is worse than one that fails.

## Reading a suite

```python
import json
from pathlib import Path

cases = [json.loads(line) for line in Path("cases.jsonl").read_text().splitlines() if line.strip()]
```

Or with the library, which validates as it goes:

```python
from t2e.exporters import cases_jsonl

records = cases_jsonl.parse(Path("cases.jsonl").read_text(encoding="utf-8"))
```

## Evaluating a suite

`t2e.assertions` is a plain library — you do not need the CLI or the server to use an exported suite:

```python
from t2e.assertions import AgentRun, assert_all

result = AgentRun(
    output=my_agent_output,
    tool_calls=["search_counterparty", "get_invoice"],
    citations=["INV-2026-0881"],
    escalated=False,
)
assert_all(result, case["expectations"], case_id=case["case_id"])
```

Reporting structured facts (`tool_calls`, `citations`, `escalated`) is always more reliable than making
the assertions infer them from output text.

## Versioning policy

- `version` (e.g. `v1`) is **yours**: it names a suite generation, and you pick when to cut a new one.
- `schema_version` is **ours**: it describes the record shape and only changes when that shape breaks.
- The generated pytest stub checks `schema_version` and fails if it does not match the `t2e` running it,
  so a stale suite gets re-exported instead of silently mis-evaluated.
- Golden files in `tests/golden/` pin both. Regenerate them deliberately with
  `uv run pytest --snapshot-update` and review the diff before committing.

## Portability

No field is specific to this tool: a case is an input, a list of checks, and some tags. That is the
point — the wedge is that you keep the output (see the honest-positioning section of the README). If you
outgrow `t2e`, the file is still a valid eval suite, and `t2e.assertions` is ~300 lines you can vendor.
