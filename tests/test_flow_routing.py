"""Routing tests for SupportTicketFlow.

The crew kickoffs are mocked to return canned TriageResult / DraftResponse /
ComplianceCheck objects so we can assert the flow reaches the correct terminal
state for each combination without any LLM calls.
"""

import types

import pytest

import support_ticket_triage_and_response.flows.support_ticket_flow as flow_mod
from support_ticket_triage_and_response.flows.support_ticket_flow import (
    MAX_COMPLIANCE_ATTEMPTS,
    SupportTicketFlow,
)
from support_ticket_triage_and_response.models import (
    ComplianceCheck,
    DraftResponse,
    TicketCategory,
    TicketStatus,
    TriageResult,
)

ORIGINAL_BODY = "Original draft body."


# --------------------------------------------------------------------------- #
# Canned-object factories
# --------------------------------------------------------------------------- #
def _crew_output(pydantic):
    """Mimic a CrewOutput: the flow only reads ``.pydantic``."""
    return types.SimpleNamespace(pydantic=pydantic)


def _triage(requires_human=False, category=TicketCategory.BILLING, urgency=3):
    return TriageResult(
        category=category, urgency=urgency, summary="s", requires_human=requires_human
    )


def _draft(body=ORIGINAL_BODY):
    return DraftResponse(body=body, confidence=0.9, cited_kb_articles=[])


def _compliance(passed, revised_body=None, issues=None):
    return ComplianceCheck(passed=passed, issues=issues or [], revised_body=revised_body)


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #
def _patch(monkeypatch, *, triage, draft=None, compliance_seq=None):
    """Patch the three crew kickoffs; unused crews raise if called."""
    monkeypatch.setattr(flow_mod, "kickoff_triage_crew", lambda i: _crew_output(triage))

    def _no_draft(inputs):
        raise AssertionError("response crew should not have run")

    monkeypatch.setattr(
        flow_mod,
        "kickoff_response_crew",
        (lambda i: _crew_output(draft)) if draft is not None else _no_draft,
    )

    calls = {"n": 0, "bodies": []}

    def _no_compliance(inputs):
        raise AssertionError("compliance crew should not have run")

    def _compliance_call(inputs):
        calls["bodies"].append(inputs["draft_body"])
        result = compliance_seq[min(calls["n"], len(compliance_seq) - 1)]
        calls["n"] += 1
        return _crew_output(result)

    monkeypatch.setattr(
        flow_mod,
        "kickoff_compliance_crew",
        _compliance_call if compliance_seq is not None else _no_compliance,
    )
    return calls


def _run(monkeypatch, **kwargs):
    calls = _patch(monkeypatch, **kwargs)
    flow = SupportTicketFlow()
    flow.kickoff(inputs={"ticket_text": "test ticket"})
    return flow.state, calls


# --------------------------------------------------------------------------- #
# Triage gate
# --------------------------------------------------------------------------- #
def test_requires_human_escalates_without_drafting(monkeypatch):
    state, _ = _run(monkeypatch, triage=_triage(requires_human=True))
    assert state.final_status is TicketStatus.NEEDS_REVIEW
    assert state.draft is None
    assert state.compliance is None


def test_missing_triage_escalates(monkeypatch):
    # kickoff returns no pydantic -> triage is None -> escalate.
    state, _ = _run(monkeypatch, triage=None)
    assert state.final_status is TicketStatus.NEEDS_REVIEW
    assert state.draft is None


# --------------------------------------------------------------------------- #
# Compliance routing
# --------------------------------------------------------------------------- #
def test_clean_draft_is_auto_sent(monkeypatch):
    state, calls = _run(
        monkeypatch,
        triage=_triage(),
        draft=_draft(),
        compliance_seq=[_compliance(True)],
    )
    assert state.final_status is TicketStatus.AUTO_SENT
    assert state.compliance_attempts == 0
    assert calls["n"] == 1
    assert state.draft.body == ORIGINAL_BODY


def test_passed_with_revision_adopts_revised_body(monkeypatch):
    state, calls = _run(
        monkeypatch,
        triage=_triage(),
        draft=_draft(),
        compliance_seq=[_compliance(True, revised_body="Cleaned body.")],
    )
    assert state.final_status is TicketStatus.AUTO_SENT
    assert state.compliance_attempts == 0
    assert state.draft.body == "Cleaned body."


def test_revise_then_pass_rechecks_revised_body(monkeypatch):
    state, calls = _run(
        monkeypatch,
        triage=_triage(),
        draft=_draft(),
        compliance_seq=[
            _compliance(False, revised_body="Revised body.", issues=["refund"]),
            _compliance(True),
        ],
    )
    assert state.final_status is TicketStatus.AUTO_SENT
    assert state.compliance_attempts == 1
    assert state.draft.body == "Revised body."
    # The second compliance run must have seen the revised text, not the original.
    assert calls["n"] == 2
    assert calls["bodies"] == [ORIGINAL_BODY, "Revised body."]


def test_uncorrectable_escalates_immediately(monkeypatch):
    state, calls = _run(
        monkeypatch,
        triage=_triage(),
        draft=_draft(),
        compliance_seq=[_compliance(False, revised_body=None, issues=["pii"])],
    )
    assert state.final_status is TicketStatus.NEEDS_REVIEW
    assert state.compliance_attempts == 0
    assert calls["n"] == 1
    assert state.draft.body == ORIGINAL_BODY  # untouched


def test_persistent_failure_escalates_after_cap(monkeypatch):
    # Always fails but keeps offering a revision -> loop until the cap, then human.
    state, calls = _run(
        monkeypatch,
        triage=_triage(),
        draft=_draft(),
        compliance_seq=[
            _compliance(False, revised_body=f"try {i}", issues=["x"]) for i in range(1, 6)
        ],
    )
    assert state.final_status is TicketStatus.NEEDS_REVIEW
    assert state.compliance_attempts == MAX_COMPLIANCE_ATTEMPTS
    # initial check + MAX retries
    assert calls["n"] == MAX_COMPLIANCE_ATTEMPTS + 1


def test_missing_compliance_result_escalates(monkeypatch):
    state, calls = _run(
        monkeypatch,
        triage=_triage(),
        draft=_draft(),
        compliance_seq=[None],  # kickoff returns no pydantic
    )
    assert state.final_status is TicketStatus.NEEDS_REVIEW
    assert calls["n"] == 1
