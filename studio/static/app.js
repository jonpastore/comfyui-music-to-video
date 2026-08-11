// Minimal SSE watcher for job progress -- no htmx-sse extension needed.
function watchJob(jobId, targetId) {
  var el = document.getElementById(targetId);
  if (!el || !jobId) return;
  var es = new EventSource("/jobs/" + jobId + "/stream");
  es.onmessage = function (e) {
    var data = JSON.parse(e.data);
    el.textContent = "job #" + data.id + " (" + (data.status || "") + "): " +
      (data.error || data.progress || "");
    if (data.status === "done" || data.status === "failed" || data.status === "cancelled") {
      es.close();
      // No surprise reload. The line reports the outcome and offers the refresh;
      // an automatic one threw away whatever you were typing in a textarea.
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Refresh to see the results";
      btn.className = "linkish";
      btn.style.marginLeft = "0.6rem";
      btn.addEventListener("click", function () { location.reload(); });
      el.appendChild(btn);
    }
  };
  es.onerror = function () { es.close(); };
}

// Drag-to-reorder, for a table of rows OR a horizontal timeline of blocks.
// One handler keyed off data-reorder-url rather than the playlist endpoint, and
// off data-axis rather than assuming vertical, so the set editor's table and its
// timeline share it instead of keeping two copies that drift. Native HTML5 drag
// and drop -- a sortable library would be a dependency for one dragover handler
// and a POST. DOM order is the source of truth; on drop the new order of ids is
// posted and the server renumbers positions.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("[data-reorder-url]").forEach(function (root) {
    // a table reorders its rows, anything else reorders its own children
    var body = root.tBodies ? root.tBodies[0] : root;
    var horizontal = root.dataset.axis === "x";
    var dragging = null;
    var kids = function () {
      return Array.prototype.filter.call(body.children, function (c) {
        return c.dataset && c.dataset.item !== undefined;
      });
    };

    body.addEventListener("dragstart", function (e) {
      dragging = e.target.closest("[data-item]");
      if (dragging) dragging.classList.add("dragging");
      if (e.dataTransfer) e.dataTransfer.setData("text/plain", "");
    });

    body.addEventListener("dragover", function (e) {
      e.preventDefault();
      var over = e.target.closest("[data-item]");
      if (!dragging || !over || over === dragging || over.parentNode !== body) return;
      var rect = over.getBoundingClientRect();
      var after = horizontal ? (e.clientX - rect.left) > rect.width / 2
                             : (e.clientY - rect.top) > rect.height / 2;
      body.insertBefore(dragging, after ? over.nextSibling : over);
    });

    body.addEventListener("dragend", function () {
      if (!dragging) return;
      dragging.classList.remove("dragging");
      dragging = null;
      var items = kids();
      var ids = items.map(function (r) { return r.dataset.item; });
      items.forEach(function (r, i) {
        var pos = r.querySelector(".pos");
        if (pos) pos.textContent = i + 1;
      });
      var form = new FormData();
      form.append("order", ids.join(","));
      var post = fetch(root.dataset.reorderUrl, {method: "POST", body: form});
      // Opt-in reload: the table updates itself in place, but the timeline's
      // block widths and its transition markers are server-rendered, so leaving
      // them stale after a drop would show a set that is not the saved one.
      if (root.dataset.reload !== undefined) post.then(function () { location.reload(); });
    });
  });
});

// Clicking a timeline block reveals the DJ controls for that item: the controls
// live below the timeline, and with a long set the one you just clicked is
// otherwise somewhere off screen.
document.addEventListener("click", function (e) {
  var block = e.target.closest(".tl-block");
  if (!block) return;
  var panel = document.getElementById("item-" + block.dataset.item);
  if (!panel) return;
  document.querySelectorAll(".tl-block").forEach(function (b) {
    b.classList.toggle("active", b === block);
  });
  panel.scrollIntoView({behavior: "smooth", block: "center"});
  panel.classList.add("just-focused");
  setTimeout(function () { panel.classList.remove("just-focused"); }, 1600);
});

