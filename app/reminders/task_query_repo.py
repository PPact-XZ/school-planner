"""Read-only, CROSS-USER view of `tasks` (Decision 6).

Adapter layer (omitted from the coverage gate). This is the only query in the
codebase with no `user_id` filter, which is why it lives in its own module
instead of on TasksRepo: it is constructed solely in the reminders wiring and
reaches solely `reminders/service.py`. `tasks/service.py` — where every query
is scoped to one uid — must never be able to reach it. It exposes one method
and no writes at all.

**Two equality filters, no order_by.** Firestore serves multiple equality
filters from its automatic single-field indexes (zigzag merge join), so this
needs no composite index. Adding `.order_by(...)` on top would require one that
is versioned nowhere in this repo, and would raise FailedPrecondition on the
first real run while passing every test against the fake — precisely the P8
defect that would have blanked the live calendar. Ordering belongs to the
service; the fake is unordered too, so there is exactly one implementation of
it and no divergence in either direction.
"""

from google.cloud.firestore_v1.base_query import FieldFilter

COLLECTION = "tasks"


class ReminderTaskQueryRepo:
    def __init__(self, db):
        self._col = db.collection(COLLECTION)

    def list_due(self, deadline: str) -> list[dict]:
        query = self._col.where(
            filter=FieldFilter("deadline", "==", deadline)
        ).where(filter=FieldFilter("submitted", "==", False))
        return [d.to_dict() | {"id": d.id} for d in query.stream()]
