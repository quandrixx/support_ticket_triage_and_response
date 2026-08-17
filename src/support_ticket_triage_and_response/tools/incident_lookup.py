"""Fixture-backed incident/alert tool for the Production Investigator agent.

Simulates querying an incident manager / status page (e.g. PagerDuty). Searches
the bundled ``fixtures/incidents.json`` with the shared keyword-overlap scorer.
"""

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from support_ticket_triage_and_response.tools.fixture_search import (
    keyword_search,
    load_fixture,
)

_INCIDENTS_FILE = "incidents.json"
_WEIGHTED_FIELDS = {"tags": 4.0, "title": 3.0, "summary": 2.0, "component": 3.0}


class IncidentLookupInput(BaseModel):
    query: str = Field(
        ...,
        description="Keywords or a short description of the issue to search "
        "active and recent incidents for.",
    )
    component: str | None = Field(
        default=None,
        description="Optional component to scope the search to.",
    )
    limit: int = Field(default=3, description="Maximum number of incidents to return.")


class IncidentLookupTool(BaseTool):
    name: str = "incident_lookup"
    description: str = (
        "Search active and recent incidents/alerts relevant to a customer's issue. "
        "Returns each incident's id, title, status, severity, component, and "
        "summary. Use it to see whether the issue is a known ongoing incident."
    )
    args_schema: Type[BaseModel] = IncidentLookupInput

    def _run(self, query: str, component: str | None = None, limit: int = 3) -> str:
        results = keyword_search(
            load_fixture(_INCIDENTS_FILE),
            query,
            _WEIGHTED_FIELDS,
            limit=limit,
            filter_field="component" if component else None,
            filter_value=component,
        )
        if not results:
            return f"No incidents matched query {query!r}."
        blocks = [f"Found {len(results)} relevant incident(s):"]
        for r in results:
            blocks.append(
                f"\n[{r['id']}] {r['title']} "
                f"({r.get('status', 'n/a')}, {r.get('severity', 'n/a')}, "
                f"{r.get('component', 'n/a')})\n{r['summary']}"
            )
        return "\n".join(blocks)
