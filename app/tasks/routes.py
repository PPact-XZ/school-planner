"""/api/tasks CRUD (create, list, get, update, delete) + submit/unsubmit —
HTTP only: parse, call service, map errors to status codes (ARCHITECTURE
§3.4, P6 brief). Every endpoint is `@api_login_required` (401 JSON on no/
expired session, never a 302 — §6). None of the unsafe-method endpoints are
in app.security.CSRF_EXEMPT_ENDPOINTS, so the app-wide before_request hook
already requires a valid X-CSRF-Token on all of them. submit/unsubmit/delete
read no request body at all — they never call _json_payload().
"""

import unicodedata

from flask import Blueprint, current_app, jsonify, request

from app.auth.session import api_login_required, current_uid
from app.errors import NotFound
from app.tasks import service

bp = Blueprint("tasks", __name__, url_prefix="/api/tasks")

# Firestore auto-IDs are short opaque strings; 128 is a generous ceiling
# (§5 "Doc IDs") that turns a garbage/huge path param into a clean 404
# instead of an oversized string reaching the repo layer.
MAX_TASK_ID_LEN = 128


def _clean_task_id(task_id: str) -> str:
    # §5 "Doc IDs": non-empty, ≤128 chars, no Cc. Same response as "doesn't
    # exist" (Decision 6) — a malformed id tells a probing caller nothing a
    # real id wouldn't also tell them.
    if not task_id or len(task_id) > MAX_TASK_ID_LEN:
        raise NotFound()
    if any(unicodedata.category(ch) == "Cc" for ch in task_id):
        raise NotFound()
    # P4 IDOR review carry-forward (LOW): Firestore reserves "." and ".." as
    # doc ids, and any id both prefixed and suffixed with "__" — on the fake
    # repo these just miss and 404 cleanly, but on real Firestore they raise
    # at the client library level, turning a probing request into a 500
    # instead of the same 404 every other bad id gets.
    if task_id in (".", "..") or (task_id.startswith("__") and task_id.endswith("__")):
        raise NotFound()
    return task_id


def _json_payload() -> dict:
    body = request.get_json(silent=True)
    # A non-dict body (bare int/string/array/invalid JSON) must fail as a
    # clean 400 in the validator, never as a TypeError-turned-500 here.
    return body if isinstance(body, dict) else {}


@bp.post("")
@api_login_required
def create():
    deps = current_app.extensions["deps"]
    doc = service.create_task(deps.tasks_repo, current_uid(), _json_payload())
    return jsonify(doc), 201


@bp.get("")
@api_login_required
def list_all():
    deps = current_app.extensions["deps"]
    docs = service.list_tasks(deps.tasks_repo, current_uid())
    return jsonify(docs), 200


@bp.get("/<task_id>")
@api_login_required
def get_one(task_id):
    deps = current_app.extensions["deps"]
    doc = service.get_task(deps.tasks_repo, current_uid(), _clean_task_id(task_id))
    return jsonify(doc), 200


@bp.put("/<task_id>")
@api_login_required
def update(task_id):
    deps = current_app.extensions["deps"]
    doc = service.update_task(
        deps.tasks_repo, current_uid(), _clean_task_id(task_id), _json_payload()
    )
    return jsonify(doc), 200


@bp.post("/<task_id>/submit")
@api_login_required
def submit(task_id):
    # No request body is ever read — submit/unsubmit take no client input
    # (locked decision 4); any body a caller sends is silently ignored.
    deps = current_app.extensions["deps"]
    doc = service.set_submitted(deps.tasks_repo, current_uid(), _clean_task_id(task_id), True)
    return jsonify(doc), 200


@bp.post("/<task_id>/unsubmit")
@api_login_required
def unsubmit(task_id):
    deps = current_app.extensions["deps"]
    doc = service.set_submitted(deps.tasks_repo, current_uid(), _clean_task_id(task_id), False)
    return jsonify(doc), 200


@bp.delete("/<task_id>")
@api_login_required
def delete_one(task_id):
    deps = current_app.extensions["deps"]
    service.delete_task(deps.tasks_repo, current_uid(), _clean_task_id(task_id))
    return "", 204
