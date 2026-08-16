from pydantic import BaseModel, Field
from enum import Enum

class TicketCategory(str, Enum):
    ACCOUNT = "account"
    BILLING = "billing"
    BUG = "bug"
    HOW_TO = "how_to"
    OTHER = "other"

class TicketStatus(Enum):
    AUTO_SENT = "auto_sent"
    ESCALATED = "escalated"
    NEEDS_REVIEW = "needs_review"

class TriageResult(BaseModel): 
    category: TicketCategory = Field(description="Ticket queue category")
    urgency: int = Field(description="The urgency of the ticket with 1 being highest priority and 5 being lowest")
    summary: str = Field(description="Summary of the ticket and reasoning of why it was triaged in the way it was")
    requires_human: bool = Field(description="Does the ticket require a human to review it before a response is sent")

class DraftResponse(BaseModel):
    body: str = Field(description="The body of the response to the ticket")
    confidence: float = Field(description="Confidence that this response will fully resolve the ticket")
    cited_kb_articles: list[str] = Field(description="List of Knowbase Articles cited to resolve this issue")

class ComplianceCheck(BaseModel):
    passed: bool = Field(description="Did the draft response pass all compliance checks?")
    issues: list[str] = Field(description="A list of any issues the complinace check found. Should be empty if the compliance check found no issues")
    revised_body: str | None = Field(description="Any changes to the response body as determined by the compliance check.")

class TicketState(BaseModel):
    ticket_text: str = Field(default="", description="The request body of the ticket")
    triage: TriageResult | None = Field(default=None, description="Result of the triage agent")
    draft: DraftResponse | None = Field(default=None, description="Result of the specialist agent")
    compliance: ComplianceCheck | None = Field(default=None, description="Result of the compliance check agent")
    final_status: TicketStatus = Field(default=TicketStatus.NEEDS_REVIEW, description="The ticket's status once it exits the flow")