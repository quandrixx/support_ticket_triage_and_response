"""Slack (Bolt / Socket Mode) integration for the investigation flow.

Two triggers converge on the same entry point ``start_investigation``:
  * a ``/triage`` slash command or an @mention in Slack, and
  * a new-ticket event (see ``main.on_ticket_created``).

Interaction is a single round-trip:
  1. ``start_investigation`` runs the intake crew, posts the ack + clarifying
     questions to a channel (opening a thread), and records the thread as
     pending.
  2. When the customer replies once in that thread, ``complete_investigation``
     runs ``InvestigationFlow`` and posts the sanitized reply back to the thread
     plus the full dossier + differential diagnosis to the engineer channel.

The Slack event loop owns the wait between the two steps; the flow itself is
synchronous. The pure functions below take an injected ``client`` so they can be
unit-tested without Slack or network access; ``build_app``/``run`` wire them to
Bolt.
"""

import json
import logging
import os
from pathlib import Path

from support_ticket_triage_and_response.crews.intake_crew.intake_crew import (
    kickoff_intake_crew,
)
from support_ticket_triage_and_response.flows.investigation_flow import (
    InvestigationFlow,
)

logger = logging.getLogger(__name__)

# Message subtypes that are edits/deletes/joins rather than a new user reply.
_IGNORED_MESSAGE_SUBTYPES = frozenset(
    {"message_changed", "message_deleted", "channel_join", "channel_leave", "bot_message"}
)


def _is_user_reply(event: dict) -> bool:
    """True only for a genuine human reply inside a thread.

    Allows a plain reply and a "also send to channel" reply (``thread_broadcast``)
    and file-share replies, but rejects the bot's own posts and edit/delete/join
    system messages.
    """
    if event.get("bot_id"):
        return False
    if event.get("subtype") in _IGNORED_MESSAGE_SUBTYPES:
        return False
    return bool(event.get("thread_ts"))


class PendingInvestigationStore:
    """Maps ``thread_ts`` -> {ticket_text, channel} for round-trips in flight.

    In-memory by default; pass a ``path`` to persist across bot restarts.
    """

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else None
        self._data: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    def _flush(self) -> None:
        if self.path:
            self.path.write_text(json.dumps(self._data), encoding="utf-8")

    def add(self, thread_ts: str, ticket_text: str, channel: str) -> None:
        self._data[thread_ts] = {"ticket_text": ticket_text, "channel": channel}
        self._flush()

    def get(self, thread_ts: str) -> dict | None:
        return self._data.get(thread_ts)

    def pop(self, thread_ts: str) -> dict | None:
        record = self._data.pop(thread_ts, None)
        self._flush()
        return record

    def __contains__(self, thread_ts: str) -> bool:
        return thread_ts in self._data


# --- Message formatting ----------------------------------------------------

def format_questions(questions: list[str]) -> str:
    intro = (
        ":mag: Thanks for the report — to investigate quickly, could you help us "
        "with a few details? Reply in this thread and we'll take it from there.\n"
    )
    if not questions:
        return intro + "\n(Reply with any additional detail about the issue.)"
    numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, start=1))
    return intro + "\n" + numbered


def format_dossier_and_diagnosis(state) -> str:
    """Render the internal dossier + differential diagnosis for engineers."""
    lines: list[str] = [":file_folder: *Investigation dossier*"]
    d = state.dossier
    if d:
        lines += [
            f"*Customer:* {d.customer_summary}",
            f"*Issue:* {d.issue_summary}",
            f"*Customer-provided details:* {d.collected_details}",
        ]
        if d.affected_components:
            lines.append(f"*Affected components:* {', '.join(d.affected_components)}")
        env = d.environment
        for label, items in (
            ("Logs", env.log_findings),
            ("Metrics", env.metric_findings),
            ("Incidents", env.incidents),
            ("Related tickets", env.related_tickets),
            ("Related Slack threads", env.related_slack_threads),
        ):
            if items:
                bullets = "\n".join(f"  • {it}" for it in items)
                lines.append(f"*{label}:*\n{bullets}")
        if d.timeline:
            lines.append("*Timeline:*\n" + "\n".join(f"  • {t}" for t in d.timeline))

    diag = state.diagnosis
    if diag:
        lines.append("\n:stethoscope: *Differential diagnosis*")
        lines.append(f"*Top recommendation:* {diag.top_recommendation}")
        for i, h in enumerate(diag.hypotheses, start=1):
            evidence = "; ".join(h.evidence) if h.evidence else "n/a"
            lines.append(
                f"{i}. *{h.cause}* (p={h.likelihood:.2f})\n"
                f"   Evidence: {evidence}\n"
                f"   Next: {h.recommended_action}"
            )
    return "\n".join(lines)


