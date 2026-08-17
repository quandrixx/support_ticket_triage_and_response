#!/usr/bin/env python
import json
import sys
from pathlib import Path

from support_ticket_triage_and_response.flows.support_ticket_flow import (
    SupportTicketFlow,
)
from support_ticket_triage_and_response.models import TicketState

SAMPLE_TICKETS = Path(__file__).with_name("sample_tickets.json")


def _load_tickets() -> list[dict]:
    return json.loads(SAMPLE_TICKETS.read_text())


def _build_ticket_text(ticket: dict) -> str:
    # Combine the subject and body into a single prompt for the crews.
    subject = (ticket.get("subject") or "").strip()
    body = (ticket.get("text") or "").strip()
    return f"Subject: {subject}\n\n{body}" if subject else body


def run_ticket(ticket: dict) -> TicketState:
    flow = SupportTicketFlow()
    flow.kickoff(inputs={"ticket_text": _build_ticket_text(ticket)})
    return flow.state

def kickoff():
    """Run every sample ticket through the flow."""
    rows: list[tuple[dict, TicketState]] = []
    for ticket in _load_tickets():
        print(f"\n=== {ticket.get('id')} — {ticket.get('subject', '')} ===")
        rows.append((ticket, run_ticket(ticket)))
    _print_summary(rows)


def run_with_trigger():
    """Entry point for deployment triggers.

    Accepts a JSON payload as the first CLI argument — either a full ticket
    object ({"subject": ..., "text": ...}) or {"ticket_text": ...}.
    """
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    ticket_text = payload.get("ticket_text") or _build_ticket_text(payload)
    flow = SupportTicketFlow()
    flow.kickoff(inputs={"ticket_text": ticket_text})
    print(f"Final status: {flow.state.final_status.value}")


def plot():
    """Generate an interactive HTML diagram of the flow."""
    SupportTicketFlow().plot("support_ticket_flow")


if __name__ == "__main__":
    kickoff()
