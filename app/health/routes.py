"""GET /healthz — static 200, no template, no session.

Render's health check hits this every few seconds; pointing it at /login would
re-render a Jinja template that often and share the login rate-limit bucket.
When Flask-Limiter is wired at P3, this endpoint must be marked limiter-exempt.
"""

from flask import Blueprint

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    return "ok", 200
