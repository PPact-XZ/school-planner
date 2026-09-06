"""GET / (Calendar page, Screen 2) and GET /api/events (ARCHITECTURE §3.3,
§6). `/` replaces app/home.py's P3 placeholder — HTML route, `login_required`
(302 to /login when unauthenticated). `/api/events` is `api_login_required`
(401 JSON, never 302 — the `/api/*` trap: a fetch that follows a redirect
into HTML renders a blank calendar with no error).

P8: the feed merges tasks and schedules (app/calendar/events.py has the
schedule branch and fc_day()).
"""

from flask import Blueprint, current_app, jsonify, render_template, request, session

from app.auth.session import api_login_required, current_uid, login_required
from app.calendar.events import to_fullcalendar
from app.calendar.validators import validate_events_query
from app.constants import SUBJECTS
from app.schedules import service as schedules_service
from app.tasks import service as tasks_service

bp = Blueprint("calendar", __name__)


@bp.get("/")
@login_required
def index():
    # Navbar user-name is plain text at P5a (not yet the /settings link — E2
    # lands at P7, once that page exists to link to).
    #
    # `subjects` feeds the P5b modal's <select>. It comes from app.constants
    # so the dropdown and validate_task_payload cannot drift apart — a
    # hardcoded option list would 400 at the boundary with no visible cause.
    return render_template(
        "calendar.html", user_name=session.get("name", ""), subjects=SUBJECTS
    )


@bp.get("/api/events")
@api_login_required
def get_events():
    win_start, win_end = validate_events_query(request.args)

    deps = current_app.extensions["deps"]
    tasks = tasks_service.list_tasks(deps.tasks_repo, current_uid())
    schedules = schedules_service.list_schedules(deps.schedules_repo, current_uid())

    events = to_fullcalendar(tasks, schedules, win_start, win_end)
    return jsonify(events), 200
