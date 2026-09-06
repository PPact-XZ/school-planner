"""Reminder due-logic and the run loop (Decision 2).

Pure Python: no Flask, no Firestore. `today` and `clock` are parameters, so the
due computation is a total function of the date handed to it and needs no clock
mocking anywhere.

The protocol is **never delete**. A ledger doc is created to claim a task,
the send is attempted, and the doc is updated with the outcome either way. The
earlier "delete the doc if SMTP fails" design was wrong in both directions —
it re-enabled the double-send that `create()` exists to prevent, and it could
lose a reminder permanently — so nothing here may ever remove a doc.

Delivery guarantee, stated honestly: **at-most-once**.

Two failure classes are deliberately kept apart, because the endpoint's retry
contract depends on the difference:

  per-task failure (no address, SMTP refused)  -> counted, loop continues, 200
  infrastructure failure (Firestore unreachable) -> propagates, route maps 503

Swallowing the second into the first is what would make `curl --retry`
decorative, so there is no broad `except` around the loop body.
"""

import logging
import time
from datetime import date, datetime, timedelta, timezone

from google.api_core.exceptions import Conflict

from app.reminders.mailer import SendError, TransientSendError

log = logging.getLogger(__name__)

MAX_SEND_ATTEMPTS = 3
# Waits between attempts 1->2 and 2->3. len() is MAX_SEND_ATTEMPTS - 1 by
# construction; the whole worst case is bounded so the job stays well inside
# gunicorn's --timeout 120 (§8): 3 attempts x 20s SMTP timeout + 3s backoff.
BACKOFF_SECONDS = (1, 2)

SUBJECT_TEMPLATE = "เตือนความจำ: {title}"
BODY_TEMPLATE = """สวัสดี

พรุ่งนี้ถึงกำหนดส่งงาน "{title}"
วิชา: {course}
กำหนดส่ง: {deadline}

เปิดดูรายละเอียดได้ที่ School Planner
"""


def due_deadline(today: date) -> str:
    """The deadline value that is due for a run on `today` — tomorrow.

    Returns the same zero-padded "%Y-%m-%d" shape parse_ymd stores, because
    the Firestore query is an equality filter: a differently formatted string
    here matches nothing at all, silently.
    """
    return (today + timedelta(days=1)).strftime("%Y-%m-%d")


def ledger_id(deadline: str, task_id: str) -> str:
    return f"{deadline}_{task_id}"


def _one_line(value) -> str:
    """Collapse all whitespace, including CR/LF.

    clean_str already rejects control characters at the API boundary, but a doc
    edited directly in the Firestore console never passed through it. A raw CRLF
    in a header would make EmailMessage raise ValueError — which is not a
    SendError, so it would escape the per-task guard and abort every other
    user's reminder for the day.
    """
    return " ".join(str(value).split())


def build_message(task: dict) -> tuple[str, str]:
    """(subject, body) for one due task. Total: a task missing any field still
    produces a sendable message rather than raising inside the loop."""
    title = _one_line(task.get("title") or "งานที่ยังไม่ส่ง")
    course = _one_line(task.get("subject") or "-")
    deadline = _one_line(task.get("deadline") or "-")
    return (
        SUBJECT_TEMPLATE.format(title=title),
        BODY_TEMPLATE.format(title=title, course=course, deadline=deadline),
    )


def _resolve_emails(directory, uids) -> dict:
    """One directory lookup per user per day (Decision 2) — never per task.

    The broad except is deliberate and contained: FirebaseUserDirectory catches
    only UserNotFoundError, so a network blip or a malformed uid surfaces here
    as a live exception. Letting it out would abort every other user's reminder
    over one user's lookup. Logs the uid only, never the address.
    """
    resolved = {}
    for uid in uids:
        try:
            resolved[uid] = directory.get_email(uid)
        except Exception as err:  # noqa: BLE001 - see docstring
            log.warning(
                "reminder: email lookup failed uid=%s error=%s", uid, type(err).__name__
            )
            resolved[uid] = None
    return resolved