// Delegated confirm for tier deletion -- kept out of an inline onsubmit="..."
// attribute so a tier name can never be interpreted as JS (add_tier restricts
// names to isidentifier(), which still allows Unicode identifier chars).
document.addEventListener("submit", function (e) {
  var tierForm = e.target.closest(".delete-tier");
  if (tierForm && !confirm("Delete tier " + tierForm.dataset.tier + "?")) {
    e.preventDefault();
    return;
  }
  var songForm = e.target.closest(".delete-song");
  if (songForm && !confirm("Permanently delete this song and all its generated files?")) {
    e.preventDefault();
  }
  // Deleting a playlist is behind a real modal now (playlists.html), which
  // lists what goes and what stays -- a one-line confirm() could not.
  var groupForm = e.target.closest(".delete-anchor-group");
  if (groupForm && !confirm("Delete every unpicked candidate in this group? " +
                            "The chosen one is kept.")) {
    e.preventDefault();
    return;
  }
  var anchorForm = e.target.closest(".delete-anchor");
  if (anchorForm) {
    // The CHOSEN one is deletable -- refusing it was impossible advice for a
    // group with only one candidate -- but the cost is stated, because
    // reference generation for that tier stops until another is chosen.
    var msg = anchorForm.dataset.chosen
      ? "Delete the CHOSEN anchor? The file is removed too, and reference " +
        "generation for this tier will refuse until you pick or generate another."
      : "Delete this anchor candidate? The file is removed too.";
    if (!confirm(msg)) { e.preventDefault(); return; }
  }
  var targetForm = e.target.closest(".delete-target");
  if (targetForm && !confirm("Remove this publishing destination?")) {
    e.preventDefault();
    return;
  }
  var setForm = e.target.closest(".delete-set");
  if (setForm && !confirm("Delete this rendered set? The songs and their own videos stay.")) {
    e.preventDefault();
    return;
  }
  // Deleting a base image is a submit with formaction rather than its own form
  // -- a nested form inside the generate form is invalid HTML -- so the check
  // is on the SUBMITTER, not on the form.
  if (e.submitter && e.submitter.classList.contains("delete-ref") &&
      !confirm("Delete this base image? The file is removed too. Sheets already " +
               "generated from it are not affected.")) {
    e.preventDefault();
    return;
  }
  var charForm = e.target.closest(".delete-character");
  if (charForm && !confirm("Delete character " + charForm.dataset.name +
                           "? Their anchor rows go too; the image files stay on disk.")) {
    e.preventDefault();
  }
});

// Switching the storyboard tier re-defaults the direction box from that tier's
// wording, which would throw away a brief you had already written. htmx fires
// htmx:confirm before every request, so the swap is held until the question is
// answered -- and only asked when the text is actually dirty (a textarea's
// defaultValue is exactly what the server rendered).
document.body.addEventListener("htmx:confirm", function (e) {
  var sel = e.target;
  if (!sel.matches || !sel.matches("#sb-form select[name=tier]")) return;
  var ta = document.querySelector("#sb-form textarea[name=direction]");
  if (!ta || ta.value === ta.defaultValue) return;      // untouched: just swap
  e.preventDefault();
  if (confirm("Switching tier reloads the default direction and discards your edits. Continue?")) {
    e.detail.issueRequest();
  } else {
    sel.value = sel.dataset.current;                     // put the select back
  }
});

