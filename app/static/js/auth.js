// Google Sign-In popup -> Firebase ID token -> POST /sessionLogin (ARCHITECTURE
// §3.2). The real popup is smoke-tested manually once the dev Firebase project
// exists; until then window.__FIREBASE_CONFIG__.apiKey is "" and the button
// stays inert rather than throwing.
(function () {
  "use strict";

  // P12 CSP pre-work: read the config from a data attribute rather than an
  // inline <script>, which an enforcing script-src blocks (see login.html).
  // JSON.parse is not a script sink — it evaluates nothing — and the value is
  // server config from env vars, never user input. The try/catch keeps the old
  // behaviour on a malformed value: stay inert rather than throw.
  function readConfig() {
    const el = document.getElementById("firebase-config");
    if (!el || !el.dataset.config) {
      return {};
    }
    try {
      return JSON.parse(el.dataset.config);
    } catch (err) {
      return {};
    }
  }

  const config = readConfig();
  const button = document.getElementById("google-signin-btn");
  const errorEl = document.getElementById("login-error");

  if (!config.apiKey) {
    return;
  }
  firebase.initializeApp(config);

  // The user-facing copy stays the single Thai line T002 specifies — a login
  // page must never explain WHY it refused. `reason` goes to the console only,
  // and is the error CODE or an HTTP status, never the token, the response
  // body, or the email (CLAUDE.md's never-log list).
  //
  // This exists because four unrelated failures — setPersistence throwing, the
  // popup being blocked or dismissed, getIdToken failing, and /sessionLogin
  // returning non-2xx — all rendered the same sentence with nothing written
  // anywhere. On the one flow that can lock every user out of the app, that
  // made a failure report unactionable: "it says try again" is all anyone
  // could report, including from production.
  function showError(reason) {
    errorEl.textContent = "เข้าสู่ระบบไม่สำเร็จ กรุณาลองใหม่";
    errorEl.classList.remove("hidden");
    console.error("[auth] sign-in failed:", reason);
  }

  button.addEventListener("click", async function () {
    errorEl.classList.add("hidden");
    try {
      // P13. This app uses Firebase's client-side session for exactly one
      // thing: mint an ID token here and exchange it at /sessionLogin. From
      // then on the Flask session cookie is the only credential that matters,
      // so a PERSISTED Firebase session is pure liability — the default
      // (LOCAL) parks an auth record in IndexedDB (firebaseLocalStorageDb)
      // that POST /logout does not touch, so "logging out" on a shared family
      // machine left Firebase's own auth state behind. The DATABASE is created
      // either way by the SDK's availability probe, on the first
      // firebase.auth() call below — so when verifying this by hand, look for
      // the absence of an fbase_key RECORD, not of the database. Bonus,
      // confirmed in the shipped bundle: setPersistence purges the record held
      // under the previous persistence, so a pre-P13 login is cleaned up on
      // the first click here.
      //
      // Persistence.NONE keeps auth state in memory for this page only.
      // Checked against the shipped 10.12.2 compat bundle rather than assumed:
      // it sets `Auth.Persistence = {LOCAL:"local",NONE:"none",SESSION:
      // "session"}`. NONE is safe for the POPUP flow specifically — it is the
      // REDIRECT flow that needs storage to survive navigating away and back.
      //
      // Rejected: calling signOut() from the logout handler. That needs the
      // Firebase SDK loaded on the calendar page too (it is not), widening
      // both the diff and the CSP surface, and it would still leave the token
      // persisted for the entire session up to the moment of logout.
      //
      // Each step below names itself on failure, so a report says which one
      // broke rather than "it says try again".
      try {
        await firebase.auth().setPersistence(firebase.auth.Auth.Persistence.NONE);
      } catch (err) {
        // Deliberately fatal rather than falling through to sign-in: carrying
        // on would silently persist an auth record to IndexedDB, which is the
        // exact thing P13 removed. Failing loudly beats a silent downgrade.
        showError("setPersistence: " + (err && err.code ? err.code : err));
        return;
      }

      const provider = new firebase.auth.GoogleAuthProvider();
      let result;
      try {
        result = await firebase.auth().signInWithPopup(provider);
      } catch (err) {
        // auth/popup-blocked, auth/popup-closed-by-user,
        // auth/unauthorized-domain and auth/cancelled-popup-request all land
        // here and are indistinguishable to the user by design.
        showError("signInWithPopup: " + (err && err.code ? err.code : err));
        return;
      }
      const idToken = await result.user.getIdToken();

      // No X-CSRF-Token here: /sessionLogin is the one CSRF-exempt endpoint
      // (app/security.py) — Origin + Content-Type validation stand in for it
      // because the CSRF token does not exist until this call succeeds.
      const resp = await fetch("/sessionLogin", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ idToken: idToken }),
      });

      if (!resp.ok) {
        // Status only. The body may carry server detail that has no business
        // in a browser console, and the server already logs the real reason.
        showError("/sessionLogin returned " + resp.status);
        return;
      }
      window.location.href = "/";
    } catch (err) {
      showError(err && err.code ? err.code : err);
    }
  });
})();
