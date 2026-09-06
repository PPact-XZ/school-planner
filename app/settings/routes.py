"""GET /settings (Screen 5, the HTML page) and PUT /api/settings (the
notify_enabled toggle) — HTTP only: parse, call service, map errors to
status codes (ARCHITECTURE §2.5, §5, P7 brief).

GET is `@login_required` (302 → /login on no/expired session, since it's a
page route). PUT is `@api_login_required` (401 JSON on no/expired session,
never a 302 — §6) and is not in app.security.CSRF_EXEMPT_ENDPOINTS, so the
app-wide before_request hook already requires a valid X-CSRF-Token.
"""

from flask import Blueprint, current_app, jsonify, render_template, request, session

from app.auth.session import api_login_required, current_uid, login_required
from app.constants import DAY_LABELS_TH, SUBJECTS
from app.settings import service

bp = Blueprint("settings", __name__)


def _json_payload() -> dict:
    # Local copy of app/tasks/routes.py's helper — private per blueprint, not
    # imported across blueprints (P7 brief).
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.get("/settings")
@login_required
def page():
    deps = current_app.extensions["deps"]
    doc = service.get_settings(
        deps.users_repo,
        current_uid(),
        session.get("email", ""),
        session.get("name", ""),
    )
    return render_template(
        "settings.html",
        user_name=doc["name"],  # doc, not session — one source per page
        user_email=doc["email"],
        notify_enabled=doc["notify_enabled"],
        # From app.constants, never hardcoded in the template — a divergent
        # copy would 400 at the boundary with no visible cause (same
        # rationale as the task modal's subject <select>, P5b).
        subjects=SUBJECTS,
        day_labels=DAY_LABELS_TH,
    )


@bp.put("/api/settings")
@api_login_required
def update():
    deps = current_app.extensions["deps"]
    result = service.update_notify(deps.users_repo, current_uid(), _json_payload())
    return jsonify(result), 200
