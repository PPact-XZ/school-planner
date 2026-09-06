// E1 — ตารางเรียน section on /settings (ARCHITECTURE §2.1 E1, Flow 7, P8
// brief). List fetch/render, add/edit/delete against /api/schedules. One
// render path: the list is always JS-fetched and JS-rendered (no
// server-rendered rows to drift against). Same standing rule as every other
// file here: user-controlled strings reach the DOM through .value and
// .textContent ONLY, never innerHTML — `room` survives clean_str with
// < > " ' intact and must never cross an HTML-parsing sink.
(function () {
  "use strict";

  var GENERIC_ERROR_TH = "เกิดข้อผิดพลาด กรุณาลองใหม่";
  var DELETE_CONFIRM_TH = "ลบคาบเรียนนี้ถาวร?";
  // P10 loading indicators — in-place label swap on the control already being
  // disabled, matching modals.js. No spinner markup, so no layout shift.
  var SAVING_TH = "กำลังบันทึก...";
  var DELETING_TH = "กำลังลบ...";

  var section = document.getElementById("schedules-section");
  if (!section) {
    // Loads only on /settings, but the bail-out guard matches the house
    // style (calendar.js, modals.js, settings.js).
    return;
  }

  var listEl = document.getElementById("schedules-list");
  var emptyEl = document.getElementById("schedules-empty");
  var form = document.getElementById("schedule-form");
  var titleEl = document.getElementById("schedule-form-title");
  var subjectSelect = document.getElementById("schedule-subject");
  var daySelect = document.getElementById("schedule-day");
  var startInput = document.getElementById("schedule-start");
  var endInput = document.getElementById("schedule-end");
  var roomInput = document.getElementById("schedule-room");
  var saveBtn = document.getElementById("schedule-save");
  var cancelBtn = document.getElementById("schedule-cancel");
  var generalError = document.getElementById("schedule-form-error");

  // The last-fetched list (server-ordered day_of_week, start_time — this
  // file never sorts) and the current form mode: null = add (POST), an id =
  // edit (PUT /api/schedules/<id>).
  var records = [];
  var editingId = null;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.content : "";
  }

  function dayLabel(d) {
    // The rendered <option>s ARE the label source (constants.DAY_LABELS_TH,
    // rendered server-side) — never define a second label list here.
    return daySelect.querySelector('option[value="' + d + '"]').textContent;
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
      // build from a caller-chosen unknown-field name — CSS.escape it before
      // it composes into a selector.
      var slot = form.querySelector('[data-error-for="' + CSS.escape(name) + '"]');
      // A validation_error field need not correspond to an input:
      // create_schedule raises one on "limit" when the per-user cap is hit.
      (slot || generalError).textContent = fields[name];
    });
  }

  function resetForm() {
    editingId = null;
    form.reset();
    titleEl.textContent = "เพิ่มคาบเรียน";
    cancelBtn.classList.add("hidden");
    clearErrors();
  }

  function beginEdit(rec) {
    editingId = rec.id;
    subjectSelect.value = rec.subject;
    daySelect.value = String(rec.day_of_week);
    startInput.value = rec.start_time;
    endInput.value = rec.end_time;
    roomInput.value = rec.room;
    titleEl.textContent = "แก้ไขคาบเรียน";
    cancelBtn.classList.remove("hidden");
    clearErrors();
  }

  function deleteRow(id) {
    fetch("/api/schedules/" + encodeURIComponent(id), {
      method: "DELETE",
      headers: { "X-CSRF-Token": csrfToken() },
    })
      .then(function (resp) {
        if (resp.status === 401 || resp.status === 403) {
          // See loadList()'s comment: 403 means "log in again" here, not a
          // CSRF failure to retry.
          window.location.href = "/login";
          return null;
        }
        if (!resp.ok) {
          throw new Error("failed to delete schedule: " + resp.status);
        }
        // 204 No Content — never call resp.json() on an empty body.
        if (editingId === id) {
          // Deleting the row currently being edited must not leave a ghost
          // PUT armed against a doc that no longer exists.
          resetForm();
        }
        return true;
      })
      .then(function (ok) {
        if (ok) {
          loadList();
        }
      })
      .catch(function () {
        generalError.textContent = GENERIC_ERROR_TH;
        renderList();
      });
  }

  function renderRow(rec) {
    var li = document.createElement("li");
    li.className = "flex items-center justify-between gap-2 py-2";

    var label = document.createElement("span");
    label.className = "text-sm text-gray-800";
    var text = dayLabel(rec.day_of_week) + " " + rec.start_time + "–" + rec.end_time + " · " + rec.subject;
    if (rec.room) {
      text += " · " + rec.room;
    }
    label.textContent = text;
    li.appendChild(label);

    var actions = document.createElement("div");
    actions.className = "flex gap-2";

    function showActionButtons() {
      actions.textContent = "";

      var editBtn = document.createElement("button");
      editBtn.type = "button";
      editBtn.className = "text-sm bg-gray-200 text-gray-700 rounded px-2 py-1";
      editBtn.textContent = "แก้ไข";
      editBtn.addEventListener("click", function () {
        beginEdit(rec);
      });

      var deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "text-sm bg-red-100 text-red-700 rounded px-2 py-1";
      deleteBtn.textContent = "ลบ";
      deleteBtn.addEventListener("click", showConfirmButtons);

      actions.appendChild(editBtn);
      actions.appendChild(deleteBtn);
    }

    function showConfirmButtons() {
      actions.textContent = "";

      var confirmLabel = document.createElement("span");
      confirmLabel.className = "text-sm text-red-700";
      confirmLabel.textContent = DELETE_CONFIRM_TH;

      var noBtn = document.createElement("button");
      noBtn.type = "button";
      noBtn.className = "text-sm bg-gray-200 text-gray-700 rounded px-2 py-1";
      noBtn.textContent = "ยกเลิก";
      noBtn.addEventListener("click", showActionButtons);

      var yesBtn = document.createElement("button");
      yesBtn.type = "button";
      yesBtn.className = "text-sm bg-red-100 text-red-700 rounded px-2 py-1";
      yesBtn.textContent = "ลบ";
      yesBtn.addEventListener("click", function () {
        yesBtn.disabled = true;
        yesBtn.textContent = DELETING_TH;
        // No label restore here: deleteRow() re-renders the whole list on
        // both outcomes, so this button does not survive the call.
        deleteRow(rec.id);
      });

      actions.appendChild(confirmLabel);
      actions.appendChild(noBtn);
      actions.appendChild(yesBtn);
    }

    showActionButtons();
    li.appendChild(actions);
    return li;
  }

  function renderList() {
    listEl.textContent = "";
    if (records.length === 0) {
      emptyEl.classList.remove("hidden");
      return;
    }
    emptyEl.classList.add("hidden");
    records.forEach(function (rec) {
      listEl.appendChild(renderRow(rec));
    });
  }

  function loadList() {
    fetch("/api/schedules", { headers: { Accept: "application/json" } })
      .then(function (resp) {
        if (resp.status === 401 || resp.status === 403) {
          // 401 JSON on an expired session (the /api/* trap — never a 302).
          // 403 is included deliberately: PERMANENT_SESSION_LIFETIME equals
          // the session's ABSOLUTE_MAX_SECONDS, and the app-wide CSRF hook
          // runs BEFORE the auth guard on unsafe methods — a 403 here on a
          // bare GET is unreachable in practice (GET skips the CSRF hook),
          // but pairing it anyway keeps one pattern at all three fetch
          // sites in this file (modals.js::handleFailure carries the same
          // reasoning for its own three sites).
          window.location.href = "/login";
          return null;
        }
        if (!resp.ok) {
          throw new Error("failed to load schedules: " + resp.status);
        }
        return resp.json();
      })
      .then(function (json) {
        if (json) {
          records = json;
          renderList();
        }
      })
      .catch(function () {
        generalError.textContent = GENERIC_ERROR_TH;
      });
  }

  function payload() {
    return {
      subject: subjectSelect.value,
      // The Number("") trap: an unselected day must NOT become 0 (Monday).
      // "" dies at the validator with the Thai day_of_week message in the
      // right slot; 0 would silently create a Monday period.
      day_of_week: daySelect.value === "" ? null : Number(daySelect.value),
      start_time: startInput.value,
      end_time: endInput.value,
      room: roomInput.value,
    };
  }

  function handleFailure(resp) {
    if (resp.status === 401 || resp.status === 403) {
      // 401 JSON, never a 302. 403 is included deliberately, not a CSRF
      // failure to retry: PERMANENT_SESSION_LIFETIME equals the session's
      // ABSOLUTE_MAX_SECONDS (app/config.py, app/auth/session.py), so the
      // cookie stops being sent at the same moment the server-side window
      // closes. The CSRF before_request hook runs BEFORE the auth guard, so
      // it finds no expected token first and 403s — the 401 branch never
      // fires on ordinary expiry for this POST/PUT. On this app, 403 here
      // means "log in again", not "retry the request." Do not simplify this
      // back to 401-only (modals.js::handleFailure carries the same
      // reasoning).
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
        generalError.textContent = GENERIC_ERROR_TH;
      }
    );
  }

  function submit(event) {
    event.preventDefault();
    clearErrors();
    // Captured, not hardcoded: this button's label is state-dependent
    // (เพิ่ม / บันทึก, set by resetForm/edit), so a fixed restore string
    // would silently relabel it after the first edit.
    var previousLabel = saveBtn.textContent;
    saveBtn.disabled = true;
    saveBtn.textContent = SAVING_TH;

    var url = editingId
      ? "/api/schedules/" + encodeURIComponent(editingId)
      : "/api/schedules";

    fetch(url, {
      method: editingId ? "PUT" : "POST",
      headers: {
        // Both load-bearing: no Content-Type -> request.get_json() yields
        // nothing -> 400 on a "missing" field; no token -> the app-wide CSRF
        // hook 403s before the view runs.
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify(payload()),
    })
      .then(function (resp) {
        if (!resp.ok) {
          return handleFailure(resp);
        }
        // The server's list, not a local splice, is what renders next —
        // fewest assumptions, and it also picks up the server's ordering.
        resetForm();
        loadList();
      })
      .catch(function () {
        generalError.textContent = GENERIC_ERROR_TH;
      })
      .finally(function () {
        saveBtn.disabled = false;
        // resetForm() on the success path already restored the correct
        // label; only overwrite when the busy text is still showing.
        if (saveBtn.textContent === SAVING_TH) {
          saveBtn.textContent = previousLabel;
        }
      });
  }

  form.addEventListener("submit", submit);
  cancelBtn.addEventListener("click", resetForm);

  loadList();
})();
