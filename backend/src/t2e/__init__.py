"""Trace2Evals - turn agent traces into versioned eval cases you own.

Local-first and fully offline: no LLM calls, no telemetry, no network at runtime.
"""

__version__ = "0.1.0"

# Bumped only on a breaking change to the exported cases.jsonl record shape.
# Every exported case carries this so goldens and downstream readers can pin it.
CASE_SCHEMA_VERSION = 1
