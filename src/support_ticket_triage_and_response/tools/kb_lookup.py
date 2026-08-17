"""Knowledge-base lookup tool for the support Specialist agent.

Searches the bundled ``kb_articles.json`` with a lightweight keyword-overlap
score (no external services or embeddings) so the agent can ground its draft
responses in real documentation and cite article IDs.
"""

import json
import re
from functools import lru_cache
from importlib.resources import files
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

_PACKAGE = "support_ticket_triage_and_response"
_KB_FILE = "kb_articles.json"

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


@lru_cache(maxsize=1)
def _load_articles() -> list[dict]:
    """Load and cache the KB articles bundled with the package."""
    raw = files(_PACKAGE).joinpath(_KB_FILE).read_text(encoding="utf-8")
    return json.loads(raw)


def _tokenize(text: str) -> set[str]:
    return {
        tok
        for tok in _TOKEN_RE.findall(text.lower())
        if len(tok) > 2 and tok not in _STOPWORDS
    }


def _score(article: dict, query_lower: str, query_tokens: set[str]) -> float:
    """Weighted overlap: tags matter most, then title, then body."""
    score = 0.0
    for tag in article.get("tags", []):
        tag_lower = tag.lower()
        if tag_lower in query_lower:  # whole tag phrase appears in the query
            score += 5.0
        else:
            score += 2.0 * len(_tokenize(tag) & query_tokens)
    score += 2.0 * len(_tokenize(article.get("title", "")) & query_tokens)
    score += 1.0 * len(_tokenize(article.get("content", "")) & query_tokens)
    return score


class KBSearchInput(BaseModel):
    """Input schema for the KB lookup tool."""

    query: str = Field(
        ...,
        description="Keywords or a short description of the customer's issue to "
        "search the knowledge base for.",
    )
    category: str | None = Field(
        default=None,
        description="Optional category to prioritise: one of billing, bug, "
        "how_to, account, other. Falls back to all categories if nothing matches.",
    )
    limit: int = Field(
        default=3,
        description="Maximum number of articles to return (default 3).",
    )


class KBLookupTool(BaseTool):
    name: str = "kb_lookup"
    description: str = (
        "Search the internal support knowledge base for articles relevant to a "
        "customer's issue. Returns each matching article's KB id, title, category, "
        "and full content. Use it before drafting a response, and cite the "
        "returned KB ids (e.g. KB001) in your answer."
    )
    args_schema: Type[BaseModel] = KBSearchInput

    def _run(self, query: str, category: str | None = None, limit: int = 3) -> str:
        articles = _load_articles()

        if category:
            cat = category.strip().lower()
            filtered = [a for a in articles if a.get("category", "").lower() == cat]
            candidates = filtered or articles  # broaden if the category is empty
        else:
            candidates = articles

        query_lower = query.lower()
        query_tokens = _tokenize(query)

        scored = [
            (score, a)
            for a in candidates
            if (score := _score(a, query_lower, query_tokens)) > 0
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = scored[: max(1, limit)]

        if not top:
            return (
                f"No knowledge base articles matched query {query!r}. "
                "Draft a general response and flag that no KB article was found."
            )

        blocks = [f"Found {len(top)} relevant KB article(s):"]
        for _, a in top:
            blocks.append(
                f"\n[{a['id']}] {a['title']} ({a.get('category', 'n/a')})\n"
                f"{a['content']}"
            )
        return "\n".join(blocks)
