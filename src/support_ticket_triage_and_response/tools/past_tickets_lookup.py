"""Fixture-backed prior-ticket tool for the Production Investigator agent.

Reuses the existing ``sample_tickets_database.json`` as the corpus of prior
support tickets so the investigator can find similar past issues. Uses the
shared keyword-overlap scorer.
"""

import json
from functools import lru_cache
from importlib.resources import files
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from support_ticket_triage_and_response.tools.fixture_search import keyword_search

_PACKAGE = "support_ticket_triage_and_response"
_TICKETS_FILE = "sample_tickets_database.json"
_WEIGHTED_FIELDS = {"subject": 3.0, "text": 2.0, "expected_category": 3.0}


@lru_cache(maxsize=1)
def _load_tickets() -> list[dict]:
    raw = files(_PACKAGE).joinpath(_TICKETS_FILE).read_text(encoding="utf-8")
    return json.loads(raw)


class PastTicketsInput(BaseModel):
    query: str = Field(
        ...,
        description="Keywords or a short description of the issue to search prior "
        "support tickets for.",
    )
    category: str | None = Field(
        default=None,
        description="Optional category to scope to: billing, bug, how_to, account, other.",
    )
    limit: int = Field(default=3, description="Maximum number of tickets to return.")


class PastTicketsTool(BaseTool):
    name: str = "past_tickets_lookup"
    description: str = (
        "Search prior support tickets for issues similar to the current one. "
        "Returns each ticket's id, subject, requester, category, and body. Use it "
        "to spot recurring problems and prior resolutions."
    )
    args_schema: Type[BaseModel] = PastTicketsInput

    def _run(self, query: str, category: str | None = None, limit: int = 3) -> str:
        results = keyword_search(
            _load_tickets(),
            query,
            _WEIGHTED_FIELDS,
            limit=limit,
            filter_field="expected_category" if category else None,
            filter_value=category,
        )
        if not results:
            return f"No prior tickets matched query {query!r}."
        blocks = [f"Found {len(results)} relevant prior ticket(s):"]
        for r in results:
            blocks.append(
                f"\n[{r['id']}] {r.get('subject', '')} "
                f"(category: {r.get('expected_category', 'n/a')}, "
                f"from: {r.get('name', 'n/a')})\n{r.get('text', '')}"
            )
        return "\n".join(blocks)
