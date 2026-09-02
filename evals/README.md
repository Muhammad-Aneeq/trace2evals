# `evals/` — the CI gate

Every repository in this portfolio ships an `evals/` folder with a CI gate (spec 00 A1). This one holds
the suite produced by dogfooding Trace2Evals on its own fixtures.

> ⚠️ These cases were built from **synthetic** fixtures, because no real traces were provided
> (see [BLOCKERS.md](../BLOCKERS.md) B-001). They are real in structure and real as *judgements*; they
> are not real production failures.

## Contents

| File | What it is |
|---|---|
| `cases.jsonl` | 16 versioned eval cases, exported at `v1`. Schema: [`docs/cases_schema.md`](../docs/cases_schema.md) |
| `test_cases.py` | The generated pytest stub. Not hand-written — regenerate it, don't edit it. |
| `conftest.py` | The `run_agent` adapter hook. Skips by default (see below). |

Both artefacts are produced by [`scripts/dogfood.py`](../scripts/dogfood.py) and are committed, so the
labels behind them are auditable. CI checks they are current with `git diff --exit-code`, because a
stale suite in the repo would be a quiet lie about what was actually labeled.

## What the gate actually checks

Run it with `make eval` (or `./make.ps1 eval`, or `uv run pytest evals/`):

```
17 passed, 17 skipped
```

- **17 passed** — suite integrity: the cases parse, every record carries the expected
  `schema_version`, and **every case has at least one assertion**. That last one matters: a case with
  no expectations passes forever and silently hides a regression.
- **17 skipped** — the per-case agent evaluations. They skip because **there is no agent in this
  repository**. Trace2Evals is the labeling and export tool, not the system under test.

This is the honest gate available here. Claiming an agent score would mean inventing an agent.

## Turning it into a real eval gate

In your own project, replace the fixture body in `conftest.py` with a call into your agent and set
`T2E_EVAL_ADAPTER=1`:

```python
@pytest.fixture
def run_agent():
    def _run(case_input: str):
        result = my_agent.investigate(case_input)
        return {
            "output": result.text,
            "tool_calls": [call.name for call in result.calls],
            "citations": result.evidence_ids,
            "escalated": result.escalated,
        }
    return _run
```

Reporting structured facts (`tool_calls`, `citations`, `escalated`) is more reliable than making the
assertions infer them from output text. The 17 skips then become 17 real checks.

## What is in the suite

From the dogfood run (`make dogfood`):

| Verdict | Runs | Cases built |
|---|---|---|
| right | 10 | 10 regression guards |
| partial | 4 | 4 |
| wrong | 2 | 2 |

27 assertions across the 16 cases (11 cases carry two, 5 carry one, none carries zero):

| Assertion kind | Cases |
|---|---|
| `must_cite` | 14 |
| `must_call_tool` | 10 |
| `must_escalate` | 3 |
| `output_matches_regex` | 0 |
| `output_matches_schema` | 0 |

The skew toward `must_cite` follows directly from the label distribution — `ungrounded` was the most
common failure tag. The two output-shape assertions are unused because no fixture was tagged
`format_break`; they are covered by the unit and golden tests instead. See the findings section of the
[README](../README.md).

## Regenerating

```bash
make dogfood                 # re-label the fixtures and re-export into evals/
uv run t2e export --version v1 --format jsonl,pytest --out evals
```

Review the diff before committing: a change to `cases.jsonl` is a change to what this repo claims was
labeled.
