"""Authoritative email lookup at send time (Decision 2).

Adapter over firebase_admin.auth (omitted from the coverage gate). The `users`
doc's `email` is a login-time snapshot and can be stale; reminders read the
address from here instead.
"""

from firebase_admin import auth


class FirebaseUserDirectory:
    def get_email(self, uid: str) -> str | None:
        try:
            return auth.get_user(uid).email
        except auth.UserNotFoundError:
            return None
