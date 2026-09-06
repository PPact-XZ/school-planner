"""Dev entrypoint. Render runs `gunicorn run:app`, so `app` must import cleanly
at module scope while `app.run()` stays behind the __main__ guard (importing
run:app must never start a server)."""

from dotenv import load_dotenv

# Local dev only: pull .env into os.environ before the factory reads it. No-op
# in prod — Render sets real env vars and ships no .env file, so nothing loads.
load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    import os

    # Debug derives from APP_ENV — never a literal True. Production is gunicorn,
    # which imports `app` above and never runs this block.
    debug = app.extensions["app_config"].app_env == "development"
    # PORT is overridable via .env because macOS AirPlay Receiver squats :5000.
    # Default stays 5000 (the design + the Windows teaching repo); Mac dev
    # sets PORT=5001 and APP_ORIGIN to match.
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, port=port)