// ---- inpaint mask painter -------------------------------------------------
// Paint white where the model may repaint, on black. The mask is produced at
// the image's NATURAL size, not the size it happens to be displayed at, because
// the workflow feeds it to InpaintModelConditioning alongside the unscaled
// frame -- a mask at CSS pixel size would be offset from the pixels it masks.
function paintMask(form) {
  var src = form.dataset.src;
  var img = new Image();
  img.onload = function () {
    var dlg = document.createElement("dialog");
    dlg.className = "mask-dialog";
    var canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    var ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0);

    // the mask itself, kept separate from what is shown: the visible canvas is
    // the frame plus a red overlay so you can see where you are painting.
    var mask = document.createElement("canvas");
    mask.width = canvas.width;
    mask.height = canvas.height;
    var mctx = mask.getContext("2d");
    mctx.fillStyle = "#000";
    mctx.fillRect(0, 0, mask.width, mask.height);

    var bar = document.createElement("div");
    bar.className = "modal-bar";
    bar.innerHTML = "<strong>Paint the area to repair</strong>";
    var size = document.createElement("input");
    size.type = "range"; size.min = "8"; size.max = "200"; size.value = "48";
    var clear = document.createElement("button");
    clear.type = "button"; clear.textContent = "Clear";
    var done = document.createElement("button");
    done.type = "button"; done.textContent = "Use this mask";
    var cancel = document.createElement("button");
    cancel.type = "button"; cancel.textContent = "Cancel";
    bar.append(size, clear, done, cancel);
    dlg.append(bar, canvas);
    document.body.appendChild(dlg);
    dlg.showModal();

    var painting = false;
    function at(e) {
      var r = canvas.getBoundingClientRect();
      return {x: (e.clientX - r.left) * (canvas.width / r.width),
              y: (e.clientY - r.top) * (canvas.height / r.height)};
    }
    function dab(e) {
      if (!painting) return;
      var p = at(e), r = Number(size.value);
      mctx.fillStyle = "#fff";
      mctx.beginPath(); mctx.arc(p.x, p.y, r, 0, Math.PI * 2); mctx.fill();
      ctx.fillStyle = "rgba(247, 118, 142, 0.5)";
      ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2); ctx.fill();
    }
    canvas.addEventListener("pointerdown", function (e) { painting = true; dab(e); });
    canvas.addEventListener("pointermove", dab);
    window.addEventListener("pointerup", function () { painting = false; });

    clear.addEventListener("click", function () {
      mctx.fillStyle = "#000"; mctx.fillRect(0, 0, mask.width, mask.height);
      ctx.drawImage(img, 0, 0);
    });
    cancel.addEventListener("click", function () { dlg.close(); dlg.remove(); });
    done.addEventListener("click", function () {
      form.querySelector("[name=mask_data]").value = mask.toDataURL("image/png");
      form.querySelector(".js-mask-state").textContent = "mask ready";
      form.querySelector(".js-mask-submit").disabled = false;
      dlg.close(); dlg.remove();
    });
  };
  img.src = src;
}

document.addEventListener("click", function (e) {
  var btn = e.target.closest(".js-paint-mask");
  if (btn) paintMask(btn.closest(".mask-form"));
});

// ---- click a column heading to sort a list table --------------------------
// data-k on a cell when the sort key is not what the cell reads: seconds behind
// "3:04", a unix time behind a formatted date. Empty cells always sort LAST in
// both directions -- otherwise sorting by length buries every song that has one
// under the ones that do not.
document.addEventListener("click", function (e) {
  var th = e.target.closest("table.sortcols th[data-sort]");
  if (!th) return;
  var table = th.closest("table");
  var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
  var dir = th.classList.contains("sort-asc") ? -1 : 1;
  table.querySelectorAll("th").forEach(function (h) {
    h.classList.remove("sort-asc", "sort-desc");
  });
  th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
  var body = table.tBodies[0];
  var rows = Array.prototype.slice.call(body.rows);
  rows.sort(function (a, b) {
    var x = a.cells[idx], y = b.cells[idx];
    var xk = x.dataset.k, yk = y.dataset.k;
    if (xk !== undefined && yk !== undefined) {
      var xn = parseFloat(xk), yn = parseFloat(yk);
      if (isNaN(xn) !== isNaN(yn)) return isNaN(xn) ? 1 : -1;
      if (!isNaN(xn)) return (xn - yn) * dir;
    }
    var xt = x.textContent.trim().toLowerCase(), yt = y.textContent.trim().toLowerCase();
    if (!xt !== !yt) return xt ? -1 : 1;
    return xt.localeCompare(yt) * dir;
  });
  rows.forEach(function (r) { body.appendChild(r); });
});

