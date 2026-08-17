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
    compliance_attempts: int = Field(default=0, description="How many times the draft has been revised and re-checked for compliance")
    final_status: TicketStatus = Field(default=TicketStatus.NEEDS_REVIEW, description="The ticket's status once it exits the flow")


# --- Investigation flow models -------------------------------------------------
# These support the Slack-invokable InvestigationFlow that builds an internal
# dossier and differential diagnosis for support engineers and returns a
# sanitized reply to the customer.

class ClarifyingQuestions(BaseModel):
    questions: list[str] = Field(
        default_factory=list,
        description="Targeted, minimal questions to ask the customer to gather the "
        "detail needed to investigate the ticket.",
    )


class EnvironmentContext(BaseModel):
    log_findings: list[str] = Field(default_factory=list, description="Relevant application/error log summaries")
    metric_findings: list[str] = Field(default_factory=list, description="Relevant monitoring/metric summaries")
    related_tickets: list[str] = Field(default_factory=list, description="Summaries of prior related support tickets")
    related_slack_threads: list[str] = Field(default_factory=list, description="Summaries of prior related Slack threads")
    incidents: list[str] = Field(default_factory=list, description="Active or recent incidents/alerts relevant to the issue")


class Dossier(BaseModel):
    customer_summary: str = Field(description="Who the customer is and account context")
    issue_summary: str = Field(description="Concise statement of the reported issue")
    collected_details: str = Field(description="Additional details the customer provided in the Slack thread")
    environment: EnvironmentContext = Field(description="Current state gathered from production systems")
    timeline: list[str] = Field(default_factory=list, description="Ordered timeline of relevant events")
    affected_components: list[str] = Field(default_factory=list, description="Systems/components implicated in the issue")


class Hypothesis(BaseModel):
    cause: str = Field(description="A candidate root cause for the issue")
    likelihood: float = Field(description="Estimated likelihood this is the cause (0-1)")
    evidence: list[str] = Field(default_factory=list, description="Evidence from the dossier supporting this hypothesis")
    recommended_action: str = Field(description="What an engineer should do next to confirm or resolve this")


class DifferentialDiagnosis(BaseModel):
    hypotheses: list[Hypothesis] = Field(default_factory=list, description="Ranked candidate root causes")
    top_recommendation: str = Field(description="The single most important next step for the engineers")


class InvestigationState(BaseModel):
    ticket_text: str = Field(default="", description="Combined subject + body of the ticket")
    customer_details: str = Field(default="", description="Consolidated extra detail the customer supplied in Slack")
    triage: TriageResult | None = Field(default=None, description="Result of the triage crew")
    dossier: Dossier | None = Field(default=None, description="Synthesized investigation dossier")
    diagnosis: DifferentialDiagnosis | None = Field(default=None, description="Differential diagnosis for engineers")
    customer_reply: DraftResponse | None = Field(default=None, description="Draft customer-facing reply before sanitization")
    sanitized: ComplianceCheck | None = Field(default=None, description="Compliance/sanitization result for the customer reply")
    sanitized_reply: str = Field(default="", description="Final sanitized reply sent to the customer")