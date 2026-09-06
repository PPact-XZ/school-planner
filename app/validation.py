"""Three concrete validation helpers (ARCHITECTURE §5).

No registry, no DSL — a reader sees the rules, not an engine that produces them.
Each helper returns a NEW value; callers assemble a NEW dict (inputs never
mutated).
"""

import re
import unicodedata
from datetime import datetime

from app.errors import ValidationError

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_MIN_YEAR = 2000
_MAX_YEAR = 2100


def _has_control_char(value: str) -> bool:
    # Unicode category "Cc" — rejects \n \r \t \x00 etc. while permitting all
    # Thai text (category Lo). Closes email-header poison and log injection.
    return any(unicodedata.category(ch) == "Cc" for ch in value)


def clean_str(value, field: str, *, max_len: int, required: bool) -> str:
    if not isinstance(value, str):
        raise ValidationError(field, "ต้องเป็นข้อความ")

    stripped = value.strip()
    if not stripped:
        if required:
            raise ValidationError(field, "กรุณากรอกข้อมูล")
        return ""

    if len(stripped) > max_len:
        raise ValidationError(field, f"ต้องยาวไม่เกิน {max_len} ตัวอักษร")
    if _has_control_char(stripped):
        raise ValidationError(field, "มีอักขระที่ไม่อนุญาต")
    return stripped


def parse_ymd(value, field: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(field, "รูปแบบวันที่ไม่ถูกต้อง")
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(field, "รูปแบบวันที่ไม่ถูกต้อง (YYYY-MM-DD)")
    if not (_MIN_YEAR <= parsed.year <= _MAX_YEAR):
        raise ValidationError(field, "ปีต้องอยู่ระหว่าง 2000–2100")
    return parsed.strftime("%Y-%m-%d")  # canonical, zero-padded


def parse_hhmm(value, field: str) -> str:
    if not isinstance(value, str) or not _HHMM.match(value.strip()):
        raise ValidationError(field, "รูปแบบเวลาไม่ถูกต้อง (HH:MM)")
    return value.strip()
