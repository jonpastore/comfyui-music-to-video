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
//
// The set-editor ruler (.tl-axis / .tl-tick / .tl-join / .tl-playhead)
// is server HTML from mixer.timeline_axis / timeline_joins /
// timeline_playhead. Do not paint ticks from pixel positions:
// TestClient has no DOM, and a JS ruler would be a second clock
// (docs/TRD-1 §1 / T1-8). .tl-axis is a sibling of .timeline so this
// handler never sees the ticks. Pointer handlers below write the same
// stored secs / automation / ?at= the server already owns.
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

function tlSecondsAt(el, clientX) {
  var dur = parseFloat(el.dataset.duration);
  if (!(dur > 0)) return 0;
  var rect = el.getBoundingClientRect();
  var t = ((clientX - rect.left) / rect.width) * dur;
  if (t < 0) return 0;
  if (t > dur) return dur;
  return t;
}

document.addEventListener("dragstart", function (e) {
  if (e.target.closest(".tl-join")) e.preventDefault();
});

document.addEventListener("click", function (e) {
  if (e.target.closest(".tl-join")) return;
  var axis = e.target.closest(".tl-axis");
  if (!axis) return;
  var t = tlSecondsAt(axis, e.clientX);
  var dur = parseFloat(axis.dataset.duration);
  var head = axis.querySelector(".tl-playhead");
  if (head && dur > 0) {
    head.setAttribute("data-t", String(t));
    head.style.left = (100 * t / dur) + "%";
  }
  try {
    var url = new URL(location.href);
    url.searchParams.set("at", String(t));
    history.replaceState(null, "", url);
  } catch (err) { /* ignore */ }
});

(function () {
  var drag = null;
  document.addEventListener("pointerdown", function (e) {
    var join = e.target.closest(".tl-join");
    if (!join) return;
    var axis = join.closest(".tl-axis");
    if (!axis) return;
    e.preventDefault();
    drag = {join: join, axis: axis};
    join.setPointerCapture && join.setPointerCapture(e.pointerId);
  });
  document.addEventListener("pointermove", function (e) {
    if (!drag) return;
    var dur = parseFloat(drag.axis.dataset.duration);
    if (!(dur > 0)) return;
    var t = tlSecondsAt(drag.axis, e.clientX);
    drag.join.setAttribute("data-t", String(t));
    drag.join.style.left = (100 * t / dur) + "%";
  });
  document.addEventListener("pointerup", function (e) {
    if (!drag) return;
    var join = drag.join;
    var axis = drag.axis;
    drag = null;
    var t = tlSecondsAt(axis, e.clientX);
    var end = parseFloat(join.dataset.end);
    var secs = isFinite(end) ? Math.max(0, end - t) : parseFloat(join.dataset.secs);
    var form = new FormData();
    form.append("secs", String(secs));
    var setId = axis.dataset.set;
    var itemId = join.dataset.item;
    if (!setId || !itemId) return;
    fetch("/sets/" + setId + "/items/" + itemId + "/join", {method: "POST", body: form})
      .then(function () { location.reload(); });
  });
})();

