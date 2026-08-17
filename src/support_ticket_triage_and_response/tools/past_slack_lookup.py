"""Fixture-backed prior-Slack-thread tool for the Production Investigator agent.

Simulates searching past Slack incident/support threads for prior art. Searches
the bundled ``fixtures/slack_threads.json`` with the shared keyword-overlap
scorer.
"""

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from support_ticket_triage_and_response.tools.fixture_search import (
    keyword_search,
    load_fixture,
)

_SLACK_FILE = "slack_threads.json"
_WEIGHTED_FIELDS = {"tags": 4.0, "title": 3.0, "summary": 2.0, "resolution": 1.5}


class PastSlackInput(BaseModel):
    query: str = Field(
        ...,
        description="Keywords or a short description of the issue to search prior "
        "Slack threads for.",
    )
    limit: int = Field(default=3, description="Maximum number of threads to return.")


class PastSlackTool(BaseTool):
    name: str = "past_slack_lookup"
    description: str = (
        "Search prior Slack incident/support threads for related discussions and "
        "how they were resolved. Returns each thread's id, channel, title, summary, "
        "and resolution. Use it to reuse prior investigations."
    )
    args_schema: Type[BaseModel] = PastSlackInput

    def _run(self, query: str, limit: int = 3) -> str:
        results = keyword_search(
            load_fixture(_SLACK_FILE), query, _WEIGHTED_FIELDS, limit=limit
        )
        if not results:
            return f"No prior Slack threads matched query {query!r}."
        blocks = [f"Found {len(results)} relevant prior Slack thread(s):"]
        for r in results:
            blocks.append(
                f"\n[{r['id']}] {r.get('channel', '')} — {r['title']}\n"
                f"{r['summary']}\nResolution: {r.get('resolution', 'n/a')}"
            )
        return "\n".join(blocks)