// ---- anchor sheets: tabs, filter, viewer, repair --------------------------
document.addEventListener("click", function (e) {
  // tier tabs: the panels are already rendered, so this is a class swap
  var tab = e.target.closest(".tier-tab");
  if (tab) {
    var album = tab.closest(".tier-tabs").dataset.album;
    document.querySelectorAll('.tier-tab').forEach(function (t) {
      if (t.closest(".tier-tabs").dataset.album === album) t.classList.remove("active");
    });
    tab.classList.add("active");
    document.querySelectorAll('.tier-panel[data-album="' + album + '"]').forEach(function (p) {
      p.classList.toggle("hidden", p.dataset.tier !== tab.dataset.tier);
    });
    return;
  }

  // a sheet opens beside its opposite view -- a character sheet is read as a
  // pair, front checked against back
  var img = e.target.closest(".anchor-open");
  if (img) {
    var dlg = document.getElementById("anchor-lightbox");
    var pair = document.getElementById("lightbox-pair");
    document.getElementById("lightbox-label").textContent =
      (img.dataset.label || "").replace(/&middot;/g, "·");
    pair.innerHTML = "";
    [img.dataset.full, img.dataset.opposite].forEach(function (src) {
      if (!src) return;
      var full = document.createElement("img");
      full.src = src;
      pair.appendChild(full);
    });
    dlg.showModal();
    return;
  }

  var edit = e.target.closest(".anchor-edit");
  if (edit) {
    var fix = document.getElementById("anchor-fix");
    document.getElementById("fix-label").textContent =
      (edit.dataset.label || "").replace(/&middot;/g, "·");
    var preview = document.getElementById("fix-preview");
    preview.src = edit.dataset.src;
    // every form in the modal posts to THIS anchor
    fix.querySelectorAll("form").forEach(function (f) {
      f.action = "/anchors/" + edit.dataset.anchor + "/fix";
    });
    // the mask painter reads the source off the form it belongs to
    var maskForm = fix.querySelector(".mask-form");
    if (maskForm) {
      maskForm.dataset.src = edit.dataset.src;
      maskForm.querySelector("[name=mask_data]").value = "";
      maskForm.querySelector(".js-mask-state").textContent = "nothing painted yet";
      maskForm.querySelector(".js-mask-submit").disabled = true;
    }
    fix.showModal();
  }
});

// show only one character's sheets. They are already on the page, so hiding is
// cheaper and more responsive than re-querying for a subset.
document.addEventListener("change", function (e) {
  var sel = e.target.closest(".anchor-character-filter");
  if (!sel) return;
  var scope = sel.closest("details") || document;
  scope.querySelectorAll(".anchor-tile").forEach(function (tile) {
    tile.classList.toggle("hidden", sel.value && tile.dataset.character !== sel.value);
  });
});

// Timestamps are rendered as UTC and converted HERE. The server runs UTC and
// this is read from a machine that does not, so formatting server-side would
// show a time nobody is in.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("time.local-time").forEach(function (el) {
    var d = new Date(el.getAttribute("datetime"));
    if (isNaN(d)) return;
    el.textContent = d.toLocaleString(undefined, {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit"});
    el.title = el.getAttribute("datetime") + " (UTC)";
  });
});

