"""Shared keyword-overlap search for the fixture-backed context tools.

The investigation tools (logs, metrics, incidents, prior Slack threads, prior
tickets) all search small bundled JSON fixtures the same way the KB lookup tool
searches ``kb_articles.json`` — a lightweight, deterministic keyword-overlap
score with no external services or embeddings. This module factors out the
tokenizing, scoring, and loading so each tool stays a thin wrapper.
"""

import json
import re
from functools import lru_cache
from importlib.resources import files

_PACKAGE = "support_ticket_triage_and_response"

# Common words that add noise to overlap scoring without signalling topic.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "you", "your", "are", "was", "this", "that",
        "have", "has", "not", "but", "can", "will", "from", "they", "them", "our",
        "out", "get", "got", "when", "what", "how", "why", "who", "into", "onto",
        "about", "after", "before", "over", "under", "does", "did", "new", "all",
        "any", "one", "please", "need", "want", "there", "their", "been", "would",
        "could", "should", "just", "some", "than", "then", "now", "still",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@lru_cache(maxsize=8)
def load_fixture(filename: str) -> list[dict]:
    """Load and cache a JSON fixture bundled under the ``fixtures/`` directory."""
    raw = files(_PACKAGE).joinpath("fixtures", filename).read_text(encoding="utf-8")
    return json.loads(raw)


def tokenize(text: str) -> set[str]:
    return {
        tok
        for tok in _TOKEN_RE.findall(text.lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    }


def _field_value(record: dict, field: str) -> object:
    return record.get(field)


def _score(record: dict, query_lower: str, query_tokens: set[str],
           weighted_fields: dict[str, float]) -> float:
    """Weighted token overlap across the record's searchable fields.

    List-valued fields (e.g. ``tags``) award a phrase-match bonus when a whole
    entry appears verbatim in the query, mirroring the KB lookup tool.
    """
    score = 0.0
    for field, weight in weighted_fields.items():
        val = _field_value(record, field)
        if val is None:
            continue
        if isinstance(val, list):
            for item in val:
                item_lower = str(item).lower()
                if item_lower and item_lower in query_lower:
                    score += weight + 2.0
                else:
                    score += weight * 0.5 * len(tokenize(str(item)) & query_tokens)
        else:
            score += weight * len(tokenize(str(val)) & query_tokens)
    return score


def keyword_search(
    records: list[dict],
    query: str,
    weighted_fields: dict[str, float],
    limit: int = 3,
    filter_field: str | None = None,
    filter_value: str | None = None,
) -> list[dict]:
    """Return up to ``limit`` records ranked by weighted keyword overlap.

    When ``filter_field``/``filter_value`` are given, the search is scoped to
    matching records but falls back to the full set if the filter empties it,
    matching the KB lookup tool's broaden-on-empty behaviour.
    """
    if filter_field and filter_value:
        wanted = filter_value.strip().lower()
        scoped = [
            r for r in records
            if str(r.get(filter_field, "")).strip().lower() == wanted
        ]
        candidates = scoped or records
    else:
        candidates = records

    query_lower = query.lower()
    query_tokens = tokenize(query)

    scored = [
        (s, r)
        for r in candidates
        if (s := _score(r, query_lower, query_tokens, weighted_fields)) > 0
    ]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [r for _, r in scored[: max(1, limit)]]
