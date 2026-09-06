"""Application factory.

`create_app(deps=None)` is the whole testability seam (ARCHITECTURE §3.6): tests
inject a `Deps` of in-memory fakes; production passes `None` and the factory
builds real Firestore-backed repos via `build_production_deps()`.
"""

import os
from datetime import timedelta

from flask import Flask

from app.auth.routes import bp as auth_bp
from app.calendar.routes import bp as calendar_bp
from app.config import SESSION_LIFETIME_DAYS, load_config
from app.errors import register_error_handlers
from app.health.routes import bp as health_bp
from app.reminders.routes import bp as reminders_bp
from app.schedules.routes import bp as schedules_bp
from app.security import limiter, register_security
from app.settings.routes import bp as settings_bp
from app.tasks.routes import bp as tasks_bp
from app.wiring import Deps, build_production_deps


def create_app(deps: Deps | None = None) -> Flask:
    # Fail fast on config BEFORE any dependency construction, so a bad APP_ENV
    # (Decision 8) never reaches Firebase or the network.
    config = load_config(dict(os.environ))

    if deps is None:
        deps = build_production_deps(config)

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=config.secret_key,
        MAX_CONTENT_LENGTH=config.max_content_length,
        # Session cookie properties (Decision 3). SESSION_REFRESH_EACH_REQUEST
        # defaults to True in Flask, which would re-stamp cookie expiry on
        # every request and turn the 7-day lifetime into an idle timeout —
        # False here plus the server-side iat check (auth/session.py) is what
        # makes it an absolute cap.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=config.is_production,
        # __Host- requires Secure, which http://localhost never sets — the
        # browser would reject the cookie outright and break local login.
        # Production only.
        SESSION_COOKIE_NAME="__Host-session" if config.is_production else "session",
        PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_LIFETIME_DAYS),
        SESSION_REFRESH_EACH_REQUEST=False,
    )
    app.extensions["deps"] = deps
    app.extensions["app_config"] = config

    register_error_handlers(app)
    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(schedules_bp)
    app.register_blueprint(reminders_bp)
    register_security(app)
    # Render's health check hits this every few seconds — it must not share
    # the login rate-limit bucket with real traffic.
    limiter.exempt(health_bp)
    return app