document.addEventListener("pointerup", function (e) {
  var lane = e.target.closest(".tl-lane");
  if (!lane || e.target.closest(".tl-join")) return;
  var root = lane.closest(".tl-lanes");
  if (!root) return;
  var items;
  try { items = JSON.parse(root.dataset.items || "[]"); }
  catch (err) { return; }
  var t = tlSecondsAt(root, e.clientX);
  var item = null;
  items.forEach(function (it) {
    if (t >= it.start && t <= it.start + it.duration) item = it;
  });
  if (!item) return;
  var rect = lane.getBoundingClientRect();
  var ypct = rect.height ? 1 - ((e.clientY - rect.top) / rect.height) : 0.5;
  if (ypct < 0) ypct = 0;
  if (ypct > 1) ypct = 1;
  var lo = parseFloat(lane.dataset.lo);
  var hi = parseFloat(lane.dataset.hi);
  if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
  var value = lo + ypct * (hi - lo);
  var localT = t - item.start;
  var points = [];
  lane.querySelectorAll(".tl-lane-pt").forEach(function (pt) {
    if (String(pt.dataset.item) !== String(item.id)) return;
    points.push([parseFloat(pt.dataset.t) - item.start, parseFloat(pt.dataset.value)]);
  });
  points.push([localT, value]);
  fetch("/api/sets/" + root.dataset.set + "/items/" + item.id +
        "/automation/" + encodeURIComponent(lane.dataset.lane), {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({points: points, curve: "linear"})
  }).then(function (r) { if (r.ok) location.reload(); });
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

  var ftab = e.target.closest(".family-tab");
  if (ftab) {
    var root = ftab.closest(".tier-panel") || ftab.closest(".gallery-section") || document;
    root.querySelectorAll(".family-tab").forEach(function (t) {
      t.classList.toggle("active", t === ftab);
      t.setAttribute("aria-selected", t === ftab ? "true" : "false");
    });
    root.querySelectorAll(".family-panel").forEach(function (p) {
      p.classList.toggle("hidden", p.dataset.family !== ftab.dataset.family);
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
  initAnchors();
  initAnchorBatch();
  initAnchorPrompts();
  initAnchorPaste();
  initViewCheckAll();
  initJobForms();       // every page, not just the ones with an anchor grid
  initRunHistory();
  initAnchorPlan();
});

// Paste / drop images onto the anchors form as base photographs.
// Delegated on document so it survives the form being swapped by htmx.
function initAnchorPaste() {
  function imageFilesFrom(dt) {
    if (!dt) return [];
    var out = [];
    if (dt.files && dt.files.length) {
      for (var i = 0; i < dt.files.length; i++) {
        if ((dt.files[i].type || "").indexOf("image/") === 0) out.push(dt.files[i]);
      }
    }
    if (!out.length && dt.items) {
      for (var j = 0; j < dt.items.length; j++) {
        if (dt.items[j].type.indexOf("image/") === 0) {
          var f = dt.items[j].getAsFile && dt.items[j].getAsFile();
          if (f) out.push(f);
        }
      }
    }
    return out;
  }

  function upload(files) {
    var form = document.getElementById("anchor-form");
    var input = document.getElementById("anchor-images");
    if (!form || !input || !files.length) return;
    var dt = new DataTransfer();
    var i;
    if (input.files) {
      for (i = 0; i < input.files.length; i++) dt.items.add(input.files[i]);
    }
    files.forEach(function (f, n) {
      var name = (f.name && f.name !== "image.png")
        ? f.name : ("paste-" + Date.now() + "-" + n + ".png");
      dt.items.add(new File([f], name, {type: f.type || "image/png"}));
    });
    input.files = dt.files;
    var btn = form.querySelector('button[formaction="/anchors/refs"]');
    if (btn) btn.click();
  }

  document.addEventListener("paste", function (e) {
    if (!document.getElementById("anchor-form")) return;
    var t = e.target;
    if (t && (t.tagName === "TEXTAREA" ||
              (t.tagName === "INPUT" && t.type !== "file" && t.type !== "checkbox"))) {
      return;
    }
    var files = imageFilesFrom(e.clipboardData);
    if (!files.length) return;
    e.preventDefault();
    upload(files);
  });

  document.addEventListener("dragover", function (e) {
    if (!document.getElementById("anchor-form")) return;
    if (!imageFilesFrom(e.dataTransfer).length) return;
    e.preventDefault();
  });
  document.addEventListener("drop", function (e) {
    if (!document.getElementById("anchor-form")) return;
    var files = imageFilesFrom(e.dataTransfer);
    if (!files.length) return;
    e.preventDefault();
    upload(files);
  });
}

// Check-all for the clothed column, the nude column, and every view.
// Delegated so it survives the form being swapped. The masters are NOT named
// "view" (they must not POST as a view) and they do not carry hx-get -- setting
// the real boxes and then letting each fire change would send one request per
// box. One ajax after the boxes are set is the whole swap.
function initViewCheckAll() {
  document.addEventListener("change", function (e) {
    var master = e.target;
    if (!master.classList || !master.classList.contains("view-check-all")) return;
    var form = document.getElementById("anchor-form");
    if (!form) return;
    var scope = master.getAttribute("data-scope");
    form.querySelectorAll('input[name="view"]').forEach(function (cb) {
      var nude = cb.getAttribute("data-nude") === "1";
      if (scope === "all" || (scope === "nude" && nude) || (scope === "clothed" && !nude)) {
        cb.checked = master.checked;
      }
    });
    if (typeof htmx === "undefined") return;
    var vals = {};
    new FormData(form).forEach(function (v, k) {
      if (vals[k] === undefined) vals[k] = v;
      else if (Array.isArray(vals[k])) vals[k].push(v);
      else vals[k] = [vals[k], v];
    });
    htmx.ajax("GET", "/anchors/form", {
      target: "#anchor-form",
      swap: "outerHTML",
      values: vals
    });
  });
}

// ---- Anchors: show exactly what will be sent -------------------------------
// The panel is filled from the SERVER, which composes it with the same
// functions the renderer uses. Nothing here rebuilds a prompt in JavaScript:
// a preview assembled a second way is a preview that can disagree with the
// render, which is this codebase's oldest defect.
// EVERY handler here is delegated on `document` and looks the form up at event
// time. They used to be bound to the form ELEMENT captured at DOMContentLoaded,
// and htmx replaces that whole element (hx-swap="outerHTML") the moment you
// change album, character, tier or view, or upload a reference image -- so the
// old node was detached and every control on the form went dead: save prompt,
// save negative, both version pickers and Assemble the prompts. The page opens
// with a tier already selected, so the first tick killed all of them, which is
// why "the save buttons do not work" was the whole story rather than one bug.
function anchorForm() { return document.getElementById("anchor-form"); }
// assigned by initAnchorPrompts; the run loader calls it to refresh the
// inert-negative warning after it changes mode or cfg.
var syncAnchorMode = function () {};

function initAnchorPrompts() {
  // The negative is inert at cfg 1.0, so fast mode says so instead of taking
  // text it will silently drop.
  syncAnchorMode = function syncMode() {
    var form = anchorForm();
    if (!form) return;
    var mode = form.querySelector("[name=mode]");
    var note = document.getElementById("negative-inert");
    var box = form.querySelector("[name=negative]");
    if (!mode || !note) return;
    // The same rule build_refs.negative_applies() applies, on the same number:
    // the negative is inert at cfg 1.0 and live above it. Reading the MODE
    // alone was wrong in one direction that matters -- fast mode with cfg
    // raised by hand drops the Lightning LoRA and the negative DOES apply, and
    // the panel said it would be thrown away.
    var cfg = form.querySelector("[name=cfg]");
    var value = cfg && cfg.value ? parseFloat(cfg.value)
                                 : (mode.value === "quality" ? 4.5 : 1.0);
    var inert = !(value > 1.0);
    note.hidden = !inert;
    if (box) box.classList.toggle("inert", inert);
  }
  document.addEventListener("change", function (e) {
    if (!e.target.closest || !e.target.closest("#anchor-form")) return;
    if (e.target.name === "mode" || e.target.name === "cfg") syncAnchorMode();
  });
  syncAnchorMode();
  // ...and again after every htmx swap, because the replacement form arrives
  // with its mode select at whatever the server rendered and no change event
  // to tell us about it.
  document.body.addEventListener("htmx:afterSwap", syncAnchorMode);

  // Saved prompt versions: pick one to load it, Save to store what is in the box.
  document.addEventListener("change", function (e) {
    var pick = e.target.closest && e.target.closest(".prompt-version-pick");
    if (!pick) return;
    var blk = promptBlock(pick);
    var box = blk && blk.querySelector("textarea");
    if (!box) return;
    var opt = pick.options[pick.selectedIndex];
    // the empty option means "the composed default" -- reloading is the honest
    // way back to it, since the composer lives on the server
    if (!opt.value) { location.reload(); return; }
    box.value = opt.dataset.text || "";
    box.dispatchEvent(new Event("input", {bubbles: true}));   // refresh the counter
    markUsedVersion(box, blk, opt.value);
    syncVersionDelete(pick);
  });

  document.addEventListener("click", function (e) {
    var save = e.target.closest && e.target.closest(".prompt-save");
    if (!save) return;
    var form = anchorForm();
    if (!form) return;
    var tier = save.dataset.tier;
    var blk = promptBlock(save);
    var box = blk && blk.querySelector("textarea");
    var note = blk && blk.querySelector(".prompt-save-note");
    var label = blk && blk.querySelector(".prompt-version-label");
    if (!box) return;
    // A version with no name is a version you cannot find again: the picker
    // lists them by name, so an unnamed one reads as "unnamed" beside every
    // other unnamed one. Refused here AND by the route.
    if (!label || !label.value.trim()) {
      say2(note, "name this version first", true);
      if (label) label.focus();
      return;
    }
    var body = new FormData();
    body.append("album", (form.querySelector("[name=album]") || {}).value || "");
    body.append("tier", tier);
    body.append("text", box.value);
    body.append("label", label.value);
    var cid = (form.querySelector("[name=character_id]") || {}).value;
    if (cid) body.append("character_id", cid);
    save.disabled = true;
    // say2, not textContent: every other handler on this form uses it, and it
    // is what clears .flash-ok. That class animates saved-fade ... forwards and
    // the keyframes END at opacity 0, so any element it has ever been applied
    // to stays invisible for good -- a later message assigned straight to
    // textContent lands in it and is never seen. The version-delete handler
    // writes into THIS same note, so that state is reachable in normal use and
    // is why a refused save looked like a button that did nothing.
    say2(note, "saving...");
    api("/anchors/prompt", body).then(function (d) {
      say2(note, "saved " + (d.label || "unnamed"));
      var pick = blk && blk.querySelector(".prompt-version-pick");
      if (pick && d.versions) {
        var keep = pick.options[0];
        pick.innerHTML = "";
        pick.appendChild(keep);
        d.versions.forEach(function (v) {
          var o = document.createElement("option");
          o.value = v.id;
          o.dataset.text = v.text;
          o.textContent = (v.label || "unnamed");
          pick.appendChild(o);
        });
        pick.value = String(d.id);
      }
      if (label) label.value = "";
    }).catch(function (err) {
      say2(note, "not saved: " + err.message, true);
    }).then(function () { save.disabled = false; });
  });

  // The negative prompt saves the same way, per ALBUM: its terms are this
  // release's failure modes and other artwork wants a different list. Same
  // pick-to-load, same version list, no tier -- a negative has none.
  document.addEventListener("change", function (e) {
    var pick = e.target.closest && e.target.closest(".negative-version-pick");
    if (!pick) return;
    var form = anchorForm();
    var box = form && form.querySelector("[name=negative]");
    var opt = pick.options[pick.selectedIndex];
    if (!box || !opt.value) return;
    box.value = opt.dataset.text || "";
    box.dispatchEvent(new Event("input", {bubbles: true}));
    markUsedVersion(box, null, opt.value);   // the negative has no per-view block
    syncAnchorMode();
    syncVersionDelete(pick);
  });

  document.addEventListener("click", function (e) {
    var save = e.target.closest && e.target.closest(".negative-save");
    if (!save) return;
    var form = anchorForm();
    if (!form) return;
    var box = form.querySelector("[name=negative]");
    var note = form.querySelector(".negative-save-note");
    var label = form.querySelector(".negative-version-label");
    if (!box) return;
    if (!label || !label.value.trim()) {
      say2(note, "name this version first", true);
      if (label) label.focus();
      return;
    }
    var body = new FormData();
    body.append("album", (form.querySelector("[name=album]") || {}).value || "");
    body.append("text", box.value);
    body.append("label", label.value);
    save.disabled = true;
    say2(note, "saving...");
    api("/anchors/negative", body).then(function (d) {
      say2(note, "saved " + (d.label || "unnamed"));
      var pick = form.querySelector(".negative-version-pick");
      if (pick && d.versions) {
        // the first option (the album's latest) and the last (the generic
        // starting point) are not versions and are kept as they are
        var first = pick.options[0], last = pick.options[pick.options.length - 1];
        pick.innerHTML = "";
        pick.appendChild(first);
        d.versions.forEach(function (v) {
          var o = document.createElement("option");
          o.value = v.id;
          o.dataset.text = v.text;
          o.textContent = (v.label || "unnamed");
          pick.appendChild(o);
        });
        pick.appendChild(last);
        pick.value = String(d.id);
      }
      if (label) label.value = "";
      syncVersionDelete(pick);
    }).catch(function (err) {
      say2(note, "not saved: " + err.message, true);
    }).then(function () { save.disabled = false; });
  });

  // ---- delete the version currently selected in a picker -------------------
  // A saved version could be created and never removed, so a picker filled up
  // with attempts and the one you wanted was somewhere among them. The button
  // is inert until a real version is selected -- the first option is "the
  // composed default", which is not a row and cannot be deleted.
  document.addEventListener("click", function (e) {
    var del = e.target.closest && e.target.closest(".version-delete");
    if (!del) return;
    var form = anchorForm();
    if (!form) return;
    var blk = promptBlock(del);
    var pick = blk ? blk.querySelector(".prompt-version-pick")
                   : form.querySelector(".negative-version-pick");
    var note = blk ? blk.querySelector(".prompt-save-note")
                   : form.querySelector(".negative-save-note");
    if (!pick || !pick.value || pick.value === "default") return;
    var opt = pick.options[pick.selectedIndex];
    if (!confirm("Delete the saved version “" + opt.textContent.trim() + "”?")) return;
    var body = new FormData();
    body.append("id", pick.value);
    del.disabled = true;
    say2(note, "deleting...");
    api("/anchors/version/delete", body).then(function () {
      say2(note, "deleted");
      opt.remove();
      pick.selectedIndex = 0;
      syncVersionDelete(pick);
    }).catch(function (err) {
      say2(note, "not deleted: " + err.message, true);
    }).then(function () { del.disabled = false; });
  });

  var out = document.getElementById("anchor-preview-out");
  document.addEventListener("click", function (e) {
    var btn = e.target.closest && e.target.closest("#anchor-preview-btn");
    if (!btn) return;
    var form = anchorForm();
    out = document.getElementById("anchor-preview-out");
    if (!form || !out) return;
    btn.disabled = true;
    out.textContent = "assembling...";
    api("/anchors/preview", new FormData(form)).then(function (d) {
      out.textContent = "";
      if (!d.sheets || !d.sheets.length) {
        out.textContent = "Nothing selected to render.";
        return;
      }
      var s = d.settings || {};
      var head = document.createElement("p");
      head.className = "hint";
      head.textContent = d.sheets.length + " sheet(s) · " + s.steps + " steps, cfg " +
        s.cfg + ", " + s.sampler_name + "/" + s.scheduler +
        (s.lora_strength ? ", Lightning LoRA " + s.lora_strength : ", LoRA off") +
        " · negative " + (d.negative_applies ? "APPLIES" : "NOT applied at this CFG");
      out.appendChild(head);

      d.sheets.forEach(function (sheet) {
        var box = document.createElement("div");
        box.className = "prompt-sheet";
        var h = document.createElement("h4");
        h.textContent = sheet.tier.toUpperCase() + " · " + sheet.view.replace(/_/g, " ");
        box.appendChild(h);
        if (sheet.refused) {
          var r = document.createElement("p");
          r.className = "hint warn";
          r.textContent = "refused before sending: " + sheet.refused;
          box.appendChild(r);
        }
        [["positive (sent)", sheet.positive],
         ["negative", sheet.negative ? sheet.negative +
            (sheet.negative_applies ? "" : "   ← dropped, not sent at this CFG") : "(none)"],
         ["this tier's wording, included above", sheet.tier_wording || "(none)"]
        ].forEach(function (pair) {
          var lbl = document.createElement("p");
          lbl.className = "hint";
          lbl.textContent = pair[0];
          var pre = document.createElement("pre");
          pre.className = "prompt-body";
          pre.textContent = pair[1];
          box.appendChild(lbl);
          box.appendChild(pre);
        });
        var foot = document.createElement("p");
        foot.className = "hint muted";
        foot.textContent = "+ the always-on adult-content safety clause (" +
          sheet.pinned_len + " chars), attached to the positive and not shown here.";
        box.appendChild(foot);
        out.appendChild(box);
      });
    }).catch(function (err) {
      out.textContent = "Could not assemble: " + err.message;
    }).then(function () { btn.disabled = false; });
  });

  // ---- the TIER's wording, saved for this album ---------------------------
  // It saved only as a side effect of pressing Generate, which meant the only
  // way to keep a wording edit was to spend a render on it.
  document.addEventListener("click", function (e) {
    var save = e.target.closest && e.target.closest(".tone-save");
    if (!save) return;
    var form = anchorForm();
    if (!form) return;
    var tier = save.dataset.tier;
    var box = form.querySelector('[name="tone_' + tier + '"]');
    var note = form.querySelector('.tone-save-note[data-tier="' + tier + '"]');
    if (!box) return;
    var body = new FormData();
    body.append("album", (form.querySelector("[name=album]") || {}).value || "");
    body.append("tier", tier);
    body.append("text", box.value);
    save.disabled = true;
    say2(note, "saving...");
    api("/anchors/tier-wording", body).then(function (d) {
      say2(note, d.overridden ? "saved for this album" : "back to the tier's own wording");
      var tag = form.querySelector('.tone-scope[data-tier="' + tier + '"]');
      if (tag) tag.textContent = d.overridden ? "this album's own wording" : "the tier's wording";
    }).catch(function (err) {
      say2(note, "not saved: " + err.message, true);
    }).then(function () { save.disabled = false; });
  });

  document.addEventListener("click", function (e) {
    var one = e.target.closest && e.target.closest(".prompt-draft");
    if (!one) return;
    var form = anchorForm();
    if (!form) return;
    var blk = promptBlock(one);
    var box = blk && blk.querySelector("textarea");
    var note = form.querySelector('.prompt-draft-note[data-tier="' + one.dataset.tier +
                                  '"][data-view="' + one.dataset.view + '"]');
    if (!box) return;
    var body = new FormData();
    body.append("album", (form.querySelector("[name=album]") || {}).value || "");
    body.append("tier", one.dataset.tier || "");
    body.append("view", one.dataset.view || "");
    body.append("current", box.value || "");
    var cid = (form.querySelector("[name=character_id]") || {}).value;
    if (cid) body.append("character_id", cid);
    one.disabled = true;
    say2(note, "drafting...");
    api("/anchors/draft", body).then(function (d) {
      box.value = d.text || "";
      box.dispatchEvent(new Event("input", {bubbles: true}));
      say2(note, "draft ready — edit it before you save");
    }).catch(function (err) {
      say2(note, "not drafted: " + err.message, true);
    }).then(function () { one.disabled = false; });
  });

  document.addEventListener("click", function (e) {
    var all = e.target.closest && e.target.closest(".prompt-draft-related");
    if (!all) return;
    var form = anchorForm();
    if (!form) return;
    var family = all.dataset.family;
    var tier = all.dataset.tier;
    var note = form.querySelector('.prompt-draft-related-note[data-tier="' + tier +
                                  '"][data-family="' + family + '"]');
    var body = new FormData();
    body.append("album", (form.querySelector("[name=album]") || {}).value || "");
    body.append("tier", tier || "");
    body.append("family", family || "");
    var cid = (form.querySelector("[name=character_id]") || {}).value;
    if (cid) body.append("character_id", cid);
    form.querySelectorAll('.position-prompt[data-tier="' + tier +
                          '"][data-family="' + family + '"] textarea').forEach(function (box) {
      var row = box.closest(".position-prompt");
      if (row && row.dataset.view) body.append("view", row.dataset.view);
    });
    all.disabled = true;
    say2(note, "drafting...");
    api("/anchors/draft-related", body).then(function (d) {
      var prompts = d.prompts || {};
      Object.keys(prompts).forEach(function (view) {
        var box = form.querySelector('[name="prompt_' + tier + '__' + view + '"]');
        if (!box) return;
        box.value = prompts[view] || "";
        box.dispatchEvent(new Event("input", {bubbles: true}));
      });
      say2(note, "drafts ready — edit them before you save");
    }).catch(function (err) {
      say2(note, "not drafted: " + err.message, true);
    }).then(function () { all.disabled = false; });
  });
}

// ---- load an earlier run's settings back into the form --------------------
// Sets what that run CHOSE, and clears what it did not: loading a run that left
// steps on the mode default has to CLEAR a steps value typed since, or you get
// a hybrid of two runs that was never rendered and is not what the summary
// beside it says.
function initRunHistory() {
  var FIELDS = ["mode", "cfg", "ref_method", "steps", "denoise", "sampler_name", "scheduler"];
  document.addEventListener("change", function (e) {
    var pick = e.target.closest && e.target.closest("#run-history");
    if (!pick) return;
    var form = anchorForm();
    if (!form) return;
    var note = form.querySelector(".run-load-note");
    var opt = pick.options[pick.selectedIndex];
    if (!opt.value) { say2(note, ""); return; }
    var data;
    try { data = JSON.parse(opt.dataset.form || "{}"); }
    catch (err) { say2(note, "could not read that run", true); return; }
    FIELDS.forEach(function (name) {
      var el = form.querySelector("[name=" + name + "]");
      if (!el) return;
      var v = data[name];
      // a NUMBER back to the string the option carries: 4.5 must match the
      // option value "4.5", and 28 must match "28", not "28.0"
      el.value = (v === undefined || v === null) ? ""
               : (typeof v === "number" ? String(+v.toFixed(4)).replace(/\.0+$/, "") : String(v));
    });
    var neg = form.querySelector("[name=negative]");
    if (neg && typeof data.negative === "string") neg.value = data.negative;
    var n = form.querySelector("[name=n]");
    if (n && opt.dataset.n) n.value = opt.dataset.n;
    say2(note, "loaded run #" + opt.value);
    if (typeof syncAnchorMode === "function") syncAnchorMode();
  });
}

// Which saved version a box is currently showing, so the generate route can
// count a RENDER as usage rather than a look. Cleared as soon as the text is
// edited: a wording you altered is no longer the version you loaded, and
// counting it would make the history's usage numbers describe something else.
// One saved-prompt row per VIEW, so everything about a row is resolved inside
// its own block. A form-wide lookup by data-tier alone reaches the FIRST view's
// box, which would save the front sheet's wording as the back sheet's and load
// it back the same way -- the cross-view leak T7-19 removed from the render
// path, reappearing in the editor. Null for the negative, which has no block.
function promptBlock(el) {
  return (el && el.closest) ? el.closest(".view-prompt") : null;
}

function markUsedVersion(box, blk, vid) {
  var form = anchorForm();
  if (!form || !box) return;
  // Only a real version id. The negative picker's last option is the sentinel
  // "default" (the generic starting point), which is not a row -- it reached
  // prompts.mark_used as a string and 500'd the render request AFTER the jobs
  // were queued. syncVersionDelete already special-cased it; this handler did
  // not, which is how a sentinel handled in one place and not the other gets
  // through.
  if (!/^\d+$/.test(String(vid || ""))) vid = "";
  var hidden = blk ? blk.querySelector(".used-version")
                   : form.querySelector(".used-version:not([data-tier])");
  if (!hidden) return;
  hidden.value = vid || "";
  if (!box.dataset.versionWatched) {
    box.dataset.versionWatched = "1";
    box.addEventListener("input", function () { hidden.value = ""; });
  }
}

// ---- preflight: what this form will do, and what would stop it -------------
// Debounced because it fires on every keystroke in a textarea. The arithmetic
// and every refusal come from the SERVER, computed by the same functions the
// submit runs -- re-deriving them here would have been less code and would have
// drifted from the route the first time either changed.
function initAnchorPlan() {
  var timer = null, inflight = false;

  function paint(d) {
    var panel = document.getElementById("anchor-plan");
    var btn = document.getElementById("anchor-generate");
    if (!panel) return;
    panel.innerHTML = "";
    var line = document.createElement("p");
    line.className = "plan-line";
    var mins = Math.round(d.seconds / 60);
    line.textContent = d.sheets + " sheet" + (d.sheets === 1 ? "" : "s") + " in " +
      d.jobs + " job" + (d.jobs === 1 ? "" : "s") +
      (d.sheets ? " · about " + (mins < 1 ? "under a minute" : mins + " min") : "") +
      (d.sweep ? " · CFG sweep" : "");
    panel.appendChild(line);
    (d.blockers || []).forEach(function (b) {
      var p = document.createElement("p");
      p.className = "plan-blocker";
      p.textContent = b;
      panel.appendChild(p);
    });
    (d.notes || []).forEach(function (nte) {
      var p = document.createElement("p");
      p.className = "plan-note";
      p.textContent = nte;
      panel.appendChild(p);
    });
    // The button is NOT disabled -- a control that cannot apply must still say
    // why, and a greyed-out Generate with the reason elsewhere is how this app
    // used to hide its refusals. It is marked, and the server refuses anyway.
    if (btn) btn.classList.toggle("blocked", !!(d.blockers || []).length);
  }

  function run() {
    var form = anchorForm();
    if (!form || inflight) return;
    inflight = true;
    api("/anchors/plan", new FormData(form)).then(paint).catch(function () {
      // a preflight that cannot answer must not claim the form is fine
      var panel = document.getElementById("anchor-plan");
      if (panel) panel.textContent = "";
    }).then(function () { inflight = false; });
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(run, 250);
  }

  document.addEventListener("input", function (e) {
    if (e.target.closest && e.target.closest("#anchor-form")) schedule();
  });
  document.addEventListener("change", function (e) {
    if (e.target.closest && e.target.closest("#anchor-form")) schedule();
  });
  document.body.addEventListener("htmx:afterSwap", schedule);
  schedule();
}

// A save note that says which it is. Success fades (.flash-ok), failure does
// NOT (.flash-fail) -- "not saved" has to still be on screen when you look back.
function say2(el, msg, bad) {
  if (!el) return;
  el.textContent = msg;
  el.className = (el.className.replace(/\s*flash-(ok|fail)\b/g, "")) + (bad ? " flash-fail" : " flash-ok");
}

// The Delete button beside a version picker is inert unless a real saved
// version is selected. The first option is the composed default and the last
// (on the negative) is the generic starting point; neither is a row.
function syncVersionDelete(pick) {
  if (!pick) return;
  var blk = promptBlock(pick);
  var form = anchorForm();
  var del = blk ? blk.querySelector(".version-delete")
                : form && form.querySelector(".version-delete:not([data-tier])");
  if (!del) return;
  var real = pick.value && pick.value !== "default";
  del.disabled = !real;
  del.title = real ? "Delete this saved version"
                   : "Select a saved version to delete it";
}

// ---- Anchors: queue the sheets, say so, and watch them render ---------------
// The Generate button was the last form POST on this page: it 303'd, reloaded
// the whole page, and said NOTHING about what it had accepted. On the occasion
// a user reported it as "I don't think it generated any anchors", twelve jobs
// HAD been queued and had all failed, and neither fact was visible from here.
//
// Nothing is re-rendered on success. The form is left exactly as submitted --
// no rebuild, so no ticked tier, chosen view, typed prompt or selected character
// can be silently reset the way the first async upload/delete handlers did.
function initAnchorBatch() {
  // Looked up at event time, not captured: the batch panel lives inside the
  // page but the FORM above it is replaced by htmx, and on a fresh /anchors
  // there may be no panel yet at DOMContentLoaded.
  var panel = document.getElementById("anchor-batch");
  var list = document.getElementById("anchor-batch-list");
  var note = document.getElementById("anchor-batch-note");
  var done = 0, failed = 0, total = list.children.length;

  function viewname(v) { return (v || "").replace(/_/g, " "); }

  function tally() {
    var running = total - done - failed;
    var parts = [];
    if (running) parts.push(running + " rendering");
    if (done) parts.push(done + " done");
    if (failed) parts.push(failed + " FAILED");
    note.firstChild.textContent = total
      ? total + " sheet" + (total === 1 ? "" : "s") + ": " + parts.join(", ") + ". "
      : "";
  }

  // A finished sheet, dropped into the page as its own group. The markup comes
  // from the SERVER (the same partial the page renders), so the pick and delete
  // forms on a fresh sheet are the ones that already work -- rebuilding this in
  // JavaScript would be a second copy to keep in step.
  function showFinishedSheet(li) {
    var album = (document.querySelector("#anchor-form [name=album]") || {}).value;
    if (!album || !li.dataset.tier) return;
    var cid = (document.querySelector("#anchor-form [name=character_id]") || {}).value;
    var url = "/anchors/group?scope_value=" + encodeURIComponent(album) +
              "&tier=" + encodeURIComponent(li.dataset.tier) +
              "&view=" + encodeURIComponent(li.dataset.view) +
              (cid ? "&character_id=" + encodeURIComponent(cid) : "");
    fetch(url, {headers: {"Accept": "text/html"}}).then(function (r) {
      return r.ok ? r.text() : "";
    }).then(function (html) {
      if (!html.trim()) return;
      var holder = document.createElement("div");
      holder.innerHTML = html;
      var fresh = holder.firstElementChild;
      if (!fresh) return;
      // replace the group if it is already on the page (a re-roll adds
      // candidates to an existing sheet), otherwise append it
      var existing = null;
      document.querySelectorAll("section.card h3").forEach(function (h) {
        if (!existing && h.textContent.replace(/\s+/g, " ").trim() ===
            fresh.querySelector("h3").textContent.replace(/\s+/g, " ").trim()) {
          existing = h.closest("section.card");
        }
      });
      if (existing) existing.replaceWith(fresh);
      else {
        var empty = document.querySelector("p.empty");
        if (empty) empty.remove();
        document.body.querySelector("main, .content, body").appendChild(fresh);
      }
      var bar = fresh.querySelector(".candidate-bar");
      if (bar) initAnchors();      // re-attach selection for the new section
    }).catch(function () { /* the line already reports the job; leave the page */ });
  }

  // One line per sheet, filled from the job's own SSE stream rather than a
  // poll -- /jobs/{id}/stream already carries status, progress and error.
  function watch(li) {
    var id = li.dataset.job;
    var label = (li.dataset.tier || "").toUpperCase() + " " + viewname(li.dataset.view);
    li.textContent = label + " — queued";
    var es = new EventSource("/jobs/" + id + "/stream");
    es.onmessage = function (e) {
      var d = JSON.parse(e.data);
      li.textContent = label + " — " + (d.error || d.progress || d.status || "");
      if (d.status === "done" || d.status === "failed" || d.status === "cancelled") {
        es.close();
        if (d.status === "done") {
          done++; li.className = "batch-done";
          // the sheet is on disk now -- put it on the page rather than making
          // someone reload to find out what they just rendered
          showFinishedSheet(li);
        } else { failed++; li.className = "batch-failed"; }
        var a = document.createElement("a");
        a.className = "linkish";
        a.href = "/jobs/" + id + "/log";
        a.textContent = "log";
        a.style.marginLeft = "0.5rem";
        li.appendChild(a);
        tally();
      }
    };
    // A dropped stream is not a failed render. Say the line went quiet and
    // leave the job alone -- /jobs is still the truth.
    es.onerror = function () {
      es.close();
      if (!li.className) li.textContent = label + " — lost the live stream; see /jobs";
    };
  }

  if (list) Array.prototype.forEach.call(list.children, watch);
  if (panel) tally();

  // Delegated on document, resolving the form at event time. Bound to the
  // ELEMENT this listener died on the first tier or view tick: every one of
  // those controls carries hx-swap="outerHTML" on #anchor-form, so the node this
  // closure captured was detached and Generate fell back to a native POST and a
  // 303 full-page reload -- no batch report, no SSE watchers, no per-sheet
  // Cancel. 36d7d7a fixed exactly this for the save buttons and the pickers and
  // left this handler behind; the test guarding it sliced the source up to the
  // start of this function, so the one surviving instance sat just past the end
  // of what it read.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest && e.target.closest("#anchor-form");
    if (!form) return;
    if (e.defaultPrevented) return;          // htmx or a confirm() already handled it
    // Upload and each thumbnail's Delete are submit buttons with their own
    // formaction, driven by htmx. Only the bare Generate submit is ours.
    if (e.submitter && e.submitter.hasAttribute("formaction")) return;
    e.preventDefault();
    panel = document.getElementById("anchor-batch");
    list = document.getElementById("anchor-batch-list");
    note = document.getElementById("anchor-batch-note");
    if (!panel || !list || !note) return;
    var btn = e.submitter || form.querySelector('button[type="submit"]:not([formaction])');
    if (btn) btn.disabled = true;
    panel.hidden = false;
    // FormData(form) IS what was submitted -- every ticked tier, every chosen
    // view, every per-tier textarea and any file picked. It is not rebuilt from
    // defaults, which is how the earlier async handlers ate the user's work.
    api("/anchors", new FormData(form)).then(function (d) {
      done = failed = 0;
      total = d.queued;
      list.innerHTML = "";
      d.jobs.forEach(function (j) {
        var li = document.createElement("li");
        li.dataset.job = j.id;
        li.dataset.tier = j.tier;
        li.dataset.view = j.view;
        list.appendChild(li);
        watch(li);
      });
      tally();
      // The files in this input have now been SAVED for the album. Leaving them
      // selected meant the next click uploaded the same photographs again --
      // the reload used to clear it.
      var file = document.getElementById("anchor-images");
      if (file) file.value = "";
      refreshQueue();          // the panel is inert while the queue was empty
    }).catch(function (err) {
      total = done = failed = 0;
      list.innerHTML = "";
      note.firstChild.textContent = "Nothing was queued: " + err.message + " ";
    }).then(function () { if (btn) btn.disabled = false; });
  });
}

// The queue panel stops polling when the queue drains, which is right -- a page
// that polls forever never lets the machine idle. But nothing re-armed it, so on
// /anchors, the one page that queues work WITHOUT a reload, the panel sat on
// "idle -- not polling / Nothing queued." for the whole render. Called wherever
// work is enqueued asynchronously.
function refreshQueue() {
  var panel = document.getElementById("queue-panel");
  if (!panel || typeof htmx === "undefined") return;
  htmx.ajax("GET", "/queue", {target: "#queue-panel", swap: "outerHTML"});
}

// ---- Retry and Cancel, on every page that shows a job ----------------------
// This lived INSIDE initAnchors(), which bails on any page without an anchor
// grid -- so the one page whose whole purpose is jobs got the plain 303. /jobs
// reloaded the entire table to cancel one job, and Cancel on a song page
// redirected to /jobs and navigated you off the song you were working on.
// Delegated on document and selector-guarded, so it is inert where there are no
// job forms and needs no per-page wiring.
//
// The message lands in [data-job-msg], marked in each template, NOT in a column
// by number: the three job tables have three different layouts, and the old
// td:nth-child(2) was the failure reason on /anchors, the job DESCRIPTION on
// /jobs and the kind on a song page -- so two of the three would have had a
// real cell overwritten with status text.
function initJobForms() {
  document.addEventListener("submit", function (e) {
    var form = e.target.closest('form[action^="/jobs/"]');
    if (!form) return;
    e.preventDefault();
    var row = form.closest("tr");
    var cell = row && (row.querySelector("[data-job-msg]") || row.querySelector("td:nth-child(2)"));
    var btn = form.querySelector("button");
    var retry = /\/retry$/.test(form.getAttribute("action") || "");
    if (btn) btn.disabled = true;
    api(form.action, new FormData(form)).then(function (d) {
      if (cell) cell.textContent = retry ? "re-queued as job #" + d.job_id : "cancelled";
      if (!retry && row) row.classList.add("job-cancelled");
      refreshQueue();          // a retry queues work; a cancel may drain it
    }).catch(function (err) {
      if (cell) cell.textContent = (retry ? "retry failed: " : "cancel failed: ") + err.message;
      if (btn) btn.disabled = false;      // it did not happen, so let it be tried again
    });
  });
}

// ---- Anchors: view full size, multi-select, and nothing reloads the page -----
function initAnchors() {
  var grid = document.querySelector(".candidate-grid");
  // Not `if (!grid) return`. An Anchors page with NO anchors yet has no grid --
  // which is exactly the regenerate-from-empty case -- and bailing there left
  // the failed-job Retry buttons below doing a full page POST, on the one page
  // where every button is supposed to be async. Every handler here is delegated
  // and selector-guarded, so it stays inert on pages that have neither.
  if (!grid && !document.getElementById("anchor-form")) return;
  var box = document.getElementById("anchor-lightbox");

  // ---- full-size view: one dialog, navigated by keyboard ----
  // Position is (row, index) resolved from the DOM every time rather than held
  // in a variable, so deleting a sheet from inside the modal cannot leave the
  // pointer describing a card that is no longer there.
  var current = null;                       // the .candidate element on show

  // The base-image gallery (.ref-gallery/.ref-thumb) is a second row/item shape
  // the same lightbox now serves, alongside .candidate-grid/.candidate -- one
  // set of selectors covering both rather than a duplicate lightbox and a
  // duplicate keyboard handler for the base-image picker.
  var ROW_SEL = ".candidate-grid, .ref-gallery";
  var ITEM_SEL = ".candidate[data-anchor], .ref-thumb[data-ref]";
  var THUMB_SEL = ROW_SEL.split(", ").map(function (s) { return s + " img.thumb"; }).join(", ");

  function rows() {
    return Array.prototype.slice.call(document.querySelectorAll(ROW_SEL));
  }
  function cardsIn(row) {
    return Array.prototype.slice.call(row.querySelectorAll(ITEM_SEL));
  }
  function where(card) {
    var row = card.closest(ROW_SEL);
    return {row: row, rowIdx: rows().indexOf(row), idx: cardsIn(row).indexOf(card)};
  }

  function show(card) {
    if (!box || !card) return;
    var img = card.querySelector("img.thumb");
    if (!img) return;
    current = card;
    var at = where(card), all = cardsIn(at.row);
    var src = img.dataset.full || img.src;
    box.querySelector("img").src = src;
    // the row's own heading, so "which sheet is this" is answerable without
    // closing the modal and counting thumbnails -- a candidate row is titled
    // by its section's h3, a base-image row has no h3 and is titled by its
    // fieldset's legend instead
    var head = at.row.closest("section.card") && at.row.closest("section.card").querySelector("h3");
    var legend = at.row.closest("fieldset") && at.row.closest("fieldset").querySelector("legend");
    var title = legend || head;
    box.querySelector(".lightbox-title").textContent = title ? title.textContent.trim() : "";
    box.querySelector(".lightbox-pos").textContent =
      "option " + (at.idx + 1) + " of " + all.length +
      (card.classList.contains("picked") ? " · CHOSEN" : "");
    var dl = box.querySelector(".lightbox-download");
    dl.href = src;
    // a name the file keeps once it is off the page; the src basename is a
    // meaningless generated one
    dl.setAttribute("download", (box.querySelector(".lightbox-title").textContent || "anchor")
      .replace(/[^\w.-]+/g, "_") + "_" + (at.idx + 1) + ".png");
    if (!box.open) box.showModal();
  }

  function step(dRow, dIdx) {
    if (!current) return;
    var at = where(current), rs = rows();
    if (dRow) {
      var nextRow = rs[at.rowIdx + dRow];
      if (!nextRow) return;                 // clamp: no wrap between rows
      var cards = cardsIn(nextRow);
      // hold the column where possible, so up/down reads as a grid move
      show(cards[Math.min(at.idx, cards.length - 1)]);
      return;
    }
    var here = cardsIn(at.row), target = here[at.idx + dIdx];
    if (target) show(target);               // clamp at both ends of the row
  }

  document.addEventListener("click", function (e) {
    var img = e.target.closest(THUMB_SEL);
    if (img) { show(img.closest(ITEM_SEL)); return; }
    // backdrop or the close button dismisses; clicking the image itself does not
    if (box && box.open && (e.target === box || e.target.closest(".lightbox-close"))) box.close();
  });

  document.addEventListener("keydown", function (e) {
    // opening from the grid, for keyboard users who never touch the mouse
    var thumb = e.target.closest && e.target.closest(THUMB_SEL);
    if (thumb && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault(); show(thumb.closest(ITEM_SEL)); return;
    }
    if (!box || !box.open || !current) return;
    if (e.key === "ArrowRight") { e.preventDefault(); step(0, 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(0, -1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); step(1, 0); }
    else if (e.key === "ArrowUp") { e.preventDefault(); step(-1, 0); }
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeShown(); }
    // Esc is <dialog>'s own; nothing to add
  });

  box && box.querySelector(".lightbox-delete").addEventListener("click", removeShown);

  function removeShown() {
    if (!current) return;
    var card = current, at = where(card), all = cardsIn(at.row);
    // where to land afterwards: the next sheet along, else the previous one
    var next = all[at.idx + 1] || all[at.idx - 1] || null;

    // a base image is not an anchor candidate -- different table, different
    // delete endpoint (one id at a time, no batch) -- so the two branches
    // cannot share the same request even though they share the modal
    if (card.classList.contains("ref-thumb")) {
      if (!confirm("Delete this base image? The file is removed too. Sheets already " +
                   "generated from it are not affected.")) return;
      api("/anchors/refs/" + card.dataset.ref + "/delete", {})
        .then(function () {
          card.remove();
          if (next) { show(next); } else { box.close(); }
        })
        .catch(function (err) {
          box.querySelector(".lightbox-pos").textContent = "not deleted: " + err.message;
        });
      return;
    }

    // same wording as the grid's own delete, and the chosen one still says what
    // it costs rather than being refused
    var msg = card.classList.contains("picked")
      ? "Delete the CHOSEN anchor? The file is removed too, and reference " +
        "generation for this tier will refuse until you pick or generate another."
      : "Delete this anchor candidate? The file is removed too.";
    if (!confirm(msg)) return;
    api("/anchors/delete", {anchor_ids: [Number(card.dataset.anchor)]})
      .then(function () {
        var sec = card.closest("section.card");
        card.remove();
        if (next) { show(next); }
        else { box.close(); }
        if (sec && !sec.querySelectorAll(".candidate").length) sec.remove();
        else if (sec) refreshGroup(sec);
      })
      .catch(function (err) {
        box.querySelector(".lightbox-pos").textContent = "not deleted: " + err.message;
      });
  }

  // free the decoded image when it closes; a 2048px sheet held open per page is
  // memory nothing is using
  if (box) box.addEventListener("close", function () {
    box.querySelector("img").removeAttribute("src");
    current = null;
  });

  // ---- selection, per GROUP ----
  function sectionOf(el) { return el.closest("section.card"); }
  function boxesIn(sec) { return Array.prototype.slice.call(sec.querySelectorAll(".pick-anchor")); }
  function chosenIn(sec) { return boxesIn(sec).filter(function (b) { return b.checked; }); }

  function refreshGroup(sec) {
    var bar = sec.querySelector(".candidate-bar");
    if (!bar) return;
    var all = boxesIn(sec), picked = chosenIn(sec);
    bar.querySelector(".anchor-count").textContent =
      picked.length ? picked.length + " of " + all.length + " selected" : "none selected";
    bar.querySelector(".delete-selected").hidden = picked.length === 0;
    var toggle = bar.querySelector(".pick-all-anchors");
    toggle.checked = all.length > 0 && picked.length === all.length;
    toggle.indeterminate = picked.length > 0 && picked.length < all.length;
  }
  document.addEventListener("change", function (e) {
    if (e.target.classList.contains("pick-anchor")) refreshGroup(sectionOf(e.target));
    if (e.target.classList.contains("pick-all-anchors")) {
      var sec = sectionOf(e.target);
      boxesIn(sec).forEach(function (b) { b.checked = e.target.checked; });
      refreshGroup(sec);
    }
  });

  function removeCards(sec, ids) {
    ids.forEach(function (id) {
      var card = sec.querySelector('.candidate[data-anchor="' + id + '"]');
      if (card) card.remove();
    });
    if (!sec.querySelectorAll(".candidate").length) sec.remove();
    else refreshGroup(sec);
  }
  function say(sec, msg) {
    var c = sec.querySelector(".anchor-count");
    if (c) c.textContent = msg;
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".delete-selected");
    if (!btn) return;
    var sec = sectionOf(btn), ids = chosenIn(sec).map(function (b) { return Number(b.value); });
    if (!ids.length) return;
    var anyChosen = ids.some(function (id) {
      var card = sec.querySelector('.candidate[data-anchor="' + id + '"]');
      return card && card.classList.contains("picked");
    });
    var warn = "Delete " + ids.length + " candidate" + (ids.length === 1 ? "" : "s") + "?";
    if (anyChosen) warn += "\n\nOne of them is the CHOSEN anchor for this group. " +
                           "Reference generation for this tier will refuse to run until another is picked.";
    if (!confirm(warn)) return;
    btn.disabled = true;
    api("/anchors/delete", {anchor_ids: ids})
      .then(function (d) { removeCards(sec, d.deleted); })
      .catch(function (err) { say(sec, "Not deleted: " + err.message); })
      .then(function () { btn.disabled = false; });
  });

  // ---- the existing per-card forms, intercepted ----
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;          // a confirm() handler already said no
    var sec, form;

    if ((form = e.target.closest(".pick-anchor-form"))) {
      e.preventDefault();
      sec = sectionOf(form);
      api(form.action, new FormData(form)).then(function (d) {
        // the server says who is chosen now AND who lost it
        d.group.forEach(function (p) {
          var card = sec.querySelector('.candidate[data-anchor="' + p.id + '"]');
          if (!card) return;
          card.classList.toggle("picked", p.chosen);
          var b = card.querySelector(".pick-anchor-form button");
          if (b) { b.disabled = p.chosen; b.textContent = p.chosen ? "Chosen" : "Pick"; }
        });
      }).catch(function (err) { say(sec, "Not picked: " + err.message); });
      return;
    }
    if ((form = e.target.closest(".delete-anchor"))) {
      e.preventDefault();
      sec = sectionOf(form);
      api(form.action, new FormData(form))
        .then(function (d) { removeCards(sec, d.deleted); })
        .catch(function (err) { say(sec, "Not deleted: " + err.message); });
      return;
    }
    if ((form = e.target.closest(".delete-anchor-group"))) {
      e.preventDefault();
      sec = sectionOf(form);
      api(form.action, new FormData(form)).then(function (d) {
        removeCards(sec, d.deleted);
        if (document.body.contains(form)) form.remove();
      }).catch(function (err) { say(sec, "Not deleted: " + err.message); });
      return;
    }
  });

  document.querySelectorAll("section.card").forEach(function (sec) {
    if (sec.querySelector(".candidate-bar")) refreshGroup(sec);
  });
}

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
  var post = api;
  function refresh() {
    var n = picked().length;
    var vis = shown();
    all.checked = vis.length > 0 && n === vis.length;
    all.indeterminate = n > 0 && n < vis.length;
    all.title = "Select all " + vis.length + " shown";
    if (!n) {
      count.textContent = "no songs selected";
      return;
    }
    var genre = val("bulk-genre-select"), genre2 = val("bulk-genre2-select");
    if (!genre && !genre2) {
      count.textContent = n + " song" + (n === 1 ? "" : "s") + " selected";
      return;
    }
    post("/songs/genres", {preview: true, song_ids: ids(),
                            genre: genre, subgenre: val("bulk-subgenre-select"),
                            genre2: genre2, subgenre2: val("bulk-subgenre2-select")})
      .then(function (d) {
        count.textContent = d.would_change + " will change";
      })
      .catch(function (err) { count.textContent = err.message; });
  }
  function ids() { return picked().map(function (r) { return Number(r.dataset.song); }); }

  all.addEventListener("change", function () {
    shown().forEach(function (r) { r.querySelector(".pick-song").checked = all.checked; });
    refresh();
  });
  document.addEventListener("change", function (e) {
    if (e.target.classList && e.target.classList.contains("pick-song")) refresh();
  });
  ["bulk-genre-select", "bulk-subgenre-select",
   "bulk-genre2-select", "bulk-subgenre2-select"].forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.addEventListener("change", refresh);
  });

  function paintGenre(row, g) {
    var cell = row.querySelector(".cell-genre");
    if (!cell) return;
    var first = g.genre + (g.subgenre ? " / " + g.subgenre : "");
    var second = g.genre2 ? g.genre2 + (g.subgenre2 ? " / " + g.subgenre2 : "") : "";
    cell.textContent = first;
    if (second) { cell.appendChild(document.createElement("br")); cell.append(second); }
  }
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
        var n = d.changed != null ? d.changed : d.updated.length;
        busy(false, "Saved to " + n + " song" + (n === 1 ? "" : "s") + ".");
        refresh();
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
