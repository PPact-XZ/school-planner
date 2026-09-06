"""Single source of truth for the subject list (§5).

Rendered into both the task <select> and the ตารางเรียน form, and enforced by
both validators. NOT derived from existing schedules docs — that is a
chicken-and-egg on first use. Adding a subject is a one-line change here.
"""

SUBJECTS: tuple[str, ...] = (
    "คณิตศาสตร์",
    "ฟิสิกส์",
    "เคมี",
    "ชีววิทยา",
    "ภาษาไทย",
    "ภาษาอังกฤษ",
    "สังคมศึกษา",
    "สุขศึกษา",
    "การงานอาชีพ",
)

# Thai day labels for the ตารางเรียน day <select>. THE INDEX IS THE T002
# day_of_week VALUE (0=จันทร์ .. 6=อาทิตย์ — Decision 1a; identical to
# date.weekday()). schedules.js reads row labels back off the rendered
# <option>s, so this tuple is the single source — never duplicate it in JS.
DAY_LABELS_TH: tuple[str, ...] = (
    "จันทร์",
    "อังคาร",
    "พุธ",
    "พฤหัสบดี",
    "ศุกร์",
    "เสาร์",
    "อาทิตย์",
)
