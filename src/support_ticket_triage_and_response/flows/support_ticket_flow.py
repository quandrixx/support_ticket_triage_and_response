from crewai.flow.flow import Flow, listen, or_, router, start

from support_ticket_triage_and_response.crews.compliance_crew.compliance_crew import (
    kickoff_compliance_crew,
)
from support_ticket_triage_and_response.crews.response_crew.response_crew import (
    kickoff_response_crew,
)
from support_ticket_triage_and_response.crews.triage_crew.triage_crew import (
    kickoff_triage_crew,
)
from support_ticket_triage_and_response.models import TicketState, TicketStatus

# Cap the revise -> recheck loop so a draft that can't be made compliant
# eventually escalates to a human instead of looping forever.
MAX_COMPLIANCE_ATTEMPTS = 2


class SupportTicketFlow(Flow[TicketState]):
    """Triage an incoming support ticket and draft an initial response.

    Pipeline:
        triage -> (auto_respond | needs_human)
        auto_respond -> draft -> check_compliance
        check_compliance -> (send | revise_and_recheck -> check_compliance | needs_human)
    """

    @start()
    def triage_ticket(self):
        """Classify the ticket: category, urgency, and whether a human is needed."""
        result = kickoff_triage_crew({"ticket_text": self.state.ticket_text})
        self.state.triage = result.pydantic

    @router(triage_ticket)
    def route_after_triage(self):
        """Skip auto-response entirely when the triage flags it for a human."""
        if self.state.triage is None or self.state.triage.requires_human:
            return "needs_human"
        return "auto_respond"

    @listen("auto_respond")
    def draft_response(self):
        """Draft a reply grounded in the knowledge base."""
        result = kickoff_response_crew(
            {
                "ticket_text": self.state.ticket_text,
                "category": self.state.triage.category.value,
                "triage_summary": self.state.triage.summary,
            }
        )
        self.state.draft = result.pydantic

    @listen(or_(draft_response, "revise_and_recheck"))
    def check_compliance(self):
        """Run the deterministic policy/compliance check against the current draft.

        Re-runs on every revision so ``compliance.passed`` always reflects the
        draft that would actually be sent.
        """
        result = kickoff_compliance_crew(
            {
                "ticket_text": self.state.ticket_text,
                "draft_body": self.state.draft.body,
            }
        )
        self.state.compliance = result.pydantic

    @router(check_compliance)
    def route_after_compliance(self):
        """Send a clean draft; apply a correction and re-check; else escalate."""
        compliance = self.state.compliance
        if compliance is None:
            return "needs_human"

        if compliance.passed:
            # Adopt the corrected text if the checker cleaned it up on this pass.
            if compliance.revised_body:
                self.state.draft.body = compliance.revised_body
            return "send"

        # Not passed: if the checker supplied a correction and we still have
        # retries left, apply it and re-run the check on the revised draft.
        if (
            compliance.revised_body
            and self.state.compliance_attempts < MAX_COMPLIANCE_ATTEMPTS
        ):
            self.state.draft.body = compliance.revised_body
            self.state.compliance_attempts += 1
            return "revise_and_recheck"

        return "needs_human"

    @listen("send")
    def auto_send(self):
        """Send the (compliance-approved) draft without human review."""
        self.state.final_status = TicketStatus.AUTO_SENT
        print(f"[auto_sent] {self.state.draft.body}")
        return self.state

    @listen("needs_human")
    def escalate_to_human(self):
        """Park the ticket in the human review queue."""
        self.state.final_status = TicketStatus.NEEDS_REVIEW
        print(f"[needs_review] triage={self.state.triage}")
        return self.state
