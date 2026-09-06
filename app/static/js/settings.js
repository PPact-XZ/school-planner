// Settings page (T002 Screen 5, ARCHITECTURE §2.5, P7 brief): the
// notify_enabled auto-save toggle (Flow 5 / A-F18 — no บันทึก button, an
// inline "บันทึกแล้ว" confirmation fades instead) and logout wiring for both
// of this page's logout buttons (navbar #logout-btn + Screen 5's own
// #settings-logout). All strings that reach the DOM here are fixed Thai
// literals; user data (name/email) never enters this file — the server
// already rendered them as autoescaped text nodes (see partials/_navbar.html
// and settings.html).
(function () {
  "use strict";

  var GENERIC_ERROR_TH = "เกิดข้อผิดพลาด กรุณาลองใหม่";

  var checkbox = document.getElementById("settings-notify");
  if (!checkbox) {
    // Loads only on /settings, but the bail-out guard matches the house
    // style (calendar.js, modals.js).
    return;
  }

  var savedEl = document.getElementById("settings-saved");
  var errorEl = document.getElementById("settings-error");

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function wireLogout(id) {
    var button = document.getElementById(id);
    if (!button) {
      return;
    }
    button.addEventListener("click", async function () {
      try {
        await fetch("/logout", {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken() },
        });
      } finally {
        // /logout redirects server-side regardless of outcome; navigating
        // here (rather than following the fetch redirect) keeps this a
        // plain browser navigation instead of rendering the login page's
        // HTML inside a fetch response body (calendar.js::wireLogout).
        window.location.href = "/login";
      }
    });
  }

  // The server-rendered truth at load (settings.html's boolean `checked`
  // conditional) — the revert target if a save ever fails.
  var lastKnown = checkbox.checked;
  var fadeTimer = null;

  // P10: this control is a checkbox, so there is no label to swap the way
  // modals.js/schedules.js swap a button's. The confirmation span carries the
  // busy state instead — and because it is role="status", a screen reader
  // announces "กำลังบันทึก..." then "บันทึกแล้ว" rather than nothing at all.
  // SAVED_TH is captured from the template so the two can never drift.
  var SAVED_TH = savedEl.textContent;
  var SAVING_TH = "กำลังบันทึก...";

  function showSaving() {
    clearTimeout(fadeTimer);
    savedEl.textContent = SAVING_TH;
    savedEl.classList.remove("opacity-0");
  }

  function hideStatus() {
    clearTimeout(fadeTimer);
    savedEl.classList.add("opacity-0");
    // Clear the text too, not just the opacity. opacity-0 hides it visually
    // but leaves it in the accessibility tree, so a screen-reader user
    // landing on this span after a FAILED save would still be told
    // "กำลังบันทึก..." — measured in a real browser, where the text survived
    // the fade. Only the failure path calls this; the ordinary 1.5s fade
    // after a successful save adds opacity-0 directly and keeps its text.
    savedEl.textContent = "";
  }

  function showSaved() {
    clearTimeout(fadeTimer);
    savedEl.textContent = SAVED_TH;
    savedEl.classList.remove("opacity-0");
    // The span's own `transition-opacity duration-500` does the animation;
    // this only flips the class after a beat. Never pair opacity-0 with an
    // opacity-100 class — presence/absence of opacity-0 is the only state
    // (CLAUDE.md same-property trap).
    fadeTimer = setTimeout(function () {
      savedEl.classList.add("opacity-0");
    }, 1500);
  }

  function onChange() {
    var next = checkbox.checked;
    errorEl.textContent = "";
    // A rapid re-toggle restarts the fade cleanly instead of stacking timers
    // (showSaving clears it).
    showSaving();
    // P10 (P7 review, deferred): disabling a focused control moves focus to
    // <body>, so a keyboard user toggling with Space lost their place after
    // every save and had to Tab back from the top. The disable itself is
    // load-bearing — it is what prevents overlapping PUTs — so the fix is to
    // restore focus afterwards rather than to stop disabling.
    var hadFocus = document.activeElement === checkbox;
    checkbox.disabled = true;

    fetch("/api/settings", {
      method: "PUT",
      headers: {
        // Both load-bearing: no Content-Type → request.get_json() yields
        // nothing → 400; no token → the app-wide CSRF hook 403s first.
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify({ notify_enabled: next }),
    })
      .then(function (resp) {
        if (resp.status === 401 || resp.status === 403) {
          // 401 JSON on an expired session (the /api/* trap — never a 302).
          // 403 is included deliberately, not a CSRF failure to retry:
          // PERMANENT_SESSION_LIFETIME equals the session's
          // ABSOLUTE_MAX_SECONDS (app/config.py, app/auth/session.py), so
          // the cookie stops being sent at the same moment the server-side
          // window closes. The CSRF before_request hook runs BEFORE the
          // auth guard, so it finds no expected token and 403s — the 401
          // branch never fires on ordinary expiry for this PUT. On this
          // app, 403 here means "log in again", not "retry the request."
          // Do not simplify this back to 401-only (modals.js::handleFailure
          // carries the same reasoning).
          window.location.href = "/login";
          return null;
        }
        if (!resp.ok) {
          throw new Error("failed to save settings: " + resp.status);
        }
        return resp.json();
      })
      .then(function (doc) {
        if (doc) {
          // The server's echo, not the local assumption, is what renders —
          // locked decision 3.
          lastKnown = doc.notify_enabled === true;
          checkbox.checked = lastKnown;
          showSaved();
        }
      })
      .catch(function () {
        // The UI never displays a preference that did not persist.
        checkbox.checked = lastKnown;
        // Clear the busy text before showing the error — leaving
        // "กำลังบันทึก..." beside a failure message would claim a save is
        // still in flight when it has already failed.
        hideStatus();
        errorEl.textContent = GENERIC_ERROR_TH;
      })
      .finally(function () {
        // Disabling during flight is also what prevents overlapping PUTs.
        checkbox.disabled = false;
        if (hadFocus) {
          // Only when it WAS focused: never steal focus from wherever the
          // user has moved to while the request was in flight.
          checkbox.focus();
        }
      });
  }

  checkbox.addEventListener("change", onChange);
  wireLogout("logout-btn");
  wireLogout("settings-logout");
})();
