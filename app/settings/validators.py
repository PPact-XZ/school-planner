"""validate_settings_payload — the `settings` boundary (§5).

Read top to bottom. Unknown fields are rejected by whitelist (the same
pattern as app/tasks/validators.py — NOT extract-known-keys, which would
silently drop an injected user_id). The returned dict is new; the input is
never mutated.
"""

from app.errors import ValidationError

ALLOWED_FIELDS = frozenset({"notify_enabled"})


def validate_settings_payload(payload: dict) -> dict:
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        # user_id (or anything else) injected here must 400, same as tasks.
        field = sorted(unknown)[0]
        raise ValidationError(field, "ฟิลด์นี้ไม่ได้รับอนุญาต")

    value = payload.get("notify_enabled")
    if not isinstance(value, bool):
        # §5: strict — "true"/1/0/None/[]/{} must all 400.
        # isinstance(1, bool) is False in Python, so 1/0 are rejected too.
        raise ValidationError("notify_enabled", "ค่าไม่ถูกต้อง")

    return {"notify_enabled": value}
