"""GET /login, POST /sessionLogin, POST /logout (ARCHITECTURE Decision 3/7,
§6). sessionLogin is the one CSRF-exempt unsafe endpoint (app/security.py);
it substitutes Content-Type + Origin checks because a CSRF token cannot exist
until this call mints the session that carries it.
"""

import logging

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for

from app.auth.service import AllowlistRejected, TokenRejected, upsert_login, verify_and_check_allowlist
from app.auth.session import clear_session, start_session
from app.security import limiter

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)


@bp.get("/login")
def login():
    config = current_app.extensions["app_config"]
    return render_template("login.html", firebase_config=config.firebase_web_config)


@bp.post("/sessionLogin")
@limiter.limit("10/minute")
def session_login():
    config = current_app.extensions["app_config"]

    # "SameSite=Lax covers login CSRF" is false — SameSite governs whether the
    # browser SENDS an existing cookie cross-site, not whether a cross-site
    # POST can be made at all. Origin validation is the real guard: an
    # attacker's page POSTing an attacker-controlled ID token here would log
    # the victim into the attacker's account.
    origin = request.headers.get("Origin")
    if origin != config.app_origin:
        # Both values are logged because this rejection is otherwise
        # undiagnosable: "origin mismatch" alone cannot distinguish a real
        # cross-site attack from the developer opening 127.0.0.1 instead of
        # localhost, or a port that does not match APP_ORIGIN — and that
        # ambiguity cost a live debugging session.
        #
        # Neither value is a secret: APP_ORIGIN is the app's own public URL,
        # and Origin is a scheme/host/port the browser computed. NOT the same
        # as the email on the allowlist branch below, which stays unlogged.
        #
        # %r, not %s: the received Origin is attacker-controlled, and repr
        # escapes CR/LF so a crafted header cannot forge extra log lines.
        # Truncated for the same reason — a header is not a payload.
        log.warning(
            "login rejected: origin mismatch received=%r expected=%r",
            (origin or "")[:100],
            config.app_origin,
        )
        return jsonify({"error": "origin_rejected"}), 403

    # get_json() with NEITHER force=True NOR silent=True: a wrong Content-Type
    # 415s by Flask's own default, and that 415 is a deliberate CSRF defense —
    # it is what makes a cross-origin <form> POST to this endpoint impossible
    # without a CORS preflight the browser will not send for a simple form.
    payload = request.get_json()
    id_token = payload.get("idToken") if isinstance(payload, dict) else None

    deps = current_app.extensions["deps"]
    try:
        claims = verify_and_check_allowlist(deps.token_verifier, config.allowed_emails, id_token)
    except TokenRejected:
        log.warning("login rejected: invalid token")
        return jsonify({"error": "invalid_token"}), 401
    except AllowlistRejected:
        # No session, no Firestore write — upsert_login is not reachable from
        # this branch (audit CRITICAL S-C2).
        log.warning("login rejected: not allowlisted")
        return jsonify({"error": "not_allowed"}), 403

    upsert_login(deps.users_repo, claims["uid"], claims["email"], claims["name"])
    start_session(claims["uid"], claims["email"], claims["name"])
    return jsonify({"ok": True}), 200


@bp.post("/logout")
def logout():
    # POST, not GET (audit S-M7): a GET logout is CSRF-able via a bare <img>
    # tag. This endpoint is NOT in CSRF_EXEMPT_ENDPOINTS, so the app-wide hook
    # already requires a valid X-CSRF-Token here.
    clear_session()
    return redirect(url_for("auth.login"))
