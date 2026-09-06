"""Dependency injection surface (ARCHITECTURE §3.6).

One frozen dataclass names every repo/adapter a feature may reach, so no
dependency is implicit. `create_app(deps=None)` builds the production set from
`build_production_deps()`; tests pass a `Deps` of `tests/fakes.py` instances.

The reminders trio (`reminder_log_repo`, `reminder_task_query`, `mailer`) landed
at P9. Decision 6's isolation is expressed here by what each feature is handed:
`reminder_task_query` (the only cross-user query in the codebase) reaches the
reminders service and nothing else, and `tasks_repo` is never handed to the
reminders service.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Deps:
    tasks_repo: object = None       # tasks feature
    schedules_repo: object = None   # schedules feature
    users_repo: object = None       # auth + settings + reminders
    user_directory: object = None   # authoritative email at send time
    token_verifier: object = None   # auth: verifies a Firebase ID token (P3)
    reminder_log_repo: object = None    # reminders: the never-delete ledger (P9)
    reminder_task_query: object = None  # reminders: READ-ONLY cross-user tasks view (P9)
    mailer: object = None               # reminders: Resend HTTP API (P9; Gmail SMTP
                                         # eliminated by Render's free-tier outbound-SMTP
                                         # block, see ARCHITECTURE.md Decision 2 addendum)


def build_production_deps(config) -> Deps:
    """Wire real Firestore-backed repos. Imports are local so the module graph
    for tests (which always inject fakes) never pulls in the Firebase client.

    Not covered by the unit gate (.coveragerc omits app/wiring.py): it is thin
    construction over the network adapter layer, exercised by the opt-in
    -m firestore suite and by real deploys.
    """
    from app.auth.token_verifier import FirebaseTokenVerifier
    from app.firebase import get_db
    from app.reminders.mailer import ResendMailer
    from app.reminders.repo import ReminderLogRepo
    from app.reminders.task_query_repo import ReminderTaskQueryRepo
    from app.schedules.repo import SchedulesRepo
    from app.tasks.repo import TasksRepo
    from app.users.directory import FirebaseUserDirectory
    from app.users.repo import UsersRepo

    db = get_db(config)
    return Deps(
        tasks_repo=TasksRepo(db),
        schedules_repo=SchedulesRepo(db),
        users_repo=UsersRepo(db),
        user_directory=FirebaseUserDirectory(),
        token_verifier=FirebaseTokenVerifier(),
        reminder_log_repo=ReminderLogRepo(db),
        reminder_task_query=ReminderTaskQueryRepo(db),
        # Constructed even when the credentials are blank: the route checks
        # for them and 503s before the job claims anything, which keeps the
        # failure a clean "not configured" instead of a burnt ledger.
        mailer=ResendMailer(config.resend_api_key, config.resend_from_email),
    )
