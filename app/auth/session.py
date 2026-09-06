"""Flask session guards + mutation helpers (ARCHITECTURE Decision 3, §6).

Two guards split by response type — a 302 on an expired `/api/*` session
makes `fetch` follow the redirect to HTML, and `response.json()` throws, so
the calendar renders blank with no error. `login_required` (HTML) 302s;
`api_login_required` (`/api/*`) always returns 401 JSON.

Session mutation (`start_session` / `clear_session`) lives here rather than
in auth/service.py so service.py stays pure Python with no Flask import — a
conscious deviation from ARCHITECTURE §3.2's file sketch, which named
auth/service.py as owning this; the guard/session logic is inherently
Flask-coupled and belongs with the guards it protects.
"""

import secrets
import time
from functools import wraps

from flask import current_app, jsonify, redirect, session, url_for

# Absolute cap (Decision 3) — NOT an idle timeout. Flask's
# SESSION_REFRESH_EACH_REQUEST defaults to True and would otherwise re-stamp
# cookie expiry on every request, making a "7 day" lifetime unbounded for an
# active user. SESSION_REFRESH_EACH_REQUEST=False (app/__init__.py) plus this
# server-side check is what makes 7 days true regardless of client behavior.
ABSOLUTE_MAX_SECONDS = 7 * 24 * 3600


def start_session(uid: str, email: str, name: str) -> None:
    """Called only from auth/routes.py:session_login, only after the
    verify-then-allowlist gate passes. session.clear() before populating is
    fixation hygiene (Decision 3); csrf_token is re-issued fresh every login."""
    session.clear()
    session["uid"] = uid
    session["email"] = email
    session["name"] = name
    session["iat"] = int(time.time())
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True


def clear_session() -> None:
    session.clear()


def current_uid() -> str | None:
    return session.get("uid")


def csrf_token() -> str:
    return session.get("csrf_token", "")


def _session_is_valid() -> bool:
    uid = session.get("uid")
    email = session.get("email")
    iat = session.get("iat")
    if not uid or not email or iat is None:
        return False
    if time.time() - iat > ABSOLUTE_MAX_SECONDS:
        return False
    # Decision 7: re-check the allowlist on EVERY request, not just at login —
    # this is what makes removing an address from ALLOWED_EMAILS (+ redeploy)
    # an instant revocation instead of a wait-for-expiry one.
    config = current_app.extensions["app_config"]
    return email in config.allowed_emails


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _session_is_valid():
            clear_session()
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapper


def api_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not _session_is_valid():
            clear_session()
            return jsonify({"error": "session_expired"}), 401
        return view(*args, **kwargs)

    # A url_map meta-test (tests/meta/) needs to prove, from the registered
    # view function alone, that this specific decorator was applied — the
    # route map has no other way to see through to it. Behavior-neutral.
    wrapper.is_api_login_required = True
    return wrapper