// ---- keyboard review ------------------------------------------------------
// Fifty frames is a lot of mousing. J/K move, A approves the focused clip, R
// rerolls it. Ignored while typing, or the reroll note would trigger both.
document.addEventListener("keydown", function (e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  var t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" ||
            t.isContentEditable)) return;
  var tiles = Array.prototype.slice.call(document.querySelectorAll(".clip-tile"));
  if (!tiles.length) return;
  var cur = document.activeElement && document.activeElement.closest(".clip-tile");
  var i = cur ? tiles.indexOf(cur) : -1;
  var key = e.key.toLowerCase();

  if (key === "j" || key === "k") {
    e.preventDefault();
    var next = tiles[Math.min(tiles.length - 1, Math.max(0, i + (key === "j" ? 1 : -1)))];
    if (i === -1) next = tiles[0];
    next.focus();
    next.scrollIntoView({block: "nearest"});
  } else if (key === "a" && cur) {
    e.preventDefault();
    var approve = cur.querySelector(".js-approve");
    if (approve) approve.click();
  } else if (key === "r" && cur) {
    e.preventDefault();
    // focus the note rather than firing immediately: a reroll costs GPU, and a
    // stray keypress that silently queues four renders is a bad trade
    var note = cur.querySelector(".js-reroll-note");
    if (note) note.focus();
  }
});

// Subgenre select filtered by the chosen genre, driven by the #genre-data
// JSON blob the template embeds (no framework, no extra request).
function initGenreSelects(genreId, subgenreId) {
  var genreEl = document.getElementById(genreId);
  var subEl = document.getElementById(subgenreId);
  var dataEl = document.getElementById("genre-data");
  if (!genreEl || !subEl || !dataEl) return;
  var genres = JSON.parse(dataEl.textContent);
  function refresh() {
    var subs = genres[genreEl.value] || [];
    subEl.innerHTML = "";
    subEl.appendChild(new Option("(none)", ""));
    subs.forEach(function (s) { subEl.appendChild(new Option(s, s)); });
  }
  genreEl.addEventListener("change", refresh);
  refresh();
}

document.addEventListener("DOMContentLoaded", function () {
  initGenreSelects("genre-select", "subgenre-select");
  initGenreSelects("genre2-select", "subgenre2-select");
  initGenreSelects("bulk-genre-select", "bulk-subgenre-select");
  initGenreSelects("bulk-genre2-select", "bulk-subgenre2-select");
  initLibraryBulk();
});

