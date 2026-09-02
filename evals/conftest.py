"""Adapter wiring for the exported eval suite.

There is no agent in this repository - Trace2Evals is the labeling and export tool, not the agent under
test. So the `run_agent` fixture here **skips** rather than pretending to run something.

That makes `make eval` a *suite-integrity* gate, which is the honest thing it can be here:

    passes  - the suite exists, its records are the right schema version, and every case carries at
              least one assertion (i.e. no case would pass vacuously forever)
    skips   - the per-case agent evaluations, because no adapter is configured

To turn this into a real eval gate in your own project, replace the fixture body with a call into your
agent and return what it did:

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

Set `T2E_EVAL_ADAPTER=1` once you have done that, and the skip turns into a real run.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def run_agent():
    if not os.environ.get("T2E_EVAL_ADAPTER"):
        pytest.skip(
            "no agent adapter configured: this repo ships the labeling tool, not an agent under "
            "test. See evals/conftest.py to wire one in, then set T2E_EVAL_ADAPTER=1."
        )

    def _run(case_input: str):  # pragma: no cover - reached only with a real adapter configured
        raise NotImplementedError(
            "T2E_EVAL_ADAPTER is set but this fixture was not replaced with a real adapter. "
            "Edit evals/conftest.py."
        )

    return _run
