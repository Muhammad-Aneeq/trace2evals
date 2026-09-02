# Trace fixtures

> ⚠️ **All data in this directory is synthetic.** Every trace here was hand-authored for this
> repository. No real agent run, customer, vendor, invoice, bank account or person is represented.
> Company names, ids, amounts, emails, phone numbers, IBANs and card numbers are invented; the card
> number in `otel/02_tool_heavy_with_pii.json` is the standard `4111111111111111` test value.

## Why these exist

The build brief allowed real trace exports to be dropped at `./seed_traces/`, which would have been the
primary fixture set and the dogfood target. That directory was not provided
(see [BLOCKERS.md](../BLOCKERS.md) **B-001**), so these fixtures stand in.

They are written to match the real wire shapes of both formats rather than a shape convenient for the
parser, because spec 03 sec 10 asks for "6 real-shaped sample files per format incl. malformed records".
The importers key off format structure, not off these files, so real exports can be dropped into
`seed_traces/` later and imported with no code change.

## Scenario

All twelve fixtures are runs of a **reconciliation exception investigation agent** — the domain of
Project 01, whose traces spec 03 sec 10 names as the intended dogfood source. Several runs are
deliberately *bad* agent behaviour, because a labeling tool with only successful traces in it is
untestable.

## OpenTelemetry JSON — `otel/`

| File | Shape exercised | Agent behaviour |
|---|---|---|
| `01_clean_reconciliation.json` | OTLP `resourceSpans`, attribute list, `gen_ai.prompt`/`completion` | Correct partial-payment diagnosis with evidence ids |
| `02_tool_heavy_with_pii.json` | 6 tool spans, token-usage attributes | Correct duplicate-payment rejection; payloads contain PII-lookalikes (email, phone, IBAN, Luhn-valid card) to exercise redaction |
| `03_tool_error_no_escalation.json` | `status.code: 2` plus an `exception` event | Tool fails, agent invents an approver and a purchase order instead of escalating — hallucination + no-escalation |
| `04_handoff_two_traces.json` | Two `resourceSpans` entries, two traces, nested `invoke_agent` | Trace 1: router hands off to an FX specialist and escalates correctly. Trace 2: clean counterparty match |
| `05_minimal_flat_events.json` | Flat `{"spans": [...]}`, snake_case keys, prompt/completion in **span events** | Single model call, materiality judgement |
| `06_malformed_mixed.json` | Valid traces beside a string where an object belongs, a `resourceSpans` entry with no `scopeSpans`, a number in `scopeSpans`, a `null` span, unparseable timestamps, and an infrastructure-only trace | Good records must still import |

## LangSmith run export JSONL — `langsmith/`

| File | Shape exercised | Agent behaviour |
|---|---|---|
| `01_clean_reconciliation.jsonl` | Root chain + llm + 2 tools, full `dotted_order` | Correct amount-plus-counterparty match |
| `02_wrong_tool_bad_args.jsonl` | Root chain + llm + 2 tools | Queries the GL by invoice id and the bank feed by a wrong date window, then concludes the supplier is mistaken — wrong-tool / bad-args |
| `03_tool_error_run_failed.jsonl` | Run-level `error` plus a failing tool record, `outputs: null` | Tool exhausts retries against a 503; run fails outright |
| `04_nested_handoff.jsonl` | Nested chain (handoff) with its own children, plus a `parser` record | Accrual schedule end-dated; correct escalation. The `parser` record must be skipped as noise |
| `05_minimal_no_trace_id.jsonl` | **No `trace_id` and no `dotted_order`** — grouping must fall back to walking `parent_run_id` | Two independent runs: a materiality judgement and an instalment residual |
| `06_malformed_mixed.jsonl` | An unknown `run_type`, a truncated line, an orphaned fragment, a bare JSON string, a record with neither `id` nor `trace_id`, then a valid run | Good records must still import |

## Regenerating snapshots

Normalization output is snapshot-tested. If you change a fixture or the normalizer on purpose:

```bash
uv run pytest tests/test_parsers_otel.py tests/test_parsers_langsmith.py --snapshot-update
```

Review the resulting diff in `tests/snapshots/` before committing it.
