"""Unit tests for the KB lookup and policy check tools."""

import pytest

from support_ticket_triage_and_response.tools.kb_lookup import (
    KBLookupTool,
    _load_articles,
    _tokenize,
)
from support_ticket_triage_and_response.tools.policy_check import (
    PolicyCheckTool,
    _check_disclaimer,
    _check_pii,
    _check_profanity,
    _check_refund_promises,
    _luhn_ok,
    _mask,
)

# A Luhn-valid test card number and the same number with a broken check digit.
VALID_CARD = "4111 1111 1111 1111"
INVALID_CARD = "4111 1111 1111 1112"
DISCLAIMER = "If this helps, great — otherwise reply to this message for more help."


# --------------------------------------------------------------------------- #
# KB lookup tool
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def kb_tool() -> KBLookupTool:
    return KBLookupTool()


def test_load_articles_has_expected_ids():
    ids = {a["id"] for a in _load_articles()}
    assert {"KB001", "KB009", "KB015"} <= ids


def test_tokenize_drops_stopwords_and_short_tokens():
    tokens = _tokenize("How do I export to CSV?")
    assert "export" in tokens and "csv" in tokens
    assert "how" not in tokens  # stopword
    assert "to" not in tokens  # too short


def test_returns_relevant_billing_article(kb_tool):
    out = kb_tool._run(query="I was charged twice for my subscription", category="billing")
    assert "KB001" in out


def test_category_filter_excludes_other_categories(kb_tool):
    # "export to csv" only matches how_to/bug articles; with a billing filter
    # (which has articles, so no broadening) nothing should match.
    out = kb_tool._run(query="export to csv", category="billing")
    assert "No knowledge base articles matched" in out
    assert "KB009" not in out


def test_unknown_category_falls_back_to_all(kb_tool):
    # A category with no articles broadens the search to everything.
    out = kb_tool._run(query="export to csv", category="nonexistent")
    assert "KB009" in out


def test_no_match_returns_message(kb_tool):
    out = kb_tool._run(query="zxqw qwbbb flarn nonsense")
    assert "No knowledge base articles matched" in out


def test_limit_is_respected(kb_tool):
    out = kb_tool._run(query="refund billing account bug export password", limit=1)
    assert out.count("[KB") == 1


def test_output_includes_citable_ids(kb_tool):
    out = kb_tool._run(query="how do I invite teammates to my workspace")
    assert "[KB008]" in out


# --------------------------------------------------------------------------- #
# Policy check tool — refund promises
# --------------------------------------------------------------------------- #
def test_refund_promise_is_flagged():
    assert _check_refund_promises("We will issue you a full refund today.", False)


def test_refund_negation_not_flagged():
    assert _check_refund_promises(
        "Unfortunately we cannot issue a refund without approval.", False
    ) == []


def test_refund_preapproved_suppresses_flag():
    assert _check_refund_promises("We will refund you in full.", True) == []


def test_refund_mention_without_promise_not_flagged():
    assert _check_refund_promises(
        "Refunds for duplicate charges are handled automatically.", False
    ) == []


# --------------------------------------------------------------------------- #
# Policy check tool — profanity
# --------------------------------------------------------------------------- #
def test_profanity_flagged():
    issues = _check_profanity("This is a damn mess.")
    assert issues and "damn" in issues[0]


def test_profanity_word_boundary_no_false_positive():
    # "class" contains "ass" but must not trip the word-boundary matcher.
    assert _check_profanity("Please attend the class and assess the report.") == []


# --------------------------------------------------------------------------- #
# Policy check tool — PII
# --------------------------------------------------------------------------- #
def test_pii_detects_ssn_phone_and_valid_card():
    issues = _check_pii(f"SSN 123-45-6789, call (415) 555-0132, card {VALID_CARD}")
    kinds = " ".join(issues)
    assert "pii:ssn" in kinds
    assert "pii:phone" in kinds
    assert "pii:card" in kinds


def test_pii_ignores_invalid_luhn_card():
    issues = _check_pii(f"Reference number {INVALID_CARD}")
    assert not any("pii:card" in i for i in issues)


def test_pii_allowed_email_domain_not_flagged():
    assert _check_pii("Reach us at support@example.com") == []


def test_pii_disallowed_email_flagged():
    issues = _check_pii("Email me at john.doe@gmail.com")
    assert any("pii:email" in i for i in issues)


def test_pii_output_is_masked():
    issues = _check_pii("SSN 123-45-6789")
    assert "123-45-6789" not in issues[0]  # raw value must not leak


# --------------------------------------------------------------------------- #
# Policy check tool — disclaimer
# --------------------------------------------------------------------------- #
def test_disclaimer_present_passes():
    assert _check_disclaimer(DISCLAIMER) == []


def test_disclaimer_missing_flagged():
    assert _check_disclaimer("Here is how to fix your issue. Thanks!")


# --------------------------------------------------------------------------- #
# Policy check helpers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "digits,expected",
    [
        ("4111111111111111", True),
        ("4111111111111112", False),
        ("123", False),  # too short
    ],
)
def test_luhn_ok(digits, expected):
    assert _luhn_ok(digits) is expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1234567890", "12******90"),
        ("abcd", "****"),
        ("ab", "**"),
    ],
)
def test_mask(value, expected):
    assert _mask(value) == expected


# --------------------------------------------------------------------------- #
# Policy check tool — end to end
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def policy_tool() -> PolicyCheckTool:
    return PolicyCheckTool()


def test_clean_draft_passes(policy_tool):
    out = policy_tool._run(draft_body=f"Try a hard refresh to fix the dashboard. {DISCLAIMER}")
    assert out.startswith("POLICY CHECK PASSED")


def test_multiple_violations_reported(policy_tool):
    draft = "This damn bug again. We will refund you. SSN 123-45-6789."
    out = policy_tool._run(draft_body=draft)
    assert out.startswith("POLICY CHECK FAILED")
    # profanity + refund promise + PII + missing disclaimer
    assert "4 issue(s)" in out
