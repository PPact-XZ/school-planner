"""/api/schedules CRUD (create, list, update, delete) — HTTP only: parse,
call service, map errors to status codes (ARCHITECTURE §3.4, §5, P8 brief).
Modeled line-for-line on app/tasks/routes.py. Every endpoint is
`@api_login_required` (401 JSON on no/expired session, never a 302 — §6).
None of the unsafe-method endpoints are in app.security.CSRF_EXEMPT_ENDPOINTS,
so the app-wide before_request hook already requires a valid X-CSRF-Token on
all of them.

No GET /api/schedules/<id>: nothing needs it — schedule chips are inert (the
events feed emits no id) and the edit form fills from the already-fetched
list, unlike a task detail click which fetches one task by id.
"""

import unicodedata

from flask import Blueprint, current_app, jsonify, request

from app.auth.session import api_login_required, current_uid
from app.errors import NotFound
from app.schedules import service

bp = Blueprint("schedules", __name__, url_prefix="/api/schedules")

# Same §5 "Doc IDs" ceiling as tasks — a garbage/huge path param turns into a
# clean 404 instead of an oversized string reaching the repo layer.
MAX_SCHEDULE_ID_LEN = 128


def _clean_schedule_id(schedule_id: str) -> str:
    # Local copy of app/tasks/routes.py::_clean_task_id — private per
    # blueprint, never imported across blueprints (P7 precedent). §5 "Doc
    # IDs": non-empty, <=128 chars, no Cc. Same response as "doesn't exist"
    # (Decision 6) — a malformed id tells a probing caller nothing a real id
    # wouldn't also tell them.
    if not schedule_id or len(schedule_id) > MAX_SCHEDULE_ID_LEN:
        raise NotFound()
    if any(unicodedata.category(ch) == "Cc" for ch in schedule_id):
        raise NotFound()
    # Firestore reserves "." and ".." as doc ids, and any id both prefixed
    # and suffixed with "__" — on the fake repo these just miss and 404
    # cleanly, but on real Firestore they raise at the client library level,
    # turning a probing request into a 500 instead of the same 404 every
    # other bad id gets.
    if schedule_id in (".", "..") or (
        schedule_id.startswith("__") and schedule_id.endswith("__")
    ):
        raise NotFound()
    return schedule_id


def _json_payload() -> dict:
    # Local copy of app/tasks/routes.py's helper — private per blueprint, not
    # imported across blueprints (P7 precedent).
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


@bp.post("")
@api_login_required
def create():
    deps = current_app.extensions["deps"]
    doc = service.create_schedule(deps.schedules_repo, current_uid(), _json_payload())
    return jsonify(doc), 201


@bp.get("")
@api_login_required
def list_all():
    deps = current_app.extensions["deps"]
    docs = service.list_schedules(deps.schedules_repo, current_uid())
    return jsonify(docs), 200


@bp.put("/<schedule_id>")
@api_login_required
def update(schedule_id):
    deps = current_app.extensions["deps"]
    doc = service.update_schedule(
        deps.schedules_repo, current_uid(), _clean_schedule_id(schedule_id), _json_payload()
    )
    return jsonify(doc), 200


@bp.delete("/<schedule_id>")
@api_login_required
def delete_one(schedule_id):
    deps = current_app.extensions["deps"]
    service.delete_schedule(
        deps.schedules_repo, current_uid(), _clean_schedule_id(schedule_id)
    )
    return "", 204
