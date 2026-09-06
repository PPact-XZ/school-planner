"""Auth business rules (ARCHITECTURE Decision 3, Decision 7). Pure Python —
no Flask, no Firestore; `token_verifier` and `users_repo` arrive by
injection so this is testable against fakes alone.

`verify_and_check_allowlist` deliberately takes no repo: it CANNOT upsert on
any path, which is what makes the audit-critical ordering (verify → allowlist
→ only-then-upsert, S-C2) a property of the code shape, not just a tested
behavior. The caller (auth/routes.py) must call this first, catch a
rejection, and only call `upsert_login` if it did not raise.
"""

from app.auth.token_verifier import TokenVerificationError


class TokenRejected(Exception):
    """Missing/invalid token, or a verified token without a confirmed email
    (audit S-M3: email present AND email_verified True, checked before
    anything else happens)."""


class AllowlistRejected(Exception):
    """Token verified, email confirmed, but not on ALLOWED_EMAILS. The caller
    must not have written anything before this is raised (Decision 7)."""


def verify_and_check_allowlist(token_verifier, allowed_emails, id_token) -> dict:
    """Order is load-bearing (audit CRITICAL S-C2): verify THEN allowlist.
    Returns {uid, email, name} only when both pass."""
    if not id_token or not isinstance(id_token, str):
        raise TokenRejected("missing id token")

    try:
        claims = token_verifier.verify(id_token)
    except TokenVerificationError as exc:
        raise TokenRejected(str(exc)) from exc

    email = claims.get("email")
    if not email or not claims.get("email_verified"):
        raise TokenRejected("email missing or unverified")

    email = email.strip().lower()
    if email not in allowed_emails:
        raise AllowlistRejected("not allowlisted")

    return {"uid": claims["uid"], "email": email, "name": claims.get("name") or ""}


def upsert_login(users_repo, uid: str, email: str, name: str) -> None:
    """Called only after verify_and_check_allowlist succeeds. First login:
    full doc with notify_enabled defaulting True. Returning login: merge
    email/name only — a full re-upsert every login would silently clobber the
    Settings (P7) notify_enabled preference back to True. T002/ARCHITECTURE
    §2.5 says "upserted at login" without specifying overwrite-vs-merge on a
    field P3 doesn't own; merge-on-return is the reading that doesn't regress
    a field this phase has no business touching."""
    if users_repo.get(uid) is None:
        users_repo.upsert(uid, {"email": email, "name": name, "notify_enabled": True})
    else:
        users_repo.update(uid, {"email": email, "name": name})
