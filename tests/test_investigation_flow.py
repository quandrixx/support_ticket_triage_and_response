"""Wiring tests for InvestigationFlow.

The crew kickoffs are mocked to return canned pydantic objects so we can assert
the flow threads triage -> dossier/diagnosis -> draft -> sanitize correctly,
without any LLM calls.
"""

import types

import support_ticket_triage_and_response.flows.investigation_flow as flow_mod
from support_ticket_triage_and_response.flows.investigation_flow import InvestigationFlow
from support_ticket_triage_and_response.models import (
    ComplianceCheck,
    DifferentialDiagnosis,
    Dossier,
    DraftResponse,
    EnvironmentContext,
    Hypothesis,
    TicketCategory,
    TriageResult,
)


def _crew_output(pydantic):
    return types.SimpleNamespace(pydantic=pydantic)


def _investigation_output(dossier, diagnosis):
    """Mimic a two-task CrewOutput: the flow reads ``tasks_output[0/-1].pydantic``."""
    return types.SimpleNamespace(
        tasks_output=[_crew_output(dossier), _crew_output(diagnosis)]
    )


def _dossier():
    return Dossier(
        customer_summary="Priya, Ops Manager at BrightLoop",
        issue_summary="Dashboard spins and never loads",
        collected_details="Started after this morning's deploy; all browsers",
        environment=EnvironmentContext(
            log_findings=["LOG-1001 render timeout"],
            metric_findings=["MET-2001 latency regression"],
            incidents=["INC-501 active SEV2"],
        ),
        timeline=["08:05 deploy v3.11.0", "08:12 timeouts"],
        affected_components=["analytics-dashboard"],
    )


def _diagnosis():
    return DifferentialDiagnosis(
        hypotheses=[
            Hypothesis(
                cause="Un-indexed aggregation query in v3.11.0",
                likelihood=0.8,
                evidence=["INC-501", "MET-2001"],
                recommended_action="Roll back v3.11.0",
            )
        ],
        top_recommendation="Roll back v3.11.0",
    )


def _patch(monkeypatch, *, triage, dossier, diagnosis, draft, compliance):
    monkeypatch.setattr(flow_mod, "kickoff_triage_crew", lambda i: _crew_output(triage))
    monkeypatch.setattr(
        flow_mod,
        "kickoff_investigation_crew",
        lambda i: _investigation_output(dossier, diagnosis),
    )
    monkeypatch.setattr(flow_mod, "kickoff_response_crew", lambda i: _crew_output(draft))
    monkeypatch.setattr(
        flow_mod, "kickoff_compliance_crew", lambda i: _crew_output(compliance)
    )


def _run(monkeypatch, **kwargs):
    _patch(monkeypatch, **kwargs)
    flow = InvestigationFlow()
    flow.kickoff(inputs={"ticket_text": "Dashboard won't load", "customer_details": "after deploy"})
    return flow.state


def test_flow_populates_dossier_and_diagnosis(monkeypatch):
    state = _run(
        monkeypatch,
        triage=TriageResult(category=TicketCategory.BUG, urgency=2, summary="bug", requires_human=False),
        dossier=_dossier(),
        diagnosis=_diagnosis(),
        draft=DraftResponse(body="We are looking into it. Reply to this to reach support.", confidence=0.7, cited_kb_articles=[]),
        compliance=ComplianceCheck(passed=True, issues=[], revised_body=None),
    )
    assert state.dossier.issue_summary.startswith("Dashboard")
    assert state.diagnosis.top_recommendation == "Roll back v3.11.0"
    assert state.diagnosis.hypotheses[0].likelihood == 0.8


def test_sanitized_reply_uses_original_when_clean(monkeypatch):
    clean_body = "We are investigating. Reply to this message to reach support."
    state = _run(
        monkeypatch,
        triage=TriageResult(category=TicketCategory.BUG, urgency=2, summary="bug", requires_human=False),
        dossier=_dossier(),
        diagnosis=_diagnosis(),
        draft=DraftResponse(body=clean_body, confidence=0.7, cited_kb_articles=[]),
        compliance=ComplianceCheck(passed=True, issues=[], revised_body=None),
    )
    assert state.sanitized_reply == clean_body


def test_sanitized_reply_adopts_revised_body(monkeypatch):
    state = _run(
        monkeypatch,
        triage=TriageResult(category=TicketCategory.BILLING, urgency=2, summary="b", requires_human=False),
        dossier=_dossier(),
        diagnosis=_diagnosis(),
        draft=DraftResponse(body="We will refund you now.", confidence=0.7, cited_kb_articles=[]),
        compliance=ComplianceCheck(
            passed=False,
            issues=["refund_promise"],
            revised_body="We're reviewing your billing issue. Contact support for next steps.",
        ),
    )
    # The customer-facing reply is the sanitized/revised text, not the raw draft.
    assert "refund you now" not in state.sanitized_reply
    assert state.sanitized_reply.startswith("We're reviewing")


def test_category_falls_back_when_triage_missing(monkeypatch):
    captured = {}

    def _resp(inputs):
        captured.update(inputs)
        return _crew_output(DraftResponse(body="ok. contact support", confidence=0.5, cited_kb_articles=[]))

    monkeypatch.setattr(flow_mod, "kickoff_triage_crew", lambda i: _crew_output(None))
    monkeypatch.setattr(
        flow_mod, "kickoff_investigation_crew", lambda i: _investigation_output(_dossier(), _diagnosis())
    )
    monkeypatch.setattr(flow_mod, "kickoff_response_crew", _resp)
    monkeypatch.setattr(
        flow_mod, "kickoff_compliance_crew",
        lambda i: _crew_output(ComplianceCheck(passed=True, issues=[], revised_body=None)),
    )

    flow = InvestigationFlow()
    flow.kickoff(inputs={"ticket_text": "x", "customer_details": "y"})
    assert captured["category"] == "other"