def _send_with_retry(mailer, to: str, subject: str, body: str, sleep) -> tuple[int, Exception | None]:
    """Returns (attempts_made, error_or_None). Permanent failures return
    immediately — retrying bad credentials or a refused address cannot help and
    only burns the request's time budget."""
    last_error = None
    for attempt in range(1, MAX_SEND_ATTEMPTS + 1):
        try:
            mailer.send(to, subject, body)
            return attempt, None
        except SendError as err:
            last_error = err
            if not isinstance(err, TransientSendError):
                return attempt, err
            if attempt < MAX_SEND_ATTEMPTS:
                sleep(BACKOFF_SECONDS[attempt - 1])
    return MAX_SEND_ATTEMPTS, last_error


def _process_one(task, deadline, emails, log_repo, mailer, clock, sleep) -> str:
    """One task: claim, send, record. Returns "sent" | "skipped" | "failed"."""
    task_id = task.get("id") or ""
    uid = task.get("user_id")
    to = emails.get(uid)

    if not to:
        # No ledger doc on purpose. Claiming a task we cannot even attempt
        # would burn its at-most-once slot forever: tomorrow the deadline no
        # longer matches, so nothing would ever retry it.
        log.warning("reminder: no address for uid=%s task=%s", uid, task_id)
        return "failed"

    doc_id = ledger_id(deadline, task_id)
    try:
        log_repo.create(
            doc_id, {"status": "sending", "attempts": 0, "claimed_at": clock()}
        )
    except Conflict:
        # Already claimed by an earlier run or a concurrent trigger. This is
        # the mutual exclusion that makes curl --retry safe.
        log.info("reminder: already claimed doc=%s", doc_id)
        return "skipped"

    subject, body = build_message(task)
    attempts, error = _send_with_retry(mailer, to, subject, body, sleep)
    status = "failed" if error else "sent"

    # ALWAYS update, NEVER delete.
    log_repo.update(
        doc_id, {"status": status, "attempts": attempts, "finished_at": clock()}
    )

    if error:
        # type name only: SMTPRecipientsRefused carries the address in its
        # message and §8 forbids logging addresses.
        log.warning(
            "reminder: send failed task=%s attempts=%d error=%s",
            task_id,
            attempts,
            type(error).__name__,
        )
        return "failed"
    return "sent"


def run_reminders(
    *,
    task_query,
    users_repo,
    log_repo,
    mailer,
    directory,
    today: date,
    clock=None,
    sleep=time.sleep,
) -> dict:
    """Run one reminder job. Returns {"due","sent","skipped","failed"}, where
    due == sent + skipped + failed (the three are a partition of the due set).

    Raises on infrastructure failure so the route can answer 503.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    deadline = due_deadline(today)

    candidates = task_query.list_due(deadline)
    if not candidates:
        return {"due": 0, "sent": 0, "skipped": 0, "failed": 0}

    owner_uids = {t.get("user_id") for t in candidates if t.get("user_id")}
    users = users_repo.get_many(sorted(owner_uids))
    notify_uids = {
        uid for uid, doc in users.items() if doc.get("notify_enabled") is True
    }

    # A task whose owner has notifications off, or has no users doc at all, is
    # not due — it is never claimed, so turning the toggle back on tomorrow is
    # not poisoned by a stale ledger entry.
    due = [t for t in candidates if t.get("user_id") in notify_uids]
    due.sort(key=lambda t: t.get("id") or "")  # stable across runs and tests

    emails = _resolve_emails(directory, sorted({t["user_id"] for t in due}))

    tally = {"sent": 0, "skipped": 0, "failed": 0}
    for task in due:
        outcome = _process_one(task, deadline, emails, log_repo, mailer, clock, sleep)
        tally[outcome] += 1

    counts = {"due": len(due), **tally}
    log.info(
        "reminder run complete deadline=%s due=%d sent=%d skipped=%d failed=%d",
        deadline,
        counts["due"],
        counts["sent"],
        counts["skipped"],
        counts["failed"],
    )
    return counts
