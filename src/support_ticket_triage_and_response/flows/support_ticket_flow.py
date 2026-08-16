from crewai.flow.flow import Flow, listen, router, start

from support_ticket_triage_and_response.crews.response_crew.response_crew import (
    kickoff_response_crew,
)
from support_ticket_triage_and_response.crews.triage_crew.triage_crew import (
    kickoff_triage_crew,
)
from support_ticket_triage_and_response.models import TicketState, TicketStatus


class SupportTicketFlow(Flow[TicketState]):
    """Triage an incoming support ticket and draft an initial response.

    Pipeline:
        triage -> (auto_respond | needs_human)
        auto_respond -> draft + compliance -> (send | needs_human)
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
        """Draft a reply and run it through the compliance check."""
        result = kickoff_response_crew(
            {
                "ticket_text": self.state.ticket_text,
                "category": self.state.triage.category.value,
                "triage_summary": self.state.triage.summary,
            }
        )
        # The response crew runs draft_response_task then compliance_check_task,
        # so the crew's final output is the compliance check and the first task
        # output is the draft.
        self.state.compliance = result.pydantic
        self.state.draft = result.tasks_output[0].pydantic

    @router(draft_response)
    def route_after_draft(self):
        """Only auto-send a draft that cleared compliance."""
        if self.state.compliance is not None and self.state.compliance.passed:
            return "send"
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
