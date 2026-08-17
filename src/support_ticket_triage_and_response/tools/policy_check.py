"""Deterministic, rule-based policy check for the Compliance Checker agent.

Runs four static checks over a draft response:
  1. Refund promises made without approval
  2. Profanity
  3. PII leakage (email, phone, SSN, credit-card numbers)
  4. Missing the required support disclaimer

Returns a plain-text report the agent maps into a ComplianceCheck. The rules
below (profanity list, disclaimer markers, allowed email domains) are meant to
be tuned to a organisation's actual policy.
"""

import re
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# --- Refund promises -------------------------------------------------------
# Assertive commitments to refund/reimburse/credit the customer. Applied per
# sentence and suppressed when the sentence also contains a negation cue.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NEGATION = re.compile(
    r"\b(?:cannot|can'?t|could\s*n'?t|unable|not\s+able|won'?t|will\s+not|"
    r"do(?:es)?\s*n'?t|is\s*n'?t|are\s*n'?t|no\s+refund|without\s+approval)\b",
    re.I,
)
_REFUND_PROMISE = [
    re.compile(
        r"\b(?:we|i)\s+(?:will|'ll|are going to|are gonna|hereby|have|'ve)\s+"
        r"(?:\w+\s+){0,4}?(?:refund|reimburse|credit)(?:ed)?\b",
        re.I,
    ),
    re.compile(
        r"\byou\s+(?:will|'ll|are going to|are gonna)\s+(?:\w+\s+){0,4}?"
        r"(?:be\s+)?(?:refunded|reimbursed|credited)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:full\s+|partial\s+|a\s+|your\s+|the\s+)?refund\s+"
        r"(?:will\s+be|has\s+been|have\s+been|is\s+being|is\s+going\s+to\s+be)\s+"
        r"(?:issued|processed|approved|sent|initiated|given|applied)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:issue|process|send|provide|grant|approve|initiate|give)\s+"
        r"(?:you\s+)?(?:a\s+|the\s+|your\s+|full\s+|partial\s+)?refund\b",
        re.I,
    ),
    re.compile(r"\bwe(?:'ve| have)\s+(?:already\s+)?(?:refunded|reimbursed|credited)\b", re.I),
]

# --- Profanity -------------------------------------------------------------
_PROFANITY = frozenset(
    {
        "fuck", "fucking", "fucked", "shit", "shitty", "bullshit", "bitch",
        "bastard", "asshole", "ass", "dick", "piss", "crap", "damn", "goddamn",
        "dumbass", "jackass", "prick", "cunt", "screwed",
    }
)
_PROFANITY_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in sorted(_PROFANITY)) + r")\b", re.I
)

# --- PII -------------------------------------------------------------------
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_CANDIDATE_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")

# Email domains that are safe to appear in a reply (e.g. your own support inbox).
_ALLOWED_EMAIL_DOMAINS = frozenset({"example.com"})

# --- Disclaimer ------------------------------------------------------------
# At least one of these must appear for the response to satisfy the required
# "how to reach a human" disclaimer. Tune to your real disclaimer text.
_DISCLAIMER_MARKERS = (
    "reply to this",
    "contact support",
    "contact our support",
    "reach out to",
    "human agent",
    "support team",
)


def _luhn_ok(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _mask(value: str) -> str:
    v = value.strip()
    if len(v) <= 4:
        return "*" * len(v)
    return f"{v[:2]}{'*' * (len(v) - 4)}{v[-2:]}"


def _check_refund_promises(body: str, refund_preapproved: bool) -> list[str]:
    if refund_preapproved:
        return []
    issues: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(body):
        if _NEGATION.search(sentence):
            continue
        if any(p.search(sentence) for p in _REFUND_PROMISE):
            issues.append(
                "[refund_promise] Promises a refund/credit without approval — "
                "refund commitments require human sign-off. Found: "
                f'"{sentence.strip()}"'
            )
    return issues


def _check_profanity(body: str) -> list[str]:
    found = {m.group(1).lower() for m in _PROFANITY_RE.finditer(body)}
    if found:
        return [f"[profanity] Contains profanity: {', '.join(sorted(found))}."]
    return []


def _check_pii(body: str) -> list[str]:
    issues: list[str] = []

    for m in _EMAIL_RE.finditer(body):
        domain = m.group(0).rsplit("@", 1)[-1].lower()
        if domain not in _ALLOWED_EMAIL_DOMAINS:
            issues.append(f"[pii:email] Possible email address: {_mask(m.group(0))}")

    for m in _SSN_RE.finditer(body):
        issues.append(f"[pii:ssn] Possible SSN: {_mask(m.group(0))}")

    for m in _PHONE_RE.finditer(body):
        issues.append(f"[pii:phone] Possible phone number: {_mask(m.group(0))}")

    for m in _CARD_CANDIDATE_RE.finditer(body):
        digits = re.sub(r"\D", "", m.group(0))
        if _luhn_ok(digits):
            issues.append(f"[pii:card] Possible payment card number: {_mask(digits)}")

    return issues


def _check_disclaimer(body: str) -> list[str]:
    lowered = body.lower()
    if any(marker in lowered for marker in _DISCLAIMER_MARKERS):
        return []
    return [
        "[missing_disclaimer] Required support disclaimer is missing — the "
        "response should tell the customer how to reach a human (e.g. "
        "'reply to this message' or 'contact support')."
    ]


class PolicyCheckInput(BaseModel):
    """Input schema for the policy check tool."""

    draft_body: str = Field(
        ..., description="The full text of the draft response to check."
    )
    refund_preapproved: bool = Field(
        default=False,
        description="Set true only if a refund has already been approved by a "
        "human; otherwise refund promises are flagged.",
    )


class PolicyCheckTool(BaseTool):
    name: str = "policy_check"
    description: str = (
        "Run deterministic, rule-based policy checks on a draft support response. "
        "Detects refund promises made without approval, profanity, PII leakage "
        "(email, phone, SSN, payment card), and a missing required disclaimer. "
        "Returns PASS or an itemised list of violations. This is authoritative for "
        "policy — trust its findings over your own judgement."
    )
    args_schema: Type[BaseModel] = PolicyCheckInput

    def _run(self, draft_body: str, refund_preapproved: bool = False) -> str:
        issues: list[str] = []
        issues += _check_refund_promises(draft_body, refund_preapproved)
        issues += _check_profanity(draft_body)
        issues += _check_pii(draft_body)
        issues += _check_disclaimer(draft_body)

        if not issues:
            return (
                "POLICY CHECK PASSED — no violations found across refund-promise, "
                "profanity, PII, and disclaimer rules."
            )

        lines = [f"POLICY CHECK FAILED — {len(issues)} issue(s):"]
        lines += [f"{i}. {issue}" for i, issue in enumerate(issues, start=1)]
        return "\n".join(lines)
