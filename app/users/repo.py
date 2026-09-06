"""Firestore access for the `users` collection — one collection, thin.

Adapter layer (omitted from the coverage gate). Its own module (NOT under
settings/) because P3's login upsert needs it long before the Settings page
exists (§9 dependencies). Doc ID = Firebase UID.
"""

COLLECTION = "users"


class UsersRepo:
    def __init__(self, db):
        self._db = db
        self._col = db.collection(COLLECTION)

    def get(self, uid: str) -> dict | None:
        snap = self._col.document(uid).get()
        return snap.to_dict() if snap.exists else None

    def upsert(self, uid: str, doc: dict) -> None:
        # Full set at login (after the allowlist check — Decision 7).
        self._col.document(uid).set(doc)

    def update(self, uid: str, fields: dict) -> None:
        self._col.document(uid).update(fields)

    def get_many(self, uids) -> dict[str, dict]:
        # Batched read (Decision 2: no N+1 over reminder owners).
        refs = [self._col.document(uid) for uid in uids]
        if not refs:
            return {}
        return {
            snap.id: snap.to_dict()
            for snap in self._db.get_all(refs)
            if snap.exists
        }
