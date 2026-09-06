"""validate_schedule_payload — the `schedules` boundary (§5).

Read top to bottom. day_of_week uses T002 semantics (0=Mon). Unknown fields are
rejected by whitelist. The returned dict is new; the input is never mutated.
"""

from app.constants import SUBJECTS
from app.errors import ValidationError
from app.validation import clean_str, parse_hhmm

ALLOWED_FIELDS = frozenset(
    {"subject", "day_of_week", "start_time", "end_time", "room"}
)


def _validate_day_of_week(value) -> int:
    # bool BEFORE int: isinstance(True, int) is True, so True would pass as 1.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("day_of_week", "วันต้องเป็นตัวเลข 0–6")
    if not (0 <= value <= 6):
        raise ValidationError("day_of_week", "วันต้องอยู่ระหว่าง 0–6")
    return value


def _reject_unknown_fields(payload: dict) -> None:
    unknown = set(payload) - ALLOWED_FIELDS
    if unknown:
        field = sorted(unknown)[0]
        raise ValidationError(field, "ฟิลด์นี้ไม่ได้รับอนุญาต")


def validate_schedule_payload(payload: dict) -> dict:
    _reject_unknown_fields(payload)

    subject = clean_str(payload.get("subject"), "subject", max_len=100, required=True)
    if subject not in SUBJECTS:
        raise ValidationError("subject", "วิชาไม่ถูกต้อง")

    start_time = parse_hhmm(payload.get("start_time"), "start_time")
    end_time = parse_hhmm(payload.get("end_time"), "end_time")
    # Zero-padded HH:MM compares correctly as strings.
    if end_time <= start_time:
        raise ValidationError("end_time", "เวลาเลิกต้องหลังเวลาเริ่ม")

    return {
        "subject": subject,
        "day_of_week": _validate_day_of_week(payload.get("day_of_week")),
        "start_time": start_time,
        "end_time": end_time,
        "room": clean_str(payload.get("room", ""), "room", max_len=50, required=False),
    }
