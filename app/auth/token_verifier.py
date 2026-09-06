"""Firebase ID token verification — the seam auth/service.py depends on.

Adapter layer (omitted from the coverage gate, like users/directory.py):
thin, logic-free translation to firebase_admin, exercised by manual smoke
testing and later the opt-in `-m firestore` suite, never by unit tests.
tests/fakes.FakeTokenVerifier implements the same `.verify()` contract so
service.py never imports firebase_admin directly (§5 build-against-fakes).
"""

from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError


class TokenVerificationError(Exception):
    """The token is missing, malformed, expired, revoked, or otherwise fails
    Firebase's verification. Callers never see the underlying SDK exception
    type — only that verification failed."""


class FirebaseTokenVerifier:
    def verify(self, id_token: str) -> dict:
        # check_revoked=True: a per-request round-trip would be a real cost,
        # but this runs once per login, not once per request (Decision 3).
        # Catch the SDK's exception BASE, not an enumerated subtype list: every
        # firebase_admin.auth verification failure (invalid/expired/revoked
        # token, cert-fetch error, disabled user, ...) subclasses FirebaseError
        # (confirmed against firebase-admin 7.5.0's exception MRO), so a
        # narrower tuple would let an unlisted subtype fall through as an
        # unhandled 500 instead of the 401 "invalid token" this seam promises.
        try:
            claims = auth.verify_id_token(id_token, check_revoked=True)
        except (ValueError, FirebaseError) as exc:
            raise TokenVerificationError(type(exc).__name__) from exc

        return {
            "uid": claims.get("uid") or claims.get("user_id"),
            "email": claims.get("email"),
            "email_verified": bool(claims.get("email_verified", False)),
            "name": claims.get("name") or "",
        }
