"""validate_task_payload — the `tasks` boundary (§5).

Read top to bottom. Unknown fields are rejected by whitelist (NOT by
extract-known-keys, which would silently drop injected user_id/submitted). The
returned dict is new; the input is never mutated.
"""

from urllib.parse import urlparse

from app.constants import SUBJECTS
from app.errors import ValidationError
from app.validation import clean_str, parse_ymd

ALLOWED_FIELDS = frozenset({"title", "subject", "deadline", "drive_link", "notes"})
DRIVE_HOSTS = frozenset({"drive.google.com", "docs.google.com"})


def _validate_drive_link(value) -> str:
    cleaned = clean_str(value, "drive_link", max_len=500, required=False)
    if not cleaned:
        return ""
    try:
        parsed = urlparse(cleaned)
    except ValueError:
        # urlparse itself can raise on a malformed netloc (e.g. IPv6 syntax,
        # fullwidth-solidus/NFKC confusables) rather than just returning an
        # empty/odd result. B1: the exception's own message embeds the
        # attacker-controlled input, which app/errors.py would otherwise
        # write to the log (CLAUDE.md forbids that) — raise `from None` so
        # the original message and its embedded netloc never propagate, and
        # reuse the existing rejection copy rather than inventing new copy.
        raise ValidationError("drive_link", "ต้องเป็นลิงก์ https ที่ถูกต้อง") from None
    # Require scheme https AND a non-empty netloc: "https:alert(1)" parses to
    # scheme='https', netloc='' and would pass a scheme-only check.
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValidationError("drive_link", "ต้องเป็นลิงก์ https ที่ถูกต้อง")
    if parsed.hostname is None or parsed.hostname.lower() not in DRIVE_HOSTS:
        raise ValidationError("drive_link", "อนุญาตเฉพาะลิงก์ Google Drive/Docs")
    return cleaned


def _reject_unknown_fields(payload: dict) -> None:
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        # user_id / created_at / submitted are server-set and must 400 here.
        field = sorted(unknown)[0]
        raise ValidationError(field, "ฟิลด์นี้ไม่ได้รับอนุญาต")


def validate_task_payload(payload: dict) -> dict:
    _reject_unknown_fields(payload)

    subject = clean_str(payload.get("subject"), "subject", max_len=100, required=True)
    if subject not in SUBJECTS:
        raise ValidationError("subject", "วิชาไม่ถูกต้อง")

    return {
        "title": clean_str(payload.get("title"), "title", max_len=200, required=True),
        "subject": subject,
        "deadline": parse_ymd(payload.get("deadline"), "deadline"),
        "drive_link": _validate_drive_link(payload.get("drive_link", "")),
        "notes": clean_str(payload.get("notes", ""), "notes", max_len=2000, required=False),
    }
