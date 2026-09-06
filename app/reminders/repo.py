"""Firestore access for the `reminder_log` collection — one collection, thin.

Adapter layer (omitted from the coverage gate). Doc ID = "{deadline}_{task_id}"
(§5), so the identity of a reminder is structural rather than queried.

There is deliberately **no delete()**. The ledger's whole purpose is that a doc,
once written, is never removed; a delete method here would put the double-send
one call away. FakeReminderLogRepo omits it too, so a service that tried would
fail loudly in tests rather than only in production.
"""

COLLECTION = "reminder_log"


class ReminderLogRepo:
    def __init__(self, db):
        self._col = db.collection(COLLECTION)

    def create(self, doc_id: str, doc: dict) -> None:
        # .create(), NOT .set(): create() raises on an existing doc, and that
        # exception IS the mutual exclusion between two concurrent triggers.
        # .set() would overwrite the claim and silently permit a second email.
        #
        # It raises AlreadyExists over gRPC, which subclasses Conflict
        # (verified: AlreadyExists.__mro__ -> Conflict), so the service's
        # `except Conflict` covers this transport and any other.
        self._col.document(doc_id).create(doc)

    def update(self, doc_id: str, fields: dict) -> None:
        self._col.document(doc_id).update(fields)

    def get(self, doc_id: str) -> dict | None:
        snap = self._col.document(doc_id).get()
        return snap.to_dict() if snap.exists else None
