"""Tests for the Slack integration's pure logic (no Slack/network required).

``start_investigation`` and ``complete_investigation`` take an injected client,
so we drive them with a fake client and monkeypatched crew/flow.
"""

import types

import support_ticket_triage_and_response.integrations.slack_app as slack_app
from support_ticket_triage_and_response.integrations.slack_app import (
    PendingInvestigationStore,
    complete_investigation,
    format_dossier_and_diagnosis,
    format_questions,
    start_investigation,
)
from support_ticket_triage_and_response.models import (
    DifferentialDiagnosis,
    Dossier,
    EnvironmentContext,
    Hypothesis,
    InvestigationState,
)


class FakeClient:
    def __init__(self, ts="1700000000.000100"):
        self.ts = ts
        self.calls: list[dict] = []

    def chat_postMessage(self, **kwargs):
        self.calls.append(kwargs)
        return {"ts": self.ts}


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def test_store_add_get_pop_and_persistence(tmp_path):
    path = tmp_path / "pending.json"
    store = PendingInvestigationStore(path)
    store.add("ts1", "ticket text", "C123")
    assert "ts1" in store
    assert store.get("ts1") == {"ticket_text": "ticket text", "channel": "C123"}

    # A fresh store from the same file sees the persisted record.
    reloaded = PendingInvestigationStore(path)
    assert "ts1" in reloaded
    assert reloaded.pop("ts1")["ticket_text"] == "ticket text"
    assert "ts1" not in reloaded


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #
def test_format_questions_numbers_items():
    out = format_questions(["When did it start?", "What error do you see?"])
    assert "1. When did it start?" in out
    assert "2. What error do you see?" in out


def test_format_dossier_and_diagnosis_includes_sections():
    state = InvestigationState(
        dossier=Dossier(
            customer_summary="Priya",
            issue_summary="Dashboard down",
            collected_details="after deploy",
            environment=EnvironmentContext(log_findings=["LOG-1001"], incidents=["INC-501"]),
            timeline=["08:05 deploy"],
            affected_components=["analytics-dashboard"],
        ),
        diagnosis=DifferentialDiagnosis(
            hypotheses=[Hypothesis(cause="bad query", likelihood=0.8, evidence=["INC-501"], recommended_action="roll back")],
            top_recommendation="roll back",
        ),
    )
    out = format_dossier_and_diagnosis(state)
    assert "Investigation dossier" in out
    assert "Differential diagnosis" in out
    assert "LOG-1001" in out
    assert "bad query" in out
    assert "roll back" in out


# --------------------------------------------------------------------------- #
# start_investigation (Phase 1)
# --------------------------------------------------------------------------- #
def test_start_investigation_posts_questions_and_registers_pending(monkeypatch):
    monkeypatch.setattr(
        slack_app,
        "kickoff_intake_crew",
        lambda inputs: types.SimpleNamespace(
            pydantic=types.SimpleNamespace(questions=["When did it start?"])
        ),
    )
    client = FakeClient(ts="1700000000.000200")
    store = PendingInvestigationStore()

    thread_ts = start_investigation(
        "Dashboard won't load", client=client, channel="C999", store=store
    )

    assert thread_ts == "1700000000.000200"
    assert thread_ts in store
    assert store.get(thread_ts)["channel"] == "C999"
    assert len(client.calls) == 1
    assert "When did it start?" in client.calls[0]["text"]
    assert client.calls[0]["channel"] == "C999"


# --------------------------------------------------------------------------- #
# complete_investigation (Phase 2)
# --------------------------------------------------------------------------- #
def test_complete_investigation_posts_reply_and_dossier(monkeypatch):
    # Fake flow that yields a known sanitized reply + dossier/diagnosis.
    fake_state = InvestigationState(
        sanitized_reply="Here is your sanitized answer. Contact support if needed.",
        dossier=Dossier(
            customer_summary="Priya", issue_summary="Dashboard down", collected_details="d",
            environment=EnvironmentContext(incidents=["INC-501"]),
        ),
        diagnosis=DifferentialDiagnosis(
            hypotheses=[Hypothesis(cause="bad query", likelihood=0.8, evidence=[], recommended_action="roll back")],
            top_recommendation="roll back",
        ),
    )

    class FakeFlow:
        def __init__(self):
            self.state = fake_state

        def kickoff(self, inputs):
            self.received = inputs

    monkeypatch.setattr(slack_app, "InvestigationFlow", FakeFlow)

    client = FakeClient()
    store = PendingInvestigationStore()
    store.add("ts1", "Dashboard won't load", "C999")

    state = complete_investigation(
        "ts1", "Started after the deploy", client=client,
        engineer_channel="C_ENG", store=store,
    )

    assert state is fake_state
    assert "ts1" not in store  # pending cleared

    # Two posts: sanitized reply to the customer thread, dossier to engineers.
    customer_post = next(c for c in client.calls if c.get("thread_ts") == "ts1")
    assert customer_post["channel"] == "C999"
    assert customer_post["text"] == "Here is your sanitized answer. Contact support if needed."

    engineer_post = next(c for c in client.calls if c["channel"] == "C_ENG")
    assert "Investigation dossier" in engineer_post["text"]
    assert "INC-501" in engineer_post["text"]


def test_complete_investigation_noop_for_unknown_thread(monkeypatch):
    monkeypatch.setattr(slack_app, "InvestigationFlow", lambda: (_ for _ in ()).throw(AssertionError("flow should not run")))
    client = FakeClient()
    store = PendingInvestigationStore()
    result = complete_investigation(
        "missing", "details", client=client, engineer_channel="C_ENG", store=store
    )
    assert result is None
    assert client.calls == []
