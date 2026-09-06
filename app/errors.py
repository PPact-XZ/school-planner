"""ValidationError and the app-wide 400/500 handlers.

Contract: the client gets a friendly Thai message; the log gets the detail.
An unexpected exception NEVER reaches the client as text.
"""

import logging
from contextlib import contextmanager

from flask import has_request_context, jsonify, request
# The vendor class real Firestore raises from document().update() when the doc
# is gone. Measured against school-planner-dev on 2026-09-06, never guessed —
# the sibling trap (Conflict, not AlreadyExists) is why this repo has that rule.
# Note google.cloud.exceptions.NotFound IS this same object, so either import
# path works; this one matches tests/fakes.py.
from google.api_core.exceptions import NotFound as FirestoreNotFound
from werkzeug.exceptions import HTTPException

GENERIC_ERROR_TH = "เกิดข้อผิดพลาด กรุณาลองใหม่"

log = logging.getLogger(__name__)


class ValidationError(Exception):
    """A boundary rule was violated. Carries the field so the client can
    highlight it. Message is Thai (user-facing copy per T002)."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field
        self.message = message

    def as_dict(self) -> dict:
        return {"error": "validation_error", "fields": {self.field: self.message}}


class NotFound(Exception):
    """A doc is missing OR not owned by the caller (Decision 6). Always maps
    to 404, never 403 — a probing user must not be able to tell "exists but
    isn't yours" from "doesn't exist". Deliberately NOT a subclass of
    werkzeug's HTTPException: that would route it through Flask's own
    exception machinery instead of the explicit handler below, and the name
    would shadow werkzeug.exceptions.NotFound for anyone reading imports."""

    def __init__(self, message: str = "ไม่พบข้อมูล"):
        super().__init__(message)
        self.message = message


@contextmanager
def missing_doc_as_not_found():
    """Translate Firestore's "that document is gone" into this app's 404.

    Closes the TOCTOU gap in every get-then-update service: ownership is read
    first, the write happens second, and the two are not transactional, so a
    doc deleted in between made Firestore raise and the request 500 — where
    404 is both correct and what the caller already gets for a missing id.

    Scoped to the single write call rather than applied globally (a Flask
    errorhandler on the vendor class was considered and rejected): a blanket
    rule would turn EVERY Firestore NotFound anywhere into a user-facing 404.

    ⚠️ CORRECTION (P13 security review). An earlier version of this docstring
    claimed the narrow scope keeps a "misconfigured database" error a loud 500.
    For the wrapped statement that is FALSE, and measurably so: Firestore
    returns NOT_FOUND for both "this document is gone" and "this database does
    not exist", and nothing here can tell them apart. What actually keeps a
    persistent misconfiguration loud is that an UNWRAPPED read (get_owned, or
    users_repo.get) precedes every wrapped write, so the request 500s at the
    read first. That ordering is load-bearing — **keep the ownership read
    OUTSIDE the `with` block.** Widening the scope to cover the read would
    convert a real infrastructure failure into a silent user-facing 404.

    The log line below is what makes the residual case non-silent: an
    infra-level NotFound that appears at the write but not at the preceding
    read (database deleted mid-request, named-database routing change) would
    otherwise emit nothing at all. Path only — never the vendor message, which
    embeds the project id and document path.

    delete() deliberately gets no wrapper: real Firestore's delete is
    idempotent on an already-deleted doc and raises nothing (measured the same
    day), so there is no race to translate.
    """
    try:
        yield
    except FirestoreNotFound as err:
        log.info(
            "firestore NotFound translated to 404 path=%s",
            request.path if has_request_context() else "<no request>",
        )
        raise NotFound() from err


def _wants_json() -> bool:
    # ponytail: path prefix, not blueprint. ARCHITECTURE §3.2 says "by blueprint",
    # but the calendar blueprint serves BOTH an HTML page (`/`) and JSON
    # (`/api/events`), so blueprint granularity cannot express the split. `/api/*`
    # is the same boundary §6's guard table already draws. (The "never match by
    # path" rule in §6 governs CSRF *exemption*, where over-matching is a hole;
    # picking a response content type is not a security boundary.)
    return request.path.startswith("/api/")


def register_error_handlers(app) -> None:
    @app.errorhandler(ValidationError)
    def _on_validation_error(err: ValidationError):
        if _wants_json():
            return jsonify(err.as_dict()), 400
        return err.message, 400

    @app.errorhandler(NotFound)
    def _on_not_found(err: NotFound):
        if _wants_json():
            return jsonify({"error": "not_found", "message": err.message}), 404
        return err.message, 404

    @app.errorhandler(Exception)
    def _on_unexpected(err: Exception):
        # HTTPExceptions (404/405/…) are the framework's normal status codes, not
        # crashes — let them keep their own status. Flask routes them here only
        # because Exception is at the root of their MRO.
        if isinstance(err, HTTPException):
            return err
        # Stack trace + path to the log; never the exception text to the client.
        log.exception("unhandled error path=%s", request.path)
        if _wants_json():
            return jsonify({"error": "internal_error", "message": GENERIC_ERROR_TH}), 500
        return GENERIC_ERROR_TH, 500
