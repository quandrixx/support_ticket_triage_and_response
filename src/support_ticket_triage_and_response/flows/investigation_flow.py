"""Slack-invokable investigation flow.

Runs *after* the customer has replied in the Slack thread with additional
detail (the intake questions are generated separately by ``intake_crew`` and
posted by the Slack app). This flow is fully synchronous — the wait for the
customer happens in the Slack event loop, not here:

    triage -> build dossier (+ env context) -> differential diagnosis
           -> draft customer reply (KB-grounded) -> sanitize reply

The final state carries both the internal artefacts (dossier + diagnosis) for
the engineer channel and the ``sanitized_reply`` for the customer thread.
"""

from crewai.flow.flow import Flow, listen, start

from support_ticket_triage_and_response.crews.compliance_crew.compliance_crew import (
    kickoff_compliance_crew,
)
from support_ticket_triage_and_response.crews.investigation_crew.investigation_crew import (
    kickoff_investigation_crew,
)
from support_ticket_triage_and_response.crews.response_crew.response_crew import (
    kickoff_response_crew,
)
from support_ticket_triage_and_response.crews.triage_crew.triage_crew import (
    kickoff_triage_crew,
)
from support_ticket_triage_and_response.models import InvestigationState


class InvestigationFlow(Flow[InvestigationState]):
    """Build an engineer-facing dossier + diagnosis and a sanitized customer reply."""

    @start()
    def triage_ticket(self):
        """Classify the ticket so downstream crews get category/urgency context."""
        result = kickoff_triage_crew({"ticket_text": self.state.ticket_text})
        self.state.triage = result.pydantic

    @listen(triage_ticket)
    def build_investigation(self):
        """Gather production state, synthesize the dossier, then diagnose.

        The investigation crew runs two sequential tasks; ``tasks_output[0]`` is
        the Dossier and ``tasks_output[1]`` is the DifferentialDiagnosis.
        """
        result = kickoff_investigation_crew(
            {
                "ticket_text": self.state.ticket_text,
                "customer_details": self.state.customer_details,
                "triage_summary": self.state.triage.summary if self.state.triage else "",
            }
        )
        self.state.dossier = result.tasks_output[0].pydantic
        self.state.diagnosis = result.tasks_output[-1].pydantic

    @listen(build_investigation)
    def draft_customer_reply(self):
        """Draft a KB-grounded, customer-facing reply (reuses the response crew)."""
        result = kickoff_response_crew(
            {
                "ticket_text": self.state.ticket_text,
                "category": self.state.triage.category.value if self.state.triage else "other",
                "triage_summary": self.state.triage.summary if self.state.triage else "",
            }
        )
        self.state.customer_reply = result.pydantic

    @listen(draft_customer_reply)
    def sanitize_reply(self):
        """Sanitize the customer reply via the deterministic policy/compliance crew.

        Reuses the same compliance crew as the main flow. We always adopt the
        checker's corrected text when it supplies one, so PII/refund-promise/
        profanity issues are stripped before the reply reaches the customer.
        """
        draft_body = self.state.customer_reply.body if self.state.customer_reply else ""
        result = kickoff_compliance_crew(
            {"ticket_text": self.state.ticket_text, "draft_body": draft_body}
        )
        self.state.sanitized = result.pydantic

        revised = self.state.sanitized.revised_body if self.state.sanitized else None
        self.state.sanitized_reply = revised or draft_body
        return self.state
