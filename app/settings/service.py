"""Settings business rules (ARCHITECTURE §2.5, §5, Decision 6). Pure Python —
no Flask, no Firestore. `uid` always arrives by injection from the session
(routes never read a user id from the request/payload). Services never
mutate inputs — every return value is a new dict.
"""

import logging

from app.auth.service import upsert_login
from app.errors import NotFound, missing_doc_as_not_found
from app.settings.validators import validate_settings_payload

log = logging.getLogger(__name__)


def get_settings(users_repo, uid: str, email: str, name: str) -> dict:
    """Read-side self-heal: login upserts this doc before minting the
    session (auth/routes.py), so "valid session, no doc" means a console-
    side deletion mid-session. Reuse upsert_login so the first-login doc
    shape stays defined in exactly one place. uid only ever logged — never
    the email (CLAUDE.md logging rule)."""
    doc = users_repo.get(uid)
    if doc is None:
        log.warning("users doc missing for a valid session — re-upserting uid=%s", uid)
        upsert_login(users_repo, uid, email, name)
        doc = users_repo.get(uid)

    # Read-side normalization only; the write path stays strict (§5) — a
    # hand-edited doc missing a key renders instead of KeyError-500ing.
    return {
        "email": doc.get("email", ""),
        "name": doc.get("name", ""),
        "notify_enabled": doc.get("notify_enabled", True),
    }


def update_notify(users_repo, uid: str, payload: dict) -> dict:
    """Validate first: unlike tasks, there is no id in the request at all,
    so the "ownership before validation" leak-ordering rationale
    (tasks.service.update_task) does not apply — the boundary check simply
    comes first."""
    validated = validate_settings_payload(payload)

    if users_repo.get(uid) is None:
        # NEVER rely on users_repo.update() to create the doc: the fake
        # would (setdefault), real Firestore raises. Get-first makes the
        # divergence unreachable and turns the edge into an honest 404.
        raise NotFound()

    # get-first above narrows the window; it does not close it. The doc can
    # still vanish between that read and this write.
    with missing_doc_as_not_found():
        users_repo.update(uid, validated)
    return validated
