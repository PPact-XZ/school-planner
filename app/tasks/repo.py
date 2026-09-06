"""Firestore access for the `tasks` collection — one collection, thin.

Adapter layer (omitted from the coverage gate). Deliberately has NO cross-user
method: the reminders cross-user query lives in its own read-only repo
(Decision 6). Inputs are never mutated — create() builds a new dict.
"""

from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

COLLECTION = "tasks"


class TasksRepo:
    def __init__(self, db):
        self._col = db.collection(COLLECTION)

    def create(self, doc: dict) -> str:
        ref = self._col.document()
        ref.set(doc | {"created_at": firestore.SERVER_TIMESTAMP})
        return ref.id

    def get(self, doc_id: str) -> dict | None:
        snap = self._col.document(doc_id).get()
        return snap.to_dict() | {"id": snap.id} if snap.exists else None

    def list_by_user(self, uid: str) -> list[dict]:
        query = self._col.where(filter=FieldFilter("user_id", "==", uid))
        return [d.to_dict() | {"id": d.id} for d in query.stream()]

    def count_by_user(self, uid: str) -> int:
        # Bounded by the 500-task cap (Decision 7); reading to count is fine here.
        query = self._col.where(filter=FieldFilter("user_id", "==", uid))
        return sum(1 for _ in query.stream())

    def update(self, doc_id: str, fields: dict) -> None:
        self._col.document(doc_id).update(fields)

    def delete(self, doc_id: str) -> None:
        self._col.document(doc_id).delete()
