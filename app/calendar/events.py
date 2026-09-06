"""Pure mapping/filter logic for the `/api/events` feed (ARCHITECTURE §3.3,
Decision 1). No Flask, no Firestore — tasks, schedules, and the request
window arrive as plain arguments so this is trivially unit-testable.

P8: schedules map to recurring FullCalendar events (blue chips). Two
as-built necessities beyond the §3.3 sketch, both verified against the
vendored FullCalendar 6.1.15 and Flask (OPEN CONFLICTS 2):
- `"display": "block"` — without it, dayGridMonth renders a TIMED event
  (which a recurring schedule event is, carrying startTime/endTime) as a
  dot-style list item, not a filled chip. The locked bg-blue-100 chip would
  simply not exist.
- `startRecur`/`endRecur` are `.isoformat()` strings, not raw `date`
  objects — Flask's default JSON provider serializes a `date` to RFC-822
  ("Fri, 01 Aug 2026 00:00:00 GMT"), which FullCalendar cannot parse.

Schedule events carry NO "id" key on purpose: there is no schedule detail
modal, and calendar.js's eventClick guards on `!info.event.id` to keep a
schedule-chip click inert (the server half of that contract lives here).
"""

from datetime import date, datetime

CHIP_UNSUBMITTED = ("bg-yellow-100", "text-yellow-800")
CHIP_SUBMITTED = ("bg-green-100", "text-green-800")
CHIP_SCHEDULE = ("bg-blue-100", "text-blue-800")


def fc_day(day_of_week: int) -> int:
    """T002 day (0=Mon..6=Sun) -> FullCalendar `daysOfWeek` day (0=Sun..6=Sat)
    (Decision 1a). No inverse exists: the schedule form submits T002 values
    directly. Its consumer (recurring schedule events) lands at P8 — built
    now because it is a pure function with a locked spec, not because
    anything calls it yet.
    """
    return (day_of_week + 1) % 7


def _deadline_in_window(deadline: str, win_start: date, win_end: date) -> bool:
    # Half-open [win_start, win_end) — FullCalendar's own `end` is exclusive,
    # so a task exactly on win_end must NOT be included. Compared as `date`
    # objects, never a raw string compare (§5) — deadline is "YYYY-MM-DD".
    parsed = datetime.strptime(deadline, "%Y-%m-%d").date()
    return win_start <= parsed < win_end


def _chip_classes(submitted: bool) -> list[str]:
    # A fresh list per call — CHIP_* are shared tuples; returning `list(...)`
    # of one means each event dict owns its own classNames list, so a caller
    # mutating one event's chip classes can never bleed into another's.
    return list(CHIP_SUBMITTED if submitted else CHIP_UNSUBMITTED)


def to_fullcalendar(
    tasks: list[dict], schedules: list[dict], win_start: date, win_end: date
) -> list[dict]:
    """Map owned tasks in [win_start, win_end) plus every schedule doc to
    FullCalendar's event shape. Titles are passed as plain text —
    FullCalendar's default (non-innerHTML) render path escapes them.

    `schedules` is positional-required (not an optional default with []):
    an optional default would let a caller forget to pass it and stay green
    (P8 brief). Tasks are single-date all-day events with no recurrence;
    schedules are recurring and bounded by startRecur/endRecur (FullCalendar's
    job), never filtered against the task date window in Python — a schedule
    always emits regardless of win_start/win_end.
    """
    task_events = [
        {
            # P6: FullCalendar exposes this natively as info.event.id.
            # notes/drive_link stay out (locked decision 1) — a chip click
            # fetches the full task separately via GET /api/tasks/<id>.
            "id": task["id"],
            "title": task["title"],
            "start": task["deadline"],
            "allDay": True,
            "classNames": _chip_classes(task["submitted"]),
        }
        for task in tasks
        if _deadline_in_window(task["deadline"], win_start, win_end)
    ]
    schedule_events = [
        {
            "title": sched["subject"],  # subject only — no room, no time
            "daysOfWeek": [fc_day(sched["day_of_week"])],  # THE one conversion site (Decision 1a)
            "startTime": sched["start_time"],
            "endTime": sched["end_time"],
            "startRecur": win_start.isoformat(),
            "endRecur": win_end.isoformat(),  # win_end is exclusive; endRecur is exclusive — aligned
            "display": "block",  # dot-vs-block trap — see module docstring
            "classNames": list(CHIP_SCHEDULE),  # fresh list per event, like _chip_classes
        }
        for sched in schedules
    ]
    return task_events + schedule_events
