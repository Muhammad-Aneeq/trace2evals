"""Redaction and PII-lookalike detection (spec 03 sec 11)."""

from __future__ import annotations

import pytest

from t2e import redaction
from t2e.normalizer import normalize_run
from t2e.redaction import redact_raw_run, redact_text, redact_value, scan_for_pii
from t2e.schemas import RawRun, RawStep


@pytest.mark.parametrize(
    ("text", "pattern_name"),
    [
        ("write to accounts@northwind-supplies.example please", "email"),
        ("card 4111111111111111 on file", "credit_card"),
        ("ssn 123-45-6789 recorded", "ssn"),
        ("IBAN GB29NWBK60161331926819 for settlement", "iban"),
        ("key sk-abcdefghijklmnopqrstuvwx in config", "api_key"),
        ("token ghp_abcdefghijklmnopqrstuvwxyz01 committed", "api_key"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "bearer_token"),
        ("call +44 20 7946 0958 today", "phone"),
        ("host 192.168.14.22 refused", "ipv4"),
    ],
)
def test_each_pattern_redacts(text, pattern_name):
    result, count, flags = redact_text(text)

    assert count >= 1
    assert pattern_name in flags
    assert f"[REDACTED:{pattern_name}]" in result


def test_redaction_removes_the_secret_itself():
    result, _, _ = redact_text("email me at jane.doe@example.com about it")

    assert "jane.doe@example.com" not in result
    assert result == "email me at [REDACTED:email] about it"


def test_redaction_is_idempotent():
    once, count_one, _ = redact_text("contact accounts@vendor.example now")
    twice, count_two, _ = redact_text(once)

    assert once == twice
    assert count_one == 1
    assert count_two == 0, "the placeholder must not itself match a pattern"


def test_ordinary_finance_text_is_not_touched():
    """Invoice ids, amounts and PO numbers must survive: false positives destroy the payload."""
    text = (
        "Invoice INV-2026-0881 gross 6,000.00 GBP settles against PO-77120 and GL-88213; "
        "residual 1,187.50 remains open as at 2026-08-14."
    )
    result, count, flags = redact_text(text)

    assert result == text
    assert count == 0
    assert flags == []


def test_card_shaped_ids_that_fail_luhn_are_preserved():
    """A 16-digit reference number is not a card number unless it passes Luhn."""
    text = "reference 1234567890123456 on the remittance"
    result, count, _ = redact_text(text)

    assert result == text
    assert count == 0

    valid, count, _ = redact_text("card 4111111111111111 charged")
    assert "[REDACTED:credit_card]" in valid
    assert count == 1


def test_detect_only_patterns_flag_without_rewriting():
    text = "delivery to 42 Wellington Street per the contract"
    result, count, flags = redact_text(text)

    assert result == text, "detect-only patterns must never rewrite"
    assert count == 0
    assert "street_address" in flags


def test_multiple_secrets_in_one_string_all_go():
    text = "reach jane@example.com or +44 20 7946 0958"
    result, count, flags = redact_text(text)

    assert count == 2
    assert set(flags) == {"email", "phone"}
    assert "example.com" not in result


# --- nested payloads ----------------------------------------------------------------------------


def test_redaction_walks_nested_structures():
    payload = {
        "counterparty": {
            "contact_email": "accounts@vendor.example",
            "phones": ["+44 20 7946 0958"],
        },
        "amount": 2340.0,
        "flags": [{"note": "card 4111111111111111"}],
    }
    result, count, flags = redact_value(payload)

    assert count == 3
    assert set(flags) == {"email", "phone", "credit_card"}
    assert result["counterparty"]["contact_email"] == "[REDACTED:email]"
    assert result["counterparty"]["phones"] == ["[REDACTED:phone]"]
    assert result["flags"][0]["note"] == "card [REDACTED:credit_card]"
    assert result["amount"] == 2340.0, "non-string values must pass through untouched"


def test_scan_detects_without_modifying():
    payload = {"email": "a@b.example"}
    flags = scan_for_pii(payload)

    assert flags == ["email"]
    assert payload == {"email": "a@b.example"}, "scanning must not mutate its input"


# --- run-level redaction ------------------------------------------------------------------------


def _raw_run_with_pii() -> RawRun:
    return RawRun(
        run_id="r1",
        source="otel",
        input={"input": "contact accounts@vendor.example about INV-1"},
        output="confirmed with accounts@vendor.example",
        steps=[
            RawStep(
                kind="tool",
                name="search_counterparty",
                args={"email": "accounts@vendor.example"},
                output={"phone": "+44 20 7946 0958"},
                error="lookup failed for accounts@vendor.example",
            )
        ],
    )


def test_run_redaction_covers_input_output_steps_and_errors():
    cleaned, count, flags = redact_raw_run(_raw_run_with_pii())

    assert count == 5
    assert set(flags) == {"email", "phone"}
    assert "vendor.example" not in str(cleaned.model_dump())


def test_previews_are_built_from_redacted_payloads():
    """Redaction runs before normalization, so a secret can never leak through a preview."""
    cleaned, _, _ = redact_raw_run(_raw_run_with_pii())
    run = normalize_run(cleaned)

    assert "vendor.example" not in run.steps[0].args_preview
    assert "vendor.example" not in run.input
    assert "vendor.example" not in run.outcome.output
    assert "[REDACTED:email]" in run.steps[0].args_preview


def test_tool_names_are_not_redacted():
    cleaned, _, _ = redact_raw_run(_raw_run_with_pii())
    assert cleaned.steps[0].name == "search_counterparty"


def test_custom_patterns_can_be_loaded_from_a_file(tmp_path):
    patterns_file = tmp_path / "patterns.txt"
    patterns_file.write_text(
        "# extra project patterns\nemployee_id=\\bEMP-\\d{6}\\b\nbroken=([unclosed\n",
        encoding="utf-8",
    )

    extra = redaction.load_extra_patterns(patterns_file)

    assert [p.name for p in extra] == ["employee_id"], "an invalid regex is skipped, not fatal"

    result, count, _ = redact_text("raised by EMP-004417", patterns=extra)
    assert result == "raised by [REDACTED:employee_id]"
    assert count == 1


def test_missing_patterns_file_is_not_fatal(tmp_path):
    assert redaction.load_extra_patterns(tmp_path / "absent.txt") == []
