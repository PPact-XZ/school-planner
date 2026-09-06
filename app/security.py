"""CSRF hook, security headers, rate limiting, ProxyFix (ARCHITECTURE §6).

The CSRF hook is app-wide (@app.before_request), NOT blueprint-scoped — a
blueprint-scoped hook would leave /api/* unguarded while every existing test
still passed. Default-deny on unsafe methods; exempt by request.endpoint
(never by path — path matching is prefix-fragile and silently over-exempts).
"""

import hmac
import logging

from flask import current_app, jsonify, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from app.auth.session import csrf_token

log = logging.getLogger(__name__)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Exempt by endpoint, hardcoded — a url_map meta-test (tests/meta/) fails the
# moment a new unsafe endpoint appears that isn't accounted for here or in
# that test's own explicit list, so nobody can silently opt out of CSRF.
# auth.session_login is the one P3 exemption: it has no CSRF token yet (the
# token is minted BY this call), so it is guarded instead by a
# Content-Type + Origin check (auth/routes.py). reminders.run is the P9
# exemption: it is called by a GitHub Actions cron that has no browser, no
# session and therefore no CSRF token at all — it is guarded instead by the
# X-Reminder-Token shared secret (reminders/routes.py::token_required), and
# tests/meta/test_internal_auth_coverage.py proves every /internal/* route
# carries that guard.
CSRF_EXEMPT_ENDPOINTS = frozenset({"auth.session_login", "reminders.run"})

# Anti-noise, not a security boundary (ARCHITECTURE §6): in-memory storage
# means cold starts wipe every counter and counts never span gunicorn
# workers/instances. The real boundaries are the allowlist, this CSRF hook,
# and (P9) the reminder trigger token. storage_uri is explicit so the choice
# reads as deliberate rather than an unconfigured fallback.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["120/minute"],
    storage_uri="memory://",
)

# CSP. Permissive enough for the Firebase JS SDK (gstatic) and the Google auth
# popup/frames. Whether it is ENFORCED or merely reported is env-driven
# (config.csp_enforce) so the P12 rollout can be staged and, critically, rolled
# back by unsetting one Render variable — no code deploy on a cold-starting
# free instance while login is broken.
#
# script-src has never included 'unsafe-inline', which is why login.html's
# Firebase config had to move to a data attribute before this could be enforced
# at all (P12 pre-work).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    # https://apis.google.com is Google Identity's gapi_iframes cross-window
    # messaging helper, loaded during the real popup sign-in flow — confirmed
    # via a live Report-Only console log during P12 prod smoke test, not
    # assumed. Missing this would silently break Google Sign-In the moment
    # CSP_ENFORCE flips to true.
    "script-src 'self' https://www.gstatic.com https://apis.google.com; "
    # 'unsafe-inline' is KEPT for styles, deliberately. FullCalendar's bundle
    # injects an empty <style> at runtime and fills it via CSSOM; blocking the
    # element leaves .sheet null and the bundle throws, which BLANKS the
    # calendar rather than merely unstyling it. It can be dropped via the
    # bundle's meta[name="csp-nonce"] hook, but that is a 6.1.15 implementation
    # detail to re-verify on every bump, and the app has no user-controlled
    # style sink (the P6 XSS review found no `.style` writes anywhere).
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    # FullCalendar's icon font is a data: URI. font-src does NOT fall back to
    # default-src's 'self' for it, so without this the locked ◀ ▶ arrows lose
    # their glyphs the moment CSP is enforced.
    "font-src 'self' data:; "
    "connect-src 'self' https://*.googleapis.com; "
    "frame-src https://*.firebaseapp.com https://accounts.google.com; "
    # Neither of these falls back to default-src. base-uri stops an injected
    # <base> from re-pointing every relative URL; form-action stops a form
    # being retargeted at an attacker's host.
    "base-uri 'self'; "
    "form-action 'self'"
)


def _csrf_check():
    if request.method not in UNSAFE_METHODS:
        return None

    endpoint = request.endpoint
    if endpoint is None:
        # No route matched — let dispatch_request raise its stored 404. There
        # is nothing to protect and nothing in CSRF_EXEMPT_ENDPOINTS to check.
        return None
    # csrf_extra_exempt: an app-instance-scoped extension point, set ONLY by
    # tests/conftest.py when it registers tests/support's session-minting
    # blueprint (which has no prior session to carry a CSRF token yet). Empty
    # by default, so a bare create_app() — production's only path — is
    # unaffected; the tests/meta/ CSRF-coverage guard builds exactly that bare
    # app and never sees this key set.
    extra_exempt = current_app.extensions.get("csrf_extra_exempt", frozenset())
    if endpoint in CSRF_EXEMPT_ENDPOINTS or endpoint in extra_exempt:
        return None

    token = request.headers.get("X-CSRF-Token", "")
    expected = session.get("csrf_token", "")
    if not expected or not hmac.compare_digest(token, expected):
        log.warning("csrf check failed endpoint=%s", endpoint)
        return jsonify({"error": "csrf_failed"}), 403
    return None


def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    config = current_app.extensions["app_config"]
    # Report-Only by default; CSP_ENFORCE=true promotes it. Staged on purpose —
    # an enforcing policy that is wrong makes the sign-in button inert, and the
    # rollback must not require a redeploy.
    csp_header = (
        "Content-Security-Policy"
        if config.csp_enforce
        else "Content-Security-Policy-Report-Only"
    )
    response.headers[csp_header] = CONTENT_SECURITY_POLICY

    if session.get("uid"):
        response.headers["Cache-Control"] = "no-store"

    if config.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


def register_security(app) -> None:
    # x_for=3, measured against the live prod chain (P12 step 7): Render sits
    # behind Cloudflare, and X-Forwarded-For always carries exactly 3 trailing
    # trusted entries — Cloudflare's observed client IP, a Cloudflare-internal
    # hop, and Render's own LB — regardless of request content. x_for=1
    # (ProxyFix's own conservative default) was CONFIRMED wrong: it landed on
    # Render's internal LB address for every request, collapsing
    # get_remote_address's rate-limit key to one shared bucket across all
    # users.
    #
    # Adversarially confirmed, not just observed once: a live request with a
    # forged `X-Forwarded-For: 1.2.3.4` prefix still resolved to the real
    # client IP. ProxyFix indexes from the right (`values[-3]`), and the 3
    # trusted hops always append at the tail, so front-injected junk changes
    # the list's length but never reaches position -3 — spoofing this way
    # doesn't work on this ingress path. (The limiter is documented anti-noise
    # above, not an auth boundary, so even a successful spoof here would only
    # degrade the rate limit, never bypass auth.)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=3, x_proto=1)

    limiter.init_app(app)
    app.before_request(_csrf_check)
    app.after_request(_security_headers)
    # base.html reads a bare `csrf_token` Jinja variable into its <meta> tag
    # (P0) — Flask does not auto-expose session contents under that name, so
    # every render needs this context processor to populate it.
    app.context_processor(lambda: {"csrf_token": csrf_token()})
