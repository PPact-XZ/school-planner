// P5b — Add/Edit Task modal (T002 Screen 3), wired to the /api/tasks CRUD
// that P4 already ships and tests (ARCHITECTURE §3.5).
//
// Same standing rule as auth.js and calendar.js, and the reason this file is
// written the way it is: user-controlled strings reach the DOM through
// .value and .textContent ONLY, never innerHTML. Server error messages are
// Thai copy from app/errors.py, but they travel the same escaped path — the
// rule is about the channel, not about trusting the source.
(function () {
  "use strict";

  var GENERIC_ERROR_TH = "เกิดข้อผิดพลาด กรุณาลองใหม่";
  // P10 loading indicator. In-place label swap on the control already being
  // disabled — no spinner markup, so nothing here can shift the layout.
  var SAVING_TH = "กำลังบันทึก...";

  var modal = document.getElementById("task-modal");
  var form = document.getElementById("task-form");
  if (!modal || !form) {
    return;
  }

  var heading = document.getElementById("task-modal-title");
  var saveButton = document.getElementById("task-save");
  var generalError = document.getElementById("task-form-error");

  // Field id ←→ locked Firestore field name. All five keys are always sent:
  // validate_task_payload rejects unknown fields BEFORE reading any of them,
  // and T002 locks "" (not null) for an absent drive_link/notes.
  var FIELDS = {
    title: "task-title",
    subject: "task-subject",
    deadline: "task-deadline",
    drive_link: "task-drive-link",
    notes: "task-notes",
  };

  // null = add mode (POST). A task id = edit mode (PUT /api/tasks/<id>).
  var editingId = null;

  function input(name) {
    return document.getElementById(FIELDS[name]);
  }

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function clearErrors() {
    var slots = form.querySelectorAll("[data-error-for]");
    for (var i = 0; i < slots.length; i++) {
      slots[i].textContent = "";
    }
    generalError.textContent = "";
  }

  function showFieldErrors(fields) {
    Object.keys(fields).forEach(function (name) {
      // name comes from the API's fields{} object, which validators.py can
      // build from a caller-chosen unknown-field name (sorted(unknown)[0]) —
      // CSS.escape it before it composes into a selector.
      var slot = form.querySelector('[data-error-for="' + CSS.escape(name) + '"]');
      // A validation_error field need not correspond to an input: create_task
      // raises one on "limit" when the per-user task cap is hit. Falling back
      // to the general slot is what keeps that message visible at all.
      (slot || generalError).textContent = fields[name];
    });
  }

  function open(task) {
    clearErrors();
    editingId = task ? task.id : null;
    heading.textContent = task ? "แก้ไขงาน" : "เพิ่มงาน";

    Object.keys(FIELDS).forEach(function (name) {
      input(name).value = task ? task[name] || "" : "";
    });

    // hidden ⇄ flex, never both: see the note in _task_modal.html.
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    input("title").focus();
  }

  function close() {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    editingId = null;
    form.reset();
    clearErrors();
  }

  function payload() {
    var body = {};
    Object.keys(FIELDS).forEach(function (name) {
      body[name] = input(name).value;
    });
    return body;
  }

  function handleFailure(resp) {
    if (resp.status === 401 || resp.status === 403) {
      // 401 JSON, never a 302 — see the /api/* trap in calendar.js. 403 is
      // included deliberately, not a CSRF failure to retry: PERMANENT_SESSION_
      // LIFETIME equals the session's ABSOLUTE_MAX_SECONDS (app/config.py,
      // app/auth/session.py), so the cookie stops being sent at the same
      // moment the server-side window closes. _csrf_check runs as a
      // before_request hook BEFORE the auth guard, so it finds no expected
      // token first and 403s — the 401 branch never fires on ordinary expiry
      // for POST/PUT/DELETE. On this app, 403 here means "log in again", not
      // "retry the request." Do not simplify this back to 401-only.
      window.location.href = "/login";
      return null;
    }
    return resp.json().then(
      function (data) {
        if (data && data.fields) {
          showFieldErrors(data.fields);
        } else {
          generalError.textContent = (data && data.message) || GENERIC_ERROR_TH;
        }
      },
      function () {
        // Body was not JSON (a proxy error page, a truncated response).
        generalError.textContent = GENERIC_ERROR_TH;
      }
    );
  }

  function submit(event) {
    event.preventDefault();
    clearErrors();
    // P10: the label is captured here rather than hardcoded, so it can never
    // drift from the template (the same reason the BADGE_BASE drift test
    // exists). Restored in finally() only if it is still the busy text, so a
    // success path that legitimately relabels the button is not clobbered.
    var previousLabel = saveButton.textContent;
    saveButton.disabled = true;
    saveButton.textContent = SAVING_TH;

    var url = editingId ? "/api/tasks/" + encodeURIComponent(editingId) : "/api/tasks";

    fetch(url, {
      method: editingId ? "PUT" : "POST",
      headers: {
        // Both are load-bearing. Without X-CSRF-Token the app-wide hook 403s
        // before the view runs; without Content-Type, request.get_json()
        // yields {} and a filled-in form comes back as "ชื่องานห้ามว่าง".
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(payload()),
    })
      .then(function (resp) {
        if (!resp.ok) {
          return handleFailure(resp);
        }
        close();
        // calendar.js owns the FullCalendar instance and stays a closed IIFE;
        // this event is the whole seam between the two files.
        document.dispatchEvent(new CustomEvent("task-saved"));
      })
      .catch(function () {
        generalError.textContent = GENERIC_ERROR_TH;
      })
      .finally(function () {
        saveButton.disabled = false;
        if (saveButton.textContent === SAVING_TH) {
          saveButton.textContent = previousLabel;
        }
      });
  }

  var addButton = document.getElementById("add-task-btn");
  if (addButton) {
    addButton.addEventListener("click", function () {
      open(null);
    });
  }

  document.getElementById("task-cancel").addEventListener("click", close);
  form.addEventListener("submit", submit);

  // Click the dark overlay (not the card) to dismiss, and Escape to dismiss —
  // the two ways a user expects to leave a modal without saving.
  modal.addEventListener("click", function (event) {
    if (event.target === modal) {
      close();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modal.classList.contains("hidden")) {
      // Close only the topmost layer: the detail modal's own Escape listener
      // registers after this one and would otherwise see this modal as already
      // hidden and close itself on the SAME keypress.
      event.stopImmediatePropagation();
      close();
    }
  });

  // Screen 4's "แก้ไข" button (P6) opens edit mode through this. It is the
  // only export; nothing else in this file is reachable from outside.
  window.TaskModal = { open: open };
})();

// P6 — Task Detail modal (T002 Screen 4) + E3 delete. A second, separate
// closed IIFE: the only bridge to the IIFE above is window.TaskModal.open
// and the "task-saved" DOM event, deliberately — see the module docstring's
// rule about user strings reaching the DOM (.textContent/.href only, never
// innerHTML). Registration order matters: this file's first IIFE (TaskModal)
// attaches its keydown listener before this one, which is what makes the
// stopImmediatePropagation() above close only the topmost modal layer.
(function () {
  "use strict";

  var GENERIC_ERROR_TH = "เกิดข้อผิดพลาด กรุณาลองใหม่";
  var BADGE_BASE = "inline-block text-sm px-3 py-1 rounded-full whitespace-nowrap";
  // P10 loading indicators (see the Add/Edit IIFE above for the rationale).
  var SAVING_TH = "กำลังบันทึก...";
  var DELETING_TH = "กำลังลบ...";

  var modalEl = document.getElementById("task-detail-modal");
  if (!modalEl) {
    return;
  }

  var titleEl = document.getElementById("detail-title");
  var statusEl = document.getElementById("detail-status");
  var subjectEl = document.getElementById("detail-subject");
  var deadlineEl = document.getElementById("detail-deadline");
  var driveRowEl = document.getElementById("detail-drive-row");
  var driveLinkEl = document.getElementById("detail-drive-link");
  var notesRowEl = document.getElementById("detail-notes-row");
  var notesEl = document.getElementById("detail-notes");
  var errorEl = document.getElementById("detail-error");
  var actionsEl = document.getElementById("detail-actions");
  var editButton = document.getElementById("detail-edit");
  var toggleSubmitButton = document.getElementById("detail-toggle-submit");
  var deleteButton = document.getElementById("detail-delete");
  var deleteConfirmEl = document.getElementById("detail-delete-confirm");
  var deleteYesButton = document.getElementById("detail-delete-yes");
  var deleteNoButton = document.getElementById("detail-delete-no");

  // The full task dict last rendered; null when the modal is closed. This is
  // the only state this IIFE holds — everything else is read from the DOM.
  var currentTask = null;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function renderBadge(submitted) {
    // The className is REPLACED wholesale, never patched: bg-yellow-100 and
    // bg-green-100 are both background-color, the same same-property trap
    // documented in CLAUDE.md for hidden/flex.
    if (submitted) {
      statusEl.className = BADGE_BASE + " bg-green-100 text-green-800";
      statusEl.textContent = "ส่งแล้ว";
      toggleSubmitButton.textContent = "ยกเลิกการส่ง";
    } else {
      statusEl.className = BADGE_BASE + " bg-yellow-100 text-yellow-800";
      statusEl.textContent = "ยังไม่ส่ง";
      toggleSubmitButton.textContent = "ส่งงานแล้ว";
    }
  }

  function render(task) {
    currentTask = task;
    titleEl.textContent = task.title;
    subjectEl.textContent = task.subject;
    deadlineEl.textContent = task.deadline; // raw YYYY-MM-DD, no formatting
    renderBadge(task.submitted);

    // The server-side host allowlist in validate_task_payload is the
    // primary control on this value; this scheme check is defense in depth
    // on the one place it reaches a live href sink. A drive_link that isn't
    // https:// (shouldn't exist, but the CSP is Report-Only and would not
    // block a javascript: navigation) is treated as absent.
    var driveLink = /^https:\/\//i.test(task.drive_link || "") ? task.drive_link : "";
    if (driveLink) {
      driveRowEl.classList.remove("hidden");
      driveLinkEl.href = driveLink;
      driveLinkEl.textContent = driveLink;
    } else {
      driveRowEl.classList.add("hidden");
      // href = "" does not clear the anchor — .href then resolves to the
      // current page URL. removeAttribute leaves the element genuinely inert
      // (the row is hidden regardless, but this closes the gap honestly).
      driveLinkEl.removeAttribute("href");
      driveLinkEl.textContent = "";
    }

    if (task.notes) {
      notesRowEl.classList.remove("hidden");
      notesEl.textContent = task.notes;
    } else {
      notesRowEl.classList.add("hidden");
      notesEl.textContent = "";
    }
  }

  function showActionsRow() {
    actionsEl.classList.remove("hidden");
    actionsEl.classList.add("flex");
    deleteConfirmEl.classList.add("hidden");
    deleteConfirmEl.classList.remove("flex");
  }

  function showDeleteConfirmRow() {
    deleteConfirmEl.classList.remove("hidden");
    deleteConfirmEl.classList.add("flex");
    actionsEl.classList.add("hidden");
    actionsEl.classList.remove("flex");
  }

  function open(task) {
    errorEl.textContent = "";
    showActionsRow();
    render(task);

    modalEl.classList.remove("hidden");
    modalEl.classList.add("flex");
    toggleSubmitButton.focus();
  }

  function close() {
    modalEl.classList.add("hidden");
    modalEl.classList.remove("flex");
    currentTask = null;
  }

  function toggleSubmit() {
    var url =
      "/api/tasks/" +
      encodeURIComponent(currentTask.id) +
      (currentTask.submitted ? "/unsubmit" : "/submit");

    // This button's label is state-dependent (ส่งงาน / ยกเลิกการส่ง) and the
    // success path calls render(), which sets the correct one. Restoring only
    // when the text is still SAVING_TH is what keeps those two from fighting.
    var previousLabel = toggleSubmitButton.textContent;
    toggleSubmitButton.disabled = true;
    toggleSubmitButton.textContent = SAVING_TH;
    fetch(url, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken() },
    })
      .then(function (resp) {
        if (resp.status === 401 || resp.status === 403) {
          // Session-expired-as-403 on this POST: see handleFailure()'s
          // comment above for why the CSRF hook gets there before 401 does.
          window.location.href = "/login";
          return null;
        }
        if (!resp.ok) {
          throw new Error("failed to toggle submit: " + resp.status);
        }
        return resp.json();
      })
      .then(function (doc) {
        if (!doc) {
          return;
        }
        render(doc); // modal stays open, flips in place
        document.dispatchEvent(
          new CustomEvent("task-saved", { detail: { source: "detail" } })
        );
      })
      .catch(function () {
        errorEl.textContent = GENERIC_ERROR_TH;
      })
      .finally(function () {
        toggleSubmitButton.disabled = false;
        if (toggleSubmitButton.textContent === SAVING_TH) {
          toggleSubmitButton.textContent = previousLabel;
        }
      });
  }

  function deleteTask() {
    var previousLabel = deleteYesButton.textContent;
    deleteYesButton.disabled = true;
    deleteYesButton.textContent = DELETING_TH;
    fetch("/api/tasks/" + encodeURIComponent(currentTask.id), {
      method: "DELETE",
      headers: { "X-CSRF-Token": csrfToken() },
    })
      .then(function (resp) {
        if (resp.status === 401 || resp.status === 403) {
          // Session-expired-as-403 on this DELETE: see handleFailure()'s
          // comment above for why the CSRF hook gets there before 401 does.
          window.location.href = "/login";
          return;
        }
        if (!resp.ok) {
          throw new Error("failed to delete task: " + resp.status);
        }
        // 204 No Content — never call resp.json() on an empty body.
        close();
        document.dispatchEvent(
          new CustomEvent("task-saved", { detail: { source: "detail" } })
        );
      })
      .catch(function () {
        errorEl.textContent = GENERIC_ERROR_TH;
        showActionsRow();
      })
      .finally(function () {
        deleteYesButton.disabled = false;
        if (deleteYesButton.textContent === DELETING_TH) {
          deleteYesButton.textContent = previousLabel;
        }
      });
  }

  editButton.addEventListener("click", function () {
    // The detail modal stays open underneath (Flow 4's decided mechanism) —
    // stacking is DOM order only, no hide/reopen state machine.
    window.TaskModal.open(currentTask);
  });

  toggleSubmitButton.addEventListener("click", toggleSubmit);

  deleteButton.addEventListener("click", showDeleteConfirmRow);
  deleteNoButton.addEventListener("click", showActionsRow);
  deleteYesButton.addEventListener("click", deleteTask);

  modalEl.addEventListener("click", function (event) {
    if (event.target === modalEl) {
      close();
    }
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !modalEl.classList.contains("hidden")) {
      // P8: dayMaxEvents makes the "+N more" popover reachable, and its own
      // Escape handler registers at mount time — AFTER this listener. Without
      // stopping propagation here, one Escape with this modal open over a
      // popover would close both on the same keypress. Mirrors the first
      // IIFE's TaskModal Escape branch above, which already had this call
      // because a modal already existed after it (this one) to protect.
      event.stopImmediatePropagation();
      close();
    }
  });

  // Flow 4: after แก้ไข saves over this open detail view, re-fetch and
  // re-render in place. Ignore our own dispatch (source: "detail") and
  // ignore it entirely while this modal isn't the one open.
  document.addEventListener("task-saved", function (event) {
    if (event.detail && event.detail.source === "detail") {
      return;
    }
    if (modalEl.classList.contains("hidden") || !currentTask) {
      return;
    }
    fetch("/api/tasks/" + encodeURIComponent(currentTask.id), {
      headers: { Accept: "application/json" },
    })
      .then(function (resp) {
        if (resp.status === 401) {
          window.location.href = "/login";
          return null;
        }
        if (!resp.ok) {
          throw new Error("failed to refresh task: " + resp.status);
        }
        return resp.json();
      })
      .then(function (task) {
        if (task) {
          render(task);
        }
      })
      .catch(function (err) {
        // The calendar already refetched; do not put a scary error in a
        // modal the user didn't touch.
        console.error(err);
      });
  });

  window.TaskDetail = { open: open };
})();
