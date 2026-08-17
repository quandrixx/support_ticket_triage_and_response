"""Fixture-backed metrics/monitoring tool for the Production Investigator agent.

Simulates querying a monitoring system (e.g. Datadog/Grafana). Searches the
bundled ``fixtures/metrics.json`` with the shared keyword-overlap scorer.
"""

from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from support_ticket_triage_and_response.tools.fixture_search import (
    keyword_search,
    load_fixture,
)

_METRICS_FILE = "metrics.json"
_WEIGHTED_FIELDS = {"tags": 4.0, "summary": 2.0, "metric": 3.0, "service": 3.0}


class MetricsLookupInput(BaseModel):
    query: str = Field(
        ...,
        description="Keywords or a short description of the issue to search "
        "monitoring metrics for.",
    )
    service: str | None = Field(
        default=None,
        description="Optional service/component to scope the search to.",
    )
    limit: int = Field(default=3, description="Maximum number of metric findings to return.")


class MetricsLookupTool(BaseTool):
    name: str = "metrics_lookup"
    description: str = (
        "Search monitoring/metrics for anomalies relevant to a customer's issue "
        "(latency, error rates, saturation). Returns each finding's id, service, "
        "metric, timestamp, and a summary. Use it to corroborate the dossier."
    )
    args_schema: Type[BaseModel] = MetricsLookupInput

    def _run(self, query: str, service: str | None = None, limit: int = 3) -> str:
        results = keyword_search(
            load_fixture(_METRICS_FILE),
            query,
            _WEIGHTED_FIELDS,
            limit=limit,
            filter_field="service" if service else None,
            filter_value=service,
        )
        if not results:
            return f"No metric findings matched query {query!r}."
        blocks = [f"Found {len(results)} relevant metric finding(s):"]
        for r in results:
            blocks.append(
                f"\n[{r['id']}] {r['service']} — {r.get('metric', 'n/a')} "
                f"@ {r.get('timestamp', 'n/a')}\n{r['summary']}"
            )
        return "\n".join(blocks)