// ---- the one way this app talks to the server from a button ----------------
// Every Library control goes through here: same Accept header, same error
// extraction, same promise shape. app.py answers JSON to this and a redirect to
// a plain form post, so the page still works with JavaScript off -- one set of
// routes serving both, rather than a parallel /api/* tree to keep in step.
//
// body: a plain object -> JSON, a FormData -> multipart (uploads), omitted -> GET.
function api(url, body, method) {
  var opts = {method: method || (body === undefined ? "GET" : "POST"),
              headers: {"Accept": "application/json"}};
  if (body instanceof FormData) {
    opts.body = body;                       // let the browser set the boundary
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  return fetch(url, opts).then(function (r) {
    if (r.status === 204) return {};
    return r.text().then(function (t) {
      var d;
      try { d = t ? JSON.parse(t) : {}; } catch (err) { d = {detail: t.slice(0, 200)}; }
      // FastAPI puts the readable reason in `detail`; surfacing r.statusText
      // instead is how "409 a job is running for this song" became "Conflict".
      if (!r.ok) throw new Error(d.detail || d.error || r.statusText);
      return d;
    });
  });
}

// ---- Library: select rows, apply a genre to all of them, analyse in place ---
// Everything here talks JSON to app.py and paints from the RESPONSE, never from
// what was typed -- a value the server drops in validation must not stay on
// screen looking saved.
function initLibraryBulk() {
  var bar = document.getElementById("bulk-genre");
  if (!bar) return;
  var all = document.getElementById("pick-all");
  var count = document.getElementById("bulk-count");
  var note = document.getElementById("bulk-note");
  var val = function (id) { var e = document.getElementById(id); return e ? e.value : ""; };

  // rows currently SHOWN. Sorting reorders and a filter could hide; either way
  // "select all" must never reach a row the user cannot see.
  function shown() {
    return Array.prototype.filter.call(
      document.querySelectorAll("tr[data-song]"),
      function (r) { return r.offsetParent !== null; });
  }
  function picked() {
    return shown().filter(function (r) { return r.querySelector(".pick-song").checked; });
  }
  function refresh() {
    var n = picked().length;
    count.textContent = n ? n + " song" + (n === 1 ? "" : "s") + " selected"
                          : "no songs selected";
    var vis = shown();
    all.checked = vis.length > 0 && n === vis.length;
    all.indeterminate = n > 0 && n < vis.length;
  }
  function ids() { return picked().map(function (r) { return Number(r.dataset.song); }); }

  all.addEventListener("change", function () {
    shown().forEach(function (r) { r.querySelector(".pick-song").checked = all.checked; });
    refresh();
  });
  document.addEventListener("change", function (e) {
    if (e.target.classList && e.target.classList.contains("pick-song")) refresh();
  });

  function paintGenre(row, g) {
    var cell = row.querySelector(".cell-genre");
    if (!cell) return;
    var first = g.genre + (g.subgenre ? " / " + g.subgenre : "");
    var second = g.genre2 ? g.genre2 + (g.subgenre2 ? " / " + g.subgenre2 : "") : "";
    cell.textContent = first;
    if (second) { cell.appendChild(document.createElement("br")); cell.append(second); }
  }
  var post = api;
  function busy(on, msg) { note.textContent = msg || ""; bar.classList.toggle("busy", !!on); }

  // Upload: same route, same validation, but the Library stays where it is and
  // asks for the row it just made rather than following a redirect away.
  var upload = document.querySelector('form[action="/songs"]');
  if (upload) upload.addEventListener("submit", function (e) {
    e.preventDefault();
    var btn = upload.querySelector('button[type="submit"]');
    btn.disabled = true;
    busy(true, "uploading…");
    api("/songs", new FormData(upload))
      .then(function (d) {
        // the ROW comes from the server's own partial, not from markup rebuilt
        // here -- so it can never drift from what the table renders
        return fetch("/songs/" + d.song_id + "/row").then(function (r) { return r.text(); })
          .then(function (html) {
            var body = document.querySelector("table.list tbody");
            if (body) body.insertAdjacentHTML("afterbegin", html);
            upload.reset();
            refresh();
            busy(false, "Uploaded " + d.title + ". Transcribe and analyse are queued.");
          });
      })
      .catch(function (err) { busy(false, "Upload failed: " + err.message); })
      .then(function () { btn.disabled = false; });
  });

  // Delete: remove the row in place. The <form> stays in the markup as the
  // no-JavaScript path; this intercepts it.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest(".delete-song");
    if (!form || !form.closest("tr[data-song]")) return;
    // the confirm() handler above is also a document-level submit listener and
    // runs first; if the user cancelled there, it already preventDefault'd and
    // this must not go on to delete anyway
    if (e.defaultPrevented) return;
    e.preventDefault();
    var row = form.closest("tr[data-song]");
    busy(true, "deleting…");
    api(form.action, new FormData(form))
      .then(function () { row.remove(); refresh(); busy(false, "Deleted."); })
      .catch(function (err) { busy(false, "Not deleted: " + err.message); });
  });

  document.getElementById("bulk-save").addEventListener("click", function () {
    var sel = ids();
    if (!sel.length) return busy(false, "Tick some songs first.");
    busy(true, "saving…");
    post("/songs/genres", {song_ids: sel, genre: val("bulk-genre-select"),
                            subgenre: val("bulk-subgenre-select"),
                            genre2: val("bulk-genre2-select"),
                            subgenre2: val("bulk-subgenre2-select")})
      .then(function (d) {
        d.updated.forEach(function (u) {
          var row = document.querySelector('tr[data-song="' + u.song_id + '"]');
          if (row) paintGenre(row, u);
        });
        busy(false, "Saved to " + d.updated.length + " song" + (d.updated.length === 1 ? "" : "s") + ".");
      })
      .catch(function (err) { busy(false, "Not saved: " + err.message); });
  });

  // Suggestions FILL THE FORM. Nothing is written until Save is pressed -- the
  // bar is the review step, which is the whole reason not to auto-apply.
  document.getElementById("bulk-suggest").addEventListener("click", function () {
    var sel = ids();
    if (!sel.length) return busy(false, "Tick some songs first.");
    busy(true, "reading style prompts…");
    post("/songs/genres/suggest", {song_ids: sel})
      .then(function (d) {
        d.suggestions.forEach(function (s) {
          var row = document.querySelector('tr[data-song="' + s.song_id + '"]');
          if (!row) return;
          paintGenre(row, s);
          row.classList.add("suggested");
          row.querySelector(".cell-genre").title = "suggested from: " + s.evidence;
        });
        var msg = d.suggestions.length + " suggested by " + d.model +
                  " — shown in the table, nothing saved yet. Press Save to keep them.";
        if (d.dropped.length) msg += " " + d.dropped.length + " dropped (unverifiable).";
        busy(false, msg);
      })
      .catch(function (err) { busy(false, "No suggestions: " + err.message); });
  });

  // Analyse-all, without the reload. One poll for the batch; see /songs/analysis.
  var form = document.getElementById("analyse-all");
  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    busy(true, "queueing…");
    api("/songs/analyse-all", {})
      .then(function (d) {
        var want = d.queued.map(function (q) { return q.song_id; });
        if (!want.length) return busy(false, "Nothing to analyse — every song already has a bpm.");
        var left = want.slice();
        var tick = setInterval(function () {
          api("/songs/analysis?ids=" + left.join(","))
            .then(function (a) {
              a.songs.forEach(function (s) {
                if (s.bpm === null || s.bpm === undefined) return;
                var row = document.querySelector('tr[data-song="' + s.song_id + '"]');
                if (row) {
                  row.querySelector(".cell-bpm").textContent = Math.round(s.bpm);
                  row.querySelector(".cell-key").textContent = s.key || "";
                  row.querySelector(".cell-energy").textContent =
                    s.energy === null || s.energy === undefined ? "" : s.energy.toFixed(3);
                }
                left = left.filter(function (i) { return i !== s.song_id; });
              });
              // one worker, one GPU -- say where we are rather than spin silently
              busy(true, (want.length - left.length) + " of " + want.length + " analysed…");
              if (!left.length) { clearInterval(tick); busy(false, "Analysed " + want.length + "."); }
            })
            .catch(function () { clearInterval(tick); busy(false, "Stopped watching; reload to see results."); });
        }, 3000);
      })
      .catch(function (err) { busy(false, "Could not queue: " + err.message); });
  });

  refresh();
}

// ---- live character count against a field's own cap -------------------------
// The composed anchor prompt can start out longer than the cap, so the count has
// to be visible while typing; arriving as a raw JSON error after submit was how
// this was found.
document.addEventListener("input", function (e) {
  var ta = e.target;
  if (!ta.classList || !ta.classList.contains("counted")) return;
  updateCount(ta);
});

function updateCount(ta) {
  var max = parseInt(ta.dataset.max, 10) || 0;
  var out = document.querySelector('.char-count[data-for="' + ta.name + '"]');
  if (!out) return;
  out.textContent = ta.value.length + " / " + max;
  out.classList.toggle("over", max > 0 && ta.value.length > max);
}

document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("textarea.counted").forEach(updateCount);
});
// htmx swaps the anchor form wholesale, so the counts have to be re-attached
document.body.addEventListener("htmx:afterSwap", function () {
  document.querySelectorAll("textarea.counted").forEach(updateCount);
});
