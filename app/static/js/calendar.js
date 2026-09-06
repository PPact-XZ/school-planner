// FullCalendar init + event fetch + logout wiring (ARCHITECTURE §3.2, §3.5,
// Decision 1b). Add/Edit modal and its interactions are P5b — the "+" button
// (calendar.html) stays inert; this file does not touch it.
//
// This is the first real frontend JS beyond auth.js — it holds the line on
// the same rule: render user strings via FullCalendar's default text path,
// NEVER innerHTML. It gets a dedicated XSS review after P5b (auth.js's
// review note in tests/... / progress memory carries the same flag forward).
(function () {
  "use strict";

  function wireLogout() {
    const button = document.getElementById("logout-btn");
    if (!button) {
      return;
    }
    button.addEventListener("click", async function () {
      const meta = document.querySelector('meta[name="csrf-token"]');
      const token = meta ? meta.content : "";
      try {
        await fetch("/logout", {
          method: "POST",
          headers: { "X-CSRF-Token": token },
        });
      } finally {
        // /logout redirects server-side regardless of outcome; navigating
        // here (rather than following the fetch redirect) keeps this a plain
        // browser navigation instead of rendering the login page's HTML
        // inside a fetch response body.
        window.location.href = "/login";
      }
    });
  }

  // P10. Presence/absence of `hidden` is the ONLY state — never paired with a
  // second display utility, which is the trap that shipped a modal at
  // display:block in P5b (CLAUDE.md).
  function toggleBanner(id, visible) {
    const el = document.getElementById(id);
    if (el) {
      el.classList.toggle("hidden", !visible);
    }
  }

  // (E5) Schedule chips deliberately carry no id (events.py emits none), so
  // "this month has a task" is exactly "some event has an id" — a full
  // timetable must not suppress the hint just by making the feed non-empty.
  function hasAnyTask(events) {
    return events.some(function (event) {
      return Boolean(event.id);
    });
  }

  function initCalendar() {
    const el = document.getElementById("calendar");
    if (!el || typeof FullCalendar === "undefined") {
      return;
    }

    const calendar = new FullCalendar.Calendar(el, {
      // Decision 1b. T002 was amended 2026-09-06 to อา-first (Sunday), so
      // this now matches Thai common use rather than fighting it.
      //
      // Set EXPLICITLY anyway, and that is not redundant: the vendored th
      // locale declares week:{dow:1} (Monday), so relying on locale: 'th'
      // would give Monday-first — the opposite of the intuition that "Thai
      // locale means Sunday-first". Deleting this line silently reverts the
      // grid to จ-first.
      //
      // ⚠️ This is DISPLAY ORDER ONLY, and is independent of the stored
      // day_of_week (still 0=Mon..6=Sun, per T002 line 203 and identical to
      // Python's date.weekday()). firstDay picks which column starts the
      // week; fc_day() decides which weekday a chip belongs to. Changing this
      // does NOT move any chip relative to its weekday — measured, not
      // assumed: all 12 chip/schedule browser tests passed unchanged across
      // the flip. Never "fix" fc_day() to compensate for a firstDay change.
      firstDay: 0,
      locale: "th",
      initialView: "dayGridMonth",
      // E6 (P13, tech-lead approved 2026-09-06). T002 line 160 locks the
      // toolbar as ◀ title ▶; "วันนี้" is a deliberate extension of the same
      // species as E1–E5, placed AFTER ▶ so the locked ◀ title ▶ relationship
      // is untouched. Two things it gets for free, both checked not assumed:
      // the Thai label comes from the vendored th locale (`today:"วันนี้"`),
      // and the button inherits FullCalendar's own toolbar chrome exactly as
      // ◀ ▶ do — input.css has no .fc-button rule — so no new Tailwind
      // utility enters the build and app.css needs no rebuild.
      headerToolbar: { left: "prev", center: "title", right: "next today" },
      // Two more th-locale traps found by inspecting the vendored bundle's
      // Intl usage directly (not assumed): (1) dayGridMonth's default
      // dayHeaderFormat is {weekday:'short'}, which under Intl('th') renders
      // full names ("จันทร์") — NOT T002's locked จ/อ/พ/พฤ/ศ/ส/อา. 'narrow'
      // is what produces exactly that locked abbreviation set. (2) Intl's
      // 'th' locale defaults to the Buddhist Era calendar for numeric years
      // (2026 -> "2569") — calendar:'gregory' forces the Gregorian year the
      // locked mockup uses ("มิถุนายน 2026", not "2569").
      dayHeaderFormat: { weekday: "narrow" },
      titleFormat: { year: "numeric", month: "long", calendar: "gregory" },
      // P8: a real timetable puts 4+ periods on every weekday; without a cap
      // the month grid becomes a schedule wall and deadlines vanish. 3 is
      // deliberate (not `true`, which derives the cap from cell height and so
      // varies per viewport). allDay events sort before timed ones under the
      // default eventOrder, so task chips are never the ones collapsed into
      // the "+N more" popover while schedules stay visible.
      dayMaxEvents: 3,
      // T002's mockup chips are text-only, and a phone-width day cell cannot
      // fit "08:30 คณิตศาสตร์" — times live in the ตารางเรียน list instead.
      displayEventTime: false,
      events: function (info, successCallback, failureCallback) {
        const url =
          "/api/events?start=" +
          encodeURIComponent(info.startStr) +
          "&end=" +
          encodeURIComponent(info.endStr);

        fetch(url, { headers: { Accept: "application/json" } })
          .then(function (resp) {
            if (resp.status === 401) {
              // The `/api/*` guard returns 401 JSON on an expired session
              // (never 302) specifically so this branch is reachable — a
              // fetch that ignored it would leave the calendar blank with no
              // explanation.
              window.location.href = "/login";
              return null;
            }
            if (!resp.ok) {
              throw new Error("failed to load events: " + resp.status);
            }
            return resp.json();
          })
          .then(function (events) {
            if (events) {
              toggleBanner("calendar-error", false);
              toggleBanner("calendar-empty", !hasAnyTask(events));
              successCallback(events);
            }
          })
          .catch(function (err) {
            // Before P10 a failed feed left the grid silently blank — the
            // same "no error anywhere" failure §6 already fixed once for the
            // 401 case. The empty hint is hidden too: an unreachable server
            // is not the same claim as "you have no tasks this month".
            toggleBanner("calendar-empty", false);
            toggleBanner("calendar-error", true);
            failureCallback(err);
          });
      },
      eventClick: function (info) {
        if (!info.event.id) {
          // Schedule chips carry no id ON PURPOSE (events.py emits none):
          // there is no schedule detail modal. Without this guard the fetch
          // below would hit /api/tasks/<empty>, 404, and the catch's
          // refetchEvents would fire on every schedule-chip click.
          return;
        }
        // The feed carries only the id (locked: notes/drive_link never enter
        // /api/events) — fetch the full task, then hand it to the detail
        // modal. window.TaskDetail is read at click time, never captured at
        // init: calendar.js loads before modals.js.
        fetch("/api/tasks/" + encodeURIComponent(info.event.id), {
          headers: { Accept: "application/json" },
        })
          .then(function (resp) {
            if (resp.status === 401) {
              window.location.href = "/login";
              return null;
            }
            if (!resp.ok) {
              throw new Error("failed to load task: " + resp.status);
            }
            return resp.json();
          })
          .then(function (task) {
            if (task && window.TaskDetail) {
              window.TaskDetail.open(task);
            }
          })
          .catch(function (err) {
            console.error(err);
            // Self-heal: a chip whose task no longer exists (deleted in
            // another tab, 404) should disappear rather than leave the click
            // with no visible effect. Cheap because /api/events is small and
            // this only runs on a failed chip click, not on every render.
            calendar.refetchEvents();
          });
      },
    });

    // The seam to modals.js (P5b): it dispatches this after a save succeeds,
    // and the calendar refetches /api/events so the new chip appears without
    // a page reload (Flow 2). Keeping it an event means this file stays a
    // closed IIFE — no global calendar instance for anything else to poke.
    document.addEventListener("task-saved", function () {
      calendar.refetchEvents();
    });

    calendar.render();
  }

  wireLogout();
  initCalendar();
})();
