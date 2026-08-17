"""Tests for the fixture-backed investigation context tools.

All offline and deterministic — they only read the bundled JSON fixtures.
"""

from support_ticket_triage_and_response.tools.fixture_search import (
    keyword_search,
    tokenize,
)
from support_ticket_triage_and_response.tools.incident_lookup import IncidentLookupTool
from support_ticket_triage_and_response.tools.log_search import LogSearchTool
from support_ticket_triage_and_response.tools.metrics_lookup import MetricsLookupTool
from support_ticket_triage_and_response.tools.past_slack_lookup import PastSlackTool
from support_ticket_triage_and_response.tools.past_tickets_lookup import PastTicketsTool


# --------------------------------------------------------------------------- #
# Shared search helper
# --------------------------------------------------------------------------- #
_RECORDS = [
    {"id": "A", "tags": ["dashboard", "timeout"], "text": "render timeout", "service": "web"},
    {"id": "B", "tags": ["billing"], "text": "duplicate charge", "service": "billing"},
]


def test_tokenize_drops_stopwords_and_short_tokens():
    toks = tokenize("The dashboard is not loading")
    assert "dashboard" in toks
    assert "loading" in toks
    assert "the" not in toks and "is" not in toks and "not" not in toks


def test_keyword_search_ranks_by_overlap():
    results = keyword_search(_RECORDS, "dashboard timeout", {"tags": 4.0, "text": 2.0})
    assert results[0]["id"] == "A"


def test_keyword_search_limit_and_no_match():
    assert keyword_search(_RECORDS, "dashboard", {"tags": 4.0}, limit=1) == [_RECORDS[0]]
    assert keyword_search(_RECORDS, "nonexistent xyzzy", {"tags": 4.0}) == []


def test_keyword_search_filter_falls_back_when_empty():
    # No record has service "ghost" -> falls back to full set and still ranks.
    results = keyword_search(
        _RECORDS, "dashboard", {"tags": 4.0},
        filter_field="service", filter_value="ghost",
    )
    assert results and results[0]["id"] == "A"


# --------------------------------------------------------------------------- #
# Tool wrappers
# --------------------------------------------------------------------------- #
def test_log_search_finds_dashboard_entries():
    out = LogSearchTool()._run(query="dashboard timeout spinner")
    assert "LOG-1001" in out
    assert "analytics-dashboard" in out


def test_log_search_service_filter():
    out = LogSearchTool()._run(query="login invalid credentials", service="auth-service")
    assert "LOG-1003" in out


def test_metrics_lookup_finds_latency_regression():
    out = MetricsLookupTool()._run(query="dashboard latency deploy")
    assert "MET-2001" in out


def test_incident_lookup_finds_active_incident():
    out = IncidentLookupTool()._run(query="dashboard not loading after deploy")
    assert "INC-501" in out
    assert "active" in out


def test_past_slack_lookup_returns_resolution():
    out = PastSlackTool()._run(query="webhook 401 signing secret")
    assert "SL-9004" in out
    assert "Resolution:" in out


def test_past_tickets_lookup_category_filter():
    out = PastTicketsTool()._run(query="duplicate charge refund", category="billing", limit=2)
    assert "T02" in out


def test_tool_no_match_message():
    out = LogSearchTool()._run(query="zzzz wwww qqqq vvvv")
    assert "No log entries matched" in out
