"""Schedule business rules (ARCHITECTURE §5, Decision 6, P8 brief). Pure
Python — no Flask, no Firestore. uid always arrives by injection from the
session. The overlap rule lives HERE, not in validate_schedule_payload: it is
cross-record (needs the user's other schedules), and the validator stays a
pure per-record boundary."""

from app.errors import NotFound, ValidationError, missing_doc_as_not_found
from app.schedules.validators import validate_schedule_payload

# A real timetable tops out near 8 periods x 7 days = 56; 100 bounds storage,
# the O(n) overlap scan, and the events feed (same species as MAX_TASKS_PER_USER).
MAX_SCHEDULES_PER_USER = 100


def get_owned(repo, uid: str, schedule_id: str) -> dict:
    """Fetch-then-check: missing and foreign docs are indistinguishable to the
    caller — both NotFound (404, never 403 — Decision 6). Deliberately a local
    sibling of tasks.service.get_owned, not a shared helper (P8 brief)."""
    doc = repo.get(schedule_id)
    if doc is None or doc.get("user_id") != uid:
        raise NotFound()
    return doc


def list_schedules(repo, uid: str) -> list[dict]:
    # Ordering is owned HERE, not by the repo: repo.list_by_user is an
    # equality-only Firestore query (no order_by) so it needs no composite
    # index. Sorting a <=100-row list in Python is free (MAX_SCHEDULES_PER_USER),
    # so nothing is lost by doing it here instead — see repo.py's docstring.
    rows = repo.list_by_user(uid)
    return sorted(rows, key=lambda r: (r["day_of_week"], r["start_time"]))


def _reject_overlap(existing: list[dict], candidate: dict, exclude_id: str | None) -> None:
    # Half-open [start, end): touching endpoints are NOT overlaps — 08:30-09:30
    # then 09:30-10:30 is a normal timetable (Locked decision 2a). Zero-padded
    # HH:MM compares correctly as strings (same note as the validator).
    for row in existing:
        if exclude_id is not None and row["id"] == exclude_id:
            # An update must not conflict with the row it is replacing (2b).
            continue
        if row["day_of_week"] != candidate["day_of_week"]:
            continue
        if candidate["start_time"] < row["end_time"] and row["start_time"] < candidate["end_time"]:
            raise ValidationError("start_time", "เวลาซ้อนทับกับคาบเรียนอื่นในวันเดียวกัน")


def create_schedule(repo, uid: str, payload: dict) -> dict:
    validated = validate_schedule_payload(payload)
    # One read feeds BOTH the cap check (len) and the overlap scan below —
    # neither depends on row order, so this deliberately does NOT go through
    # list_schedules()'s sort.
    existing = repo.list_by_user(uid)
    if len(existing) >= MAX_SCHEDULES_PER_USER:
        raise ValidationError(
            "limit", f"คุณมีตารางเรียนครบจำนวนสูงสุดแล้ว ({MAX_SCHEDULES_PER_USER} รายการ)"
        )
    _reject_overlap(existing, validated, exclude_id=None)
    doc = validated | {"user_id": uid}
    doc_id = repo.create(doc)
    return doc | {"id": doc_id}


def update_schedule(repo, uid: str, schedule_id: str, payload: dict) -> dict:
    # Ownership FIRST: a foreign/missing id must 404 before the payload is
    # even inspected, so a validation error can never leak "this id exists".
    existing = get_owned(repo, uid, schedule_id)
    validated = validate_schedule_payload(payload)
    # Overlap scan visits every row regardless of order — unsorted rows from
    # the repo are fine here too, same reasoning as create_schedule above.
    _reject_overlap(repo.list_by_user(uid), validated, exclude_id=schedule_id)
    with missing_doc_as_not_found():
        repo.update(schedule_id, validated)
    return existing | validated


def delete_schedule(repo, uid: str, schedule_id: str) -> None:
    get_owned(repo, uid, schedule_id)
    repo.delete(schedule_id)
