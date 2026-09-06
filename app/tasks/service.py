"""Task business rules (ARCHITECTURE §3.4, §5, Decision 6). Pure Python — no
Flask, no Firestore. `uid` always arrives by injection from the session
(routes never read a user id from the request/payload); ownership is
enforced here via get_owned, the single choke point every read/update goes
through. Services never mutate inputs — every return value is a new dict.
"""

from app.errors import NotFound, ValidationError, missing_doc_as_not_found
from app.tasks.validators import validate_task_payload

# Decision 7 / S-C2 backstop: bounds storage and the in-memory calendar event
# mapping (§3.3) against a runaway or abusive client. One user, a few hundred
# tasks a year — 500 is generous, not a real limit for honest use.
MAX_TASKS_PER_USER = 500


def get_owned(repo, uid: str, task_id: str) -> dict:
    """Fetch-then-check, in that order: a missing doc and a foreign doc must
    be indistinguishable to the caller, so both raise the same NotFound (404,
    never 403 — Decision 6)."""
    doc = repo.get(task_id)
    if doc is None or doc.get("user_id") != uid:
        raise NotFound()
    return doc


def create_task(repo, uid: str, payload: dict) -> dict:
    validated = validate_task_payload(payload)

    if repo.count_by_user(uid) >= MAX_TASKS_PER_USER:
        raise ValidationError(
            "limit", f"คุณมีงานครบจำนวนสูงสุดแล้ว ({MAX_TASKS_PER_USER} รายการ)"
        )

    # user_id/submitted are server-set here, never taken from payload — the
    # validator already rejects both as unknown fields if a caller tries.
    doc = validated | {"user_id": uid, "submitted": False}
    doc_id = repo.create(doc)
    return doc | {"id": doc_id}


def list_tasks(repo, uid: str) -> list[dict]:
    # Only ever the owned-list read. No unfiltered list exists on TasksRepo
    # (Decision 6) — there is nothing broader this could accidentally call.
    return repo.list_by_user(uid)


def get_task(repo, uid: str, task_id: str) -> dict:
    return get_owned(repo, uid, task_id)


def update_task(repo, uid: str, task_id: str, payload: dict) -> dict:
    # Ownership FIRST: a foreign or missing id must 404 before the payload is
    # even inspected, so a validation error can never leak "this id exists".
    existing = get_owned(repo, uid, task_id)
    validated = validate_task_payload(payload)

    # Partial field update — user_id/submitted/created_at are untouched in
    # the store because they are not in `validated` (the validator whitelists
    # them out). Editing can never flip `submitted` or reassign `user_id`.
    with missing_doc_as_not_found():
        repo.update(task_id, validated)
    return existing | validated


def set_submitted(repo, uid: str, task_id: str, submitted: bool) -> dict:
    """Flip only `submitted` (Screen 4's ส่งงานแล้ว/ยกเลิกการส่ง toggle). Never
    routes through update_task/validate_task_payload — `submitted` is a
    server-only field, changed exclusively via this function (locked
    decision 4).

    TOCTOU (shared with update_task): get_owned and the repo.update below are
    not transactional, so a doc deleted in between used to surface as 500.
    Fixed 2026-09-06 once the real exception class was MEASURED against live
    Firestore rather than guessed — see missing_doc_as_not_found().
    """
    existing = get_owned(repo, uid, task_id)
    with missing_doc_as_not_found():
        repo.update(task_id, {"submitted": submitted})
    return existing | {"submitted": submitted}


def delete_task(repo, uid: str, task_id: str) -> None:
    """E3 delete. Ownership FIRST, same as update_task — a foreign or
    missing id 404s before anything is touched."""
    get_owned(repo, uid, task_id)
    repo.delete(task_id)