# --- Core logic (Slack-agnostic, injected client) --------------------------

def start_investigation(ticket_text: str, *, client, channel: str,
                        store: PendingInvestigationStore) -> str:
    """Phase 1: generate clarifying questions and open a thread. Returns thread_ts."""
    result = kickoff_intake_crew({"ticket_text": ticket_text})
    questions = result.pydantic.questions if result.pydantic else []
    posted = client.chat_postMessage(channel=channel, text=format_questions(questions))
    thread_ts = posted["ts"]
    store.add(thread_ts, ticket_text, channel)
    logger.info("opened investigation thread %s in channel %s (awaiting reply)", thread_ts, channel)
    return thread_ts


def complete_investigation(thread_ts: str, customer_details: str, *, client,
                           engineer_channel: str, store: PendingInvestigationStore):
    """Phase 2: run the flow, post sanitized reply to the thread + dossier to engineers."""
    pending = store.pop(thread_ts)
    if pending is None:
        return None

    flow = InvestigationFlow()
    flow.kickoff(
        inputs={"ticket_text": pending["ticket_text"], "customer_details": customer_details}
    )
    state = flow.state

    client.chat_postMessage(
        channel=pending["channel"],
        thread_ts=thread_ts,
        text=state.sanitized_reply,
    )
    client.chat_postMessage(
        channel=engineer_channel,
        text=format_dossier_and_diagnosis(state),
    )
    return state


# --- Bolt wiring -----------------------------------------------------------

def build_app(store: PendingInvestigationStore | None = None):
    """Construct the Bolt app with handlers wired to the core logic."""
    from slack_bolt import App

    app = App(token=os.environ["SLACK_BOT_TOKEN"])
    store = store or PendingInvestigationStore(os.environ.get("SLACK_PENDING_STORE"))
    default_channel = os.environ.get("SLACK_CUSTOMER_CHANNEL")
    engineer_channel = os.environ["SLACK_ENGINEER_CHANNEL"]

    @app.command("/triage")
    def _handle_triage(ack, command, client):
        ack()
        ticket_text = (command.get("text") or "").strip()
        channel = command.get("channel_id") or default_channel
        start_investigation(ticket_text, client=client, channel=channel, store=store)

    @app.event("app_mention")
    def _handle_mention(event, client):
        # Strip the leading "<@BOTID>" mention from the text.
        text = event.get("text", "")
        ticket_text = text.split(">", 1)[-1].strip() if ">" in text else text.strip()
        channel = event.get("channel") or default_channel
        start_investigation(ticket_text, client=client, channel=channel, store=store)

    @app.event("message")
    def _handle_message(event, client):
        # Only the customer's single reply inside a pending thread should resume.
        thread_ts = event.get("thread_ts")
        logger.info(
            "message event: channel=%s thread_ts=%s subtype=%s bot_id=%s pending=%s",
            event.get("channel"), thread_ts, event.get("subtype"),
            event.get("bot_id"), thread_ts in store if thread_ts else False,
        )
        if not _is_user_reply(event):
            return
        if thread_ts not in store:
            # A reply in some other thread we aren't tracking — ignore quietly.
            return
        try:
            complete_investigation(
                thread_ts,
                event.get("text", ""),
                client=client,
                engineer_channel=engineer_channel,
                store=store,
            )
        except Exception:  # noqa: BLE001 — surface flow/posting errors in the log
            logger.exception("investigation failed for thread %s", thread_ts)

    return app, store


def run():
    """Launch the Socket Mode listener (blocking)."""
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    logging.basicConfig(
        level=os.environ.get("SLACK_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app, _ = build_app()
    logger.info(
        "Slack app starting (Socket Mode). Watching for /triage, @mentions, and thread replies. "
        "If replies do nothing, confirm the 'message.channels' bot event is subscribed and the "
        "bot is a member of the channel."
    )
    SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"]).start()
