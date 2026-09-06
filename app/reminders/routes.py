"""POST /internal/reminders/run — the daily reminder trigger (Decision 2).

HTTP only: authenticate the caller, compute "today" in Asia/Bangkok, call the
service, map the outcome to the response contract. No request body is read at
all, so there is no injection surface here — the only input is one header.

`/internal/` is a naming convention, NOT a security boundary: this path is on
the public internet exactly like every other route. The shared-secret token is
the whole guard, which is why it fails closed on an unconfigured deployment.

Response contract (§ Decision 2) — the point of it is that `curl --retry`
retries exactly the case a retry can fix:

  200  {"due","sent","skipped","failed"}   job completed (per-task failures included)
  503  {"error": "job_incomplete"}          job never started or died mid-loop — RETRY
  401  {"error": "unauthorized"}            bad or missing token
"""

import hmac
import logging
from datetime import datetime
from functools import wraps
from zoneinfo import ZoneInfo

from flask import Blueprint, current_app, jsonify, request

from app.reminders.service import run_reminders
from app.security import limiter

bp = Blueprint("reminders", __name__)

log = logging.getLogger(__name__)

# Decision 2: 06:00 Asia/Bangkok. zoneinfo reads the OS tz database, which slim
# Linux images omit — `tzdata` is a pinned runtime dependency for this line.
TIMEZONE = ZoneInfo("Asia/Bangkok")
TOKEN_HEADER = "X-Reminder-Token"
# secrets.token_hex(32) is 64 chars; 32 is a floor that still rejects a
# human-chosen string without dictating the encoding.
MIN_TOKEN_LENGTH = 32


def _token_matches(presented: str, configured: str) -> bool:
    """Constant-time compare that fails closed on an absent or weak secret.

    Without the length floor, an unconfigured deployment would compare "" to ""
    and authorise every caller — the endpoint would stand wide open precisely
    when nobody had configured it. Same fail-closed shape as security.py's
    CSRF check (`if not expected or not compare_digest(...)`).
    """
    if len(configured) < MIN_TOKEN_LENGTH:
        return False
    return hmac.compare_digest(presented, configured)


def _presented_token_is_valid() -> bool:
    config = current_app.extensions["app_config"]
    return _token_matches(
        request.headers.get(TOKEN_HEADER, ""), config.reminder_trigger_token
    )


def token_required(view):
    """Guards /internal/*. Stamps a marker the url_map meta-test reads, so a
    future internal route that forgets this decorator fails the build rather
    than shipping unauthenticated (mirrors api_login_required's pattern)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _presented_token_is_valid():
            # Never log the presented value — a near-miss in the logs is a
            # gift to anyone who can read them.
            log.warning("reminder trigger rejected: bad or missing token")
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)

    wrapper.is_token_guarded = True
    return wrapper


@bp.post("/internal/reminders/run")
# exempt_when: a caller holding the real token is never counted or blocked, so
# a delayed GitHub run retrying legitimately can't rate-limit itself out. Only
# junk consumes the bucket.
@limiter.limit("20/hour", exempt_when=_presented_token_is_valid)
@token_required
def run():
    config = current_app.extensions["app_config"]
    deps = current_app.extensions["deps"]

    if not (config.resend_api_key and config.resend_from_email):
        # 503 BEFORE the service runs, deliberately. If we let the job proceed,
        # every due task would be claimed in the ledger and then fail to send —
        # and since the ledger never deletes and the due window is one day,
        # those reminders would be permanently lost to a config typo.
        log.error("reminder run aborted: Resend is not configured")
        return jsonify({"error": "job_incomplete"}), 503

    try:
        counts = run_reminders(
            task_query=deps.reminder_task_query,
            users_repo=deps.users_repo,
            log_repo=deps.reminder_log_repo,
            mailer=deps.mailer,
            directory=deps.user_directory,
            today=datetime.now(TIMEZONE).date(),
        )
    except Exception:
        # Infrastructure failure: unprocessed tasks have no ledger entry, so a
        # retry genuinely finishes the job while processed ones skip. Per-task
        # send failures never reach here — the service counts them and returns
        # 200, because retrying those changes nothing.
        log.exception("reminder run incomplete")
        return jsonify({"error": "job_incomplete"}), 503

    return jsonify(counts), 200
