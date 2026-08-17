"""Local re-export shim for this crew's JSON config.

CrewAI's JSON loader resolves ``{"python": "..."}`` references relative to this
crew's directory and requires the target file to live under it, so the package's
shared models are re-exported here. Keep the definitions in
``support_ticket_triage_and_response.models``; this file only forwards them.
"""

from support_ticket_triage_and_response.models import ComplianceCheck

__all__ = ["ComplianceCheck"]
