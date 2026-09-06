"""validate_events_query — the `/api/events` query boundary (§5).

FullCalendar sends ISO8601 WITH a UTC offset (e.g.
"2026-08-01T00:00:00+07:00"), never a bare "YYYY-MM-DD" — comparing that raw
string against a task's "YYYY-MM-DD" deadline would silently misorder every
window. Parsed with datetime.fromisoformat, converted to Asia/Bangkok, then
reduced to a `date` — all downstream comparisons are date-to-date.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.errors import ValidationError

# tzdata is a pinned runtime dependency (ARCHITECTURE Decision 2) — zoneinfo
# reads the OS tz database, which slim Linux images omit.
BANGKOK = ZoneInfo("Asia/Bangkok")

MAX_WINDOW_DAYS = 366


def _parse_instant(value, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(field, "พารามิเตอร์วันที่ไม่ถูกต้อง")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError(field, "รูปแบบวันที่ไม่ถูกต้อง")
    if parsed.tzinfo is None:
        # FullCalendar always sends an offset (§3.3). A naive value's zone is
        # unknown — reject rather than silently assume Bangkok.
        raise ValidationError(field, "ต้องระบุ timezone offset")
    return parsed


def _to_bangkok_date(instant: datetime) -> date:
    return instant.astimezone(BANGKOK).date()


def validate_events_query(args) -> tuple[date, date]:
    """`args` is anything with a `.get(key, default)` — a Flask
    request.args MultiDict in production, a plain dict in unit tests."""
    start_instant = _parse_instant(args.get("start", ""), "start")
    end_instant = _parse_instant(args.get("end", ""), "end")

    start_date = _to_bangkok_date(start_instant)
    end_date = _to_bangkok_date(end_instant)

    if end_date <= start_date:
        raise ValidationError("end", "end ต้องอยู่หลัง start")
    if (end_date - start_date).days > MAX_WINDOW_DAYS:
        raise ValidationError("end", f"ช่วงวันที่ต้องไม่เกิน {MAX_WINDOW_DAYS} วัน")

    return start_date, end_date
