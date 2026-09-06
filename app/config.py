"""Environment loading with fail-fast validation.

Errors name the missing variable and NEVER print its value — a config error
lands in logs that are not a secret store.
"""

import re
from dataclasses import dataclass, field

VALID_APP_ENVS = ("development", "production")
MAX_CONTENT_LENGTH = 64 * 1024
SESSION_LIFETIME_DAYS = 7

# Public, client-side Firebase identifiers (not secrets — safe in the browser).
# Each maps 1:1 to a firebaseConfig key the JS SDK expects (P3, login.html).
_FIREBASE_WEB_CONFIG_ENV_KEYS = {
    "apiKey": "FIREBASE_API_KEY",
    "authDomain": "FIREBASE_AUTH_DOMAIN",
    "projectId": "FIREBASE_PROJECT_ID",
    "storageBucket": "FIREBASE_STORAGE_BUCKET",
    "messagingSenderId": "FIREBASE_MESSAGING_SENDER_ID",
    "appId": "FIREBASE_APP_ID",
}


class ConfigError(Exception):
    """Startup configuration is invalid. Raised before the app can serve."""


@dataclass(frozen=True)
class Config:
    app_env: str
    secret_key: str
    allowed_emails: tuple[str, ...]
    firebase_credentials_path: str | None
    firebase_credentials_json: str | None
    max_content_length: int = MAX_CONTENT_LENGTH
    # Defaulted (not positional-required): tests/live/test_firestore_roundtrip.py
    # constructs Config(...) directly and predates P3, so every new field needs
    # a default or that call site breaks. load_config() below still fails fast
    # on a missing APP_ORIGIN in the real env-loading path — the default only
    # protects direct Config(...) construction in tests.
    app_origin: str = ""
    firebase_web_config: dict = field(default_factory=dict)
    # P9 reminders — defaulted and validated at USE time, not via _require().
    # Making these startup-required would stop `python run.py` booting for any
    # .env written before P9, and only the daily reminder job needs them. The
    # checks that matter still exist, they just live at the endpoint: an
    # absent or weak trigger token 401s, and an absent Resend config 503s the
    # run BEFORE any ledger doc is claimed (so a misconfigured deploy cannot
    # burn every task's at-most-once slot on a send it never attempted).
    reminder_trigger_token: str = ""
    resend_api_key: str = ""
    resend_from_email: str = ""
    # P12: promote CSP from Report-Only to enforcing. Env-driven and defaulted
    # OFF so the rollout is staged and reversible by unsetting one Render
    # variable — a wrong policy makes the sign-in button inert, and needing a
    # code deploy to undo that is the wrong position to be in.
    csp_enforce: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


def _require(env: dict, name: str) -> str:
    value = env.get(name, "")
    if not value.strip():
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _parse_allowlist(raw: str) -> tuple[str, ...]:
    emails = tuple(e.strip().lower() for e in raw.split(",") if e.strip())
    if not emails:
        # An empty allowlist must never degrade to "allow everyone" (Decision 7).
        raise ConfigError("ALLOWED_EMAILS must list at least one address")
    return emails


def _parse_credentials(env: dict) -> tuple[str | None, str | None]:
    """Decision 4: FIREBASE_CREDENTIALS_JSON wins if set, so the Render
    Secret-File → env-JSON fallback is an env change, not a code change."""
    raw_json = env.get("FIREBASE_CREDENTIALS_JSON", "").strip()
    if raw_json:
        return None, raw_json
    return _require(env, "FIREBASE_CREDENTIALS_PATH"), None


def _parse_firebase_web_config(env: dict) -> dict:
    # Optional — the dev Firebase project does not exist yet (P3 ships before
    # P1's real project is wired for this app's client config), so failing
    # fast here would block create_app() entirely. Unset keys are just "" and
    # login.html renders an inert button until the real values land.
    return {
        key: env.get(env_key, "").strip()
        for key, env_key in _FIREBASE_WEB_CONFIG_ENV_KEYS.items()
    }


def load_config(env: dict) -> Config:
    app_env = _require(env, "APP_ENV")
    if app_env not in VALID_APP_ENVS:
        # Decision 8: "test" is invalid, not magic — no env string unlocks anything.
        raise ConfigError(
            f"APP_ENV must be one of {list(VALID_APP_ENVS)}"
        )

    secret_key = _require(env, "FLASK_SECRET_KEY")
    if not re.fullmatch(r"[0-9a-fA-F]{64,}", secret_key):
        # The git-committed .env.example placeholder ("replace-with-...") is
        # non-blank, so _require's check alone lets it pass startup and sign
        # sessions with a known key — forging the allowlisted user's cookie
        # and defeating both the allowlist and CSRF. Require the
        # secrets.token_hex(32) shape instead. Never echo the value here.
        raise ConfigError(
            "FLASK_SECRET_KEY must be a hex string of at least 64 chars, "
            "e.g. secrets.token_hex(32)"
        )

    path, raw_json = _parse_credentials(env)
    return Config(
        app_env=app_env,
        secret_key=secret_key,
        allowed_emails=_parse_allowlist(_require(env, "ALLOWED_EMAILS")),
        firebase_credentials_path=path,
        firebase_credentials_json=raw_json,
        # APP_ORIGIN guards /sessionLogin's Origin check (§6) — "SameSite=Lax
        # covers login CSRF" is false, so this is the real defense and must
        # fail fast rather than silently compare against "".
        app_origin=_require(env, "APP_ORIGIN").strip(),
        firebase_web_config=_parse_firebase_web_config(env),
        reminder_trigger_token=env.get("REMINDER_TRIGGER_TOKEN", "").strip(),
        resend_api_key=env.get("RESEND_API_KEY", "").strip(),
        resend_from_email=env.get("RESEND_FROM_EMAIL", "").strip(),
        # Strict allowlist, not truthiness: an unset var, "", "0", "no" or a
        # typo must all leave CSP in Report-Only. Silently enforcing because
        # someone wrote CSP_ENFORCE=maybe would take the app down.
        csp_enforce=env.get("CSP_ENFORCE", "").strip().lower() in ("1", "true", "yes"),
    )
