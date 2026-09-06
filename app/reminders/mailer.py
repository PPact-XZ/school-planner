"""Resend HTTP API adapter (Decision 2 addendum).

Render blocks outbound traffic to SMTP ports 25/465/587 on free web services
(since 2025-09-26 — https://render.com/changelog/free-web-services-will-no-longer-allow-outbound-traffic-to-smtp-ports),
which is what the original Gmail-SMTP mailer used. Resend's send-email
endpoint is a plain HTTPS POST (port 443, not blocked), so this adapter talks
to it directly via the stdlib rather than adding a new dependency for one
JSON request.

Adapter layer (omitted from the coverage gate). It does exactly one thing:
send a single already-composed message over HTTPS and classify the failure.
The RETRY POLICY lives in service.py on purpose — retry is business logic and
belongs where the coverage gate can see it, not in an omitted module.

Four properties here are load-bearing, not style:

1. `context=ssl.create_default_context()` is passed explicitly to the opener's
   `HTTPSHandler`, even though `urlopen` verifies TLS by default on `https://`
   URLs (confirmed: `ssl._create_default_https_context is ssl.create_default_context`).
   This repo's rule is to assume nothing about a stdlib default that concerns
   TLS and measure it instead — the same reasoning that caught `smtplib.SMTP_SSL`
   silently skipping verification without an explicit context.
2. `timeout=` is REQUIRED. Unset, an HTTPS request blocks on the socket
   indefinitely, which outlives gunicorn's `--timeout 120` and pins one of its
   8 threads. Eight hung sends is a total outage — same hazard the old SMTP
   timeout guarded against.
3. Redirects are declined, not followed. `urlopen`'s default `HTTPRedirectHandler`
   follows 301/302/303 on POST (re-issued as GET) and forwards `req.headers` —
   including `Authorization` — to whatever host the response names. A custom
   opener with `_NoRedirect` turns any 3xx into an `HTTPError` instead, so the
   API key can never be replayed cross-host and a redirected 2xx can never be
   mistaken for a successful send.
4. An explicit `User-Agent` and `Accept` header are REQUIRED. `urlopen`'s
   default `User-Agent: Python-urllib/3.x` with no `Accept` header at all was
   confirmed live to trip Cloudflare's bot-signature check fronting Resend's
   API: every send from Render was blocked with Cloudflare error 1010 (banned
   by browser signature) before the request ever reached Resend, while an
   identical request from a real browser/curl succeeded — nothing to do with
   the API key, domain, or from-address, all of which were independently
   confirmed correct first. An honest, identifying User-Agent fixed it; do
   not spoof a browser's UA string instead.
"""

import http.client
import json
import ssl
import urllib.error
import urllib.request

RESEND_API_URL = "https://api.resend.com/emails"
REQUEST_TIMEOUT_SECONDS = 20
SENDER_DISPLAY_NAME = "School Planner"

# 429 (rate limited) and 5xx (Resend-side trouble) are worth a retry; every
# other 4xx (bad/revoked key, unverified sender domain, malformed payload)
# will fail identically on a retry.
_TRANSIENT_HTTP_CODES = {429}


class SendError(Exception):
    """A send failed. Carries no recipient address — see the note below."""


class TransientSendError(SendError):
    """Retrying may succeed: timeout, dropped connection, 429, 5xx."""


class PermanentSendError(SendError):
    """Retrying cannot help: bad/revoked API key, unverified sender, 4xx (non-429)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Declining (returning None) makes urllib fall through to the default
    error handler, which raises HTTPError — already classified below."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ResendMailer:
    def __init__(self, api_key: str, from_email: str):
        # from_email is config-sourced (a Render env var), not per-request —
        # validated once here rather than on every send. It rides inside a
        # composite header value (f"{name} <{from_email}>"), where a stray
        # '>' or CRLF restructures the header, not just one address.
        if "\r" in from_email or "\n" in from_email or ">" in from_email:
            raise ValueError("invalid RESEND_FROM_EMAIL")
        self._api_key = api_key
        self._from = from_email
        self._opener = urllib.request.build_opener(
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )

    def send(self, to: str, subject: str, body: str) -> None:
        # Structural guard: EmailMessage used to refuse a CRLF in a header
        # value, which made header injection impossible regardless of what
        # service.py scrubbed. json.dumps would happily escape a raw \r\n
        # into the request body instead of raising, so that sink is gone
        # unless this check replaces it. `to` is normally a trusted
        # Firebase-Admin-SDK lookup, not user input, but the check is cheap
        # defense-in-depth given `subject` already needs it.
        for field in (subject, to):
            if "\r" in field or "\n" in field:
                raise PermanentSendError("malformed field (control character)")

        try:
            payload = json.dumps(
                {
                    "from": f"{SENDER_DISPLAY_NAME} <{self._from}>",
                    "to": [to],
                    "subject": subject,
                    "text": body,
                }
            ).encode("utf-8")

            request = urllib.request.Request(
                RESEND_API_URL,
                data=payload,
                method="POST",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    # urllib's default User-Agent ("Python-urllib/3.x") sends
                    # no Accept header and is a well-known trigger for
                    # Cloudflare's bot-signature check, which fronts Resend's
                    # API — confirmed live: requests from Render were blocked
                    # with Cloudflare error 1010 before ever reaching Resend,
                    # while an identical request from a real browser/curl
                    # succeeded. An honest, identifying User-Agent is the fix,
                    # not a spoofed one.
                    "User-Agent": "SchoolPlanner-Reminders/1.0",
                },
            )

            with self._opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS):
                pass
        except (ValueError, TypeError) as err:
            # Construction-side failure, not a network one. Inside the try on
            # purpose, mirroring the old mailer's reasoning: an uncaught
            # ValueError/TypeError here would escape _send_with_retry
            # (SendError only) and leave this task's ledger doc stuck at
            # "sending" forever.
            raise PermanentSendError(f"malformed request ({type(err).__name__})") from err
        except urllib.error.HTTPError as err:
            # Caught BEFORE the broad clause below — HTTPError is a URLError
            # subclass, which is itself an OSError subclass. Status code
            # only, never err.read(): Resend's error body can echo the `to`
            # address, and §8 forbids logging addresses.
            if err.code in _TRANSIENT_HTTP_CODES or err.code >= 500:
                raise TransientSendError(f"HTTP {err.code}") from err
            raise PermanentSendError(f"HTTP {err.code}") from err
        except (urllib.error.URLError, OSError, ssl.SSLError, http.client.HTTPException) as err:
            # Disconnects, DNS failures, refused connections, TLS handshake
            # failures, socket timeouts, and malformed/truncated HTTP framing
            # (http.client.HTTPException — NOT an OSError subclass, and easy
            # to miss carrying over an SMTP-shaped exception tuple that never
            # had to think about it). All worth another attempt.
            raise TransientSendError(
                f"transient network failure ({type(err).__name__})"
            ) from err
