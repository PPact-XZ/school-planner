"""Firebase Admin SDK init (guarded, once) and get_db().

Adapter layer — omitted from the coverage gate (.coveragerc); exercised by the
opt-in `pytest -m firestore` round-trip and by real deploys. One code path for
both credential mechanisms (Decision 4): FIREBASE_CREDENTIALS_JSON wins if set,
else the file at FIREBASE_CREDENTIALS_PATH.
"""

import json

import firebase_admin
from firebase_admin import credentials, firestore

_app = None


def _build_credentials(config):
    if config.firebase_credentials_json:
        return credentials.Certificate(json.loads(config.firebase_credentials_json))
    return credentials.Certificate(config.firebase_credentials_path)


def init_app(config):
    """Initialise the default Admin app exactly once. firebase_admin raises on a
    second default init, so the module-global guard is load-bearing under
    gunicorn's import-once, multi-thread model."""
    global _app
    if _app is None:
        _app = firebase_admin.initialize_app(_build_credentials(config))
    return _app


def get_db(config):
    init_app(config)
    return firestore.client()
