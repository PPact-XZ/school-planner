"""Firestore access for the `schedules` collection — one collection, thin.

Adapter layer (omitted from the coverage gate). list_by_user does NOT order —
ordering is the service's job (app/schedules/service.py::list_schedules). The
query here is equality-only (`where(user_id == uid)`), which deliberately
needs no composite index; adding `.order_by(...)` on top of the `where` would
require one Firestore does not have configured anywhere in this repo, and
would raise FailedPrecondition in production the first time a real user
called GET /api/schedules or GET /api/events.
"""

from google.cloud.firestore_v1.base_query import FieldFilter

COLLECTION = "schedules"


class SchedulesRepo:
    def __init__(self, db):
        self._col = db.collection(COLLECTION)

    def create(self, doc: dict) -> str:
        ref = self._col.document()
        ref.set(doc)
        return ref.id

    def get(self, doc_id: str) -> dict | None:
        snap = self._col.document(doc_id).get()
        return snap.to_dict() | {"id": snap.id} if snap.exists else None

    def list_by_user(self, uid: str) -> list[dict]:
        # Equality-only filter, no order_by: see module docstring. Rows come
        # back in whatever order Firestore streams them; the caller sorts.
        query = self._col.where(filter=FieldFilter("user_id", "==", uid))
        return [d.to_dict() | {"id": d.id} for d in query.stream()]

    def update(self, doc_id: str, fields: dict) -> None:
        self._col.document(doc_id).update(fields)

    def delete(self, doc_id: str) -> None:
        self._col.document(doc_id).delete()
