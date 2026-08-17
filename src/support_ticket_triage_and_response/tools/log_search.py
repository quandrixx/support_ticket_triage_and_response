"""Fixture-backed log-search tool for the Production Investigator agent.

Simulates querying a centralised logging system (e.g. an ELK/Datadog log
backend). Searches the bundled ``fixtures/logs.json`` with the shared
keyword-overlap scorer so the agent can ground the dossier in concrete log
lines without any external service.
"""

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from support_ticket_triage_and_response.tools.fixture_search import (
    keyword_search,
    load_fixture,
)

_LOG_FILE = "logs.json"
_WEIGHTED_FIELDS = {"tags": 4.0, "message": 2.0, "service": 3.0}


class LogSearchInput(BaseModel):
    query: str = Field(
        ...,
        description="Keywords or a short description of the issue to search "
        "production logs for.",
    )
    service: str | None = Field(
        default=None,
        description="Optional service/component to scope the search to "
        "(e.g. analytics-dashboard, auth-service, billing-service).",
    )
    limit: int = Field(default=3, description="Maximum number of log entries to return.")


class LogSearchTool(BaseTool):
    name: str = "log_search"
    description: str = (
        "Search production application and error logs for entries relevant to a "
        "customer's issue. Returns each entry's id, service, level, timestamp, and "
        "message. Use it while investigating to ground the dossier in real logs."
    )
    args_schema: Type[BaseModel] = LogSearchInput

    def _run(self, query: str, service: str | None = None, limit: int = 3) -> str:
        results = keyword_search(
            load_fixture(_LOG_FILE),
            query,
            _WEIGHTED_FIELDS,
            limit=limit,
            filter_field="service" if service else None,
            filter_value=service,
        )
        if not results:
            return f"No log entries matched query {query!r}."
        blocks = [f"Found {len(results)} relevant log entr(ies):"]
        for r in results:
            blocks.append(
                f"\n[{r['id']}] {r['service']} {r.get('level', '').upper()} "
                f"@ {r.get('timestamp', 'n/a')}\n{r['message']}"
            )
        return "\n".join(blocks)
