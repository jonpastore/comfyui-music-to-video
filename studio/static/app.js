// Minimal SSE watcher for job progress -- no htmx-sse extension needed.
function watchJob(jobId, targetId, onDone) {
  if (!jobId) return;
  var el = targetId ? document.getElementById(targetId) : null;
  if (el) el.hidden = false;
  var finished = false;
  var es = null;
  var tries = 0;
  function apply(data) {
    if (!data || finished) return;
    if (el) {
      el.textContent = "job #" + data.id + " (" + (data.status || "") + "): " +
        (data.error || data.progress || "");
    }
    if (data.status === "done" || data.status === "failed" || data.status === "cancelled") {
      finished = true;
      if (es) { es.close(); es = null; }
      if (poll) clearInterval(poll);
      if (typeof onDone === "function") {
        onDone(data);
        return;
      }
      if (!el) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Refresh to see the results";
      btn.className = "linkish";
      btn.style.marginLeft = "0.6rem";
      btn.addEventListener("click", function () { location.reload(); });
      el.appendChild(btn);
    }
  }
  function connect() {
    if (finished) return;
    if (es) es.close();
    es = new EventSource("/jobs/" + jobId + "/stream");
    es.onmessage = function (e) {
      try { apply(JSON.parse(e.data)); } catch (err) {}
    };
    es.onerror = function () {
      if (es) { es.close(); es = null; }
      if (!finished && tries++ < 60) setTimeout(connect, 1000);
    };
  }
  connect();
  var poll = setInterval(function () {
    if (finished) return;
    fetch("/jobs/" + jobId, {headers: {Accept: "application/json"}})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(apply)
      .catch(function () {});
  }, 2500);
}

// Waveform: .tl-block[data-peaks] holds mixer.peaks min/max pairs.
function drawTlWaves() {
  document.querySelectorAll(".tl-block[data-peaks] canvas.tl-wave").forEach(function (canvas) {
    var block = canvas.closest(".tl-block");
    if (!block) return;
    var pairs;
    try { pairs = JSON.parse(block.getAttribute("data-peaks") || "[]"); }
    catch (err) { return; }
    if (!pairs || !pairs.length) return;
    var w = Math.max(2, canvas.clientWidth || block.clientWidth || 100);
    var h = Math.max(2, canvas.clientHeight || 40);
    if (canvas.width !== w) canvas.width = w;
    if (canvas.height !== h) canvas.height = h;
    var ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    var mid = h / 2;
    var n = pairs.length;
    var maxAbs = 0;
    for (var i = 0; i < n; i++) {
      var lo = Math.abs(pairs[i][0] || 0);
      var hi = Math.abs(pairs[i][1] || 0);
      if (lo > maxAbs) maxAbs = lo;
      if (hi > maxAbs) maxAbs = hi;
    }
    if (!(maxAbs > 0)) maxAbs = 1;
    ctx.fillStyle = getComputedStyle(document.documentElement)
      .getPropertyValue("--accent").trim() || "#7aa2f7";
    var barW = Math.max(1, w / n);
    for (var j = 0; j < n; j++) {
      var mn = pairs[j][0] || 0;
      var mx = pairs[j][1] || 0;
      var y1 = mid - (mx / maxAbs) * (mid - 1);
      var y2 = mid - (mn / maxAbs) * (mid - 1);
      var top = Math.min(y1, y2);
      var bot = Math.max(y1, y2);
      ctx.fillRect(j * barW, top, Math.max(1, barW - 0.5), Math.max(1, bot - top));
    }
  });
}

function bindLiveMeter() {
  document.querySelectorAll("[data-meter=loudness] .tl-measure").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var card = btn.closest("[data-meter-url]");
      var url = card && card.getAttribute("data-meter-url");
      if (!url) return;
      btn.disabled = true;
      fetch(url).then(function (r) { return r.json(); }).then(function (body) {
        var loud = body.loudness;
        if (!loud) return;
        var fill = card.querySelector(".meter-fill");
        if (fill) fill.style.width = (loud.fill_pct || 0) + "%";
        var meter = card.querySelector(".meter");
        if (meter) {
          meter.classList.toggle("off", !!loud.flagged);
          meter.classList.toggle("ok", !loud.flagged);
        }
        var text = card.querySelector(".meter-text");
        if (text) {
          var html = "<strong data-lufs=\"" + loud.lufs + "\">" +
            Number(loud.lufs).toFixed(1) + "</strong> LUFS";
          if (loud.true_peak_db != null) {
            html += " / <strong data-tp=\"" + loud.true_peak_db + "\">" +
              Number(loud.true_peak_db).toFixed(1) + "</strong> dBTP";
          }
          if (loud.flagged) html += " <span class=\"tag warn-tag\">off target</span>";
          html += " <span class=\"muted\">· live_mix</span>";
          text.innerHTML = html;
        }
      }).finally(function () { btn.disabled = false; });
    });
  });
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
  drawTlWaves();
  bindLiveMeter();
  if (typeof ResizeObserver !== "undefined") {
    document.querySelectorAll(".tl-block.has-wave").forEach(function (b) {
      new ResizeObserver(drawTlWaves).observe(b);
    });
  }
  bindReorder(document);
});

function fillDeferredFold(d) {
  if (!d || !window.htmx) return;
  var url = d.getAttribute("hx-get");
  if (!url) return;
  var spec = d.getAttribute("hx-target") || "";
  var dest = spec.indexOf("find ") === 0 ? d.querySelector(spec.slice(5)) : d;
  if (!dest) return;
  if (dest.querySelector(".anchor-tile, .pose-roster, .family-tabs, .pose-need")) return;
  htmx.ajax("GET", url, {target: dest, swap: "innerHTML"});
}

function bindReorder(scope) {
  var roots = (scope || document).querySelectorAll("[data-reorder-url]");
  Array.prototype.forEach.call(roots, function (root) {
    if (root.dataset.reorderBound) return;
    root.dataset.reorderBound = "1";
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
      if (root.dataset.reload !== undefined) post.then(function () { location.reload(); });
    });
  });
}

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
      var state = form.querySelector(".js-mask-state");
      if (state) { state.hidden = false; state.textContent = "ready"; }
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

// Approve-grid Fix: one dialog, not an inline <details> that stretches the
// neighbour card up the row.
document.addEventListener("click", function (e) {
  var btn = e.target.closest(".js-ref-fix");
  if (!btn) return;
  var dlg = document.getElementById("ref-fix");
  if (!dlg) return;
  var label = document.getElementById("ref-fix-label");
  var preview = document.getElementById("ref-fix-preview");
  if (label) label.textContent = btn.dataset.label || "";
  if (preview) preview.src = btn.dataset.src || "";
  dlg.querySelectorAll("form").forEach(function (f) {
    f.action = btn.dataset.action;
    var tier = f.querySelector("[name=tier]");
    var ref = f.querySelector("[name=ref_id]");
    if (tier) tier.value = btn.dataset.tier || "";
    if (ref) ref.value = btn.dataset.ref || "";
  });
  var maskForm = dlg.querySelector(".mask-form");
  if (maskForm) {
    maskForm.dataset.src = btn.dataset.src || "";
    var data = maskForm.querySelector("[name=mask_data]");
    var state = maskForm.querySelector(".js-mask-state");
    var submit = maskForm.querySelector(".js-mask-submit");
    if (data) data.value = "";
    if (state) { state.hidden = true; state.textContent = "ready"; }
    if (submit) submit.disabled = true;
  }
  dlg.showModal();
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
// Playlist pair viewer (#anchor-lightbox without .lightbox-pose-form).
// Candidate lightbox on /anchors has the pose form and uses initAnchors.
var pairNav = { items: [], idx: 0 };
function isPairLightbox(dlg) {
  return !!(dlg && dlg.id === "anchor-lightbox" && !dlg.querySelector(".lightbox-pose-form"));
}
function paintPair(i) {
  var dlg = document.getElementById("anchor-lightbox");
  var pair = document.getElementById("lightbox-pair");
  if (!isPairLightbox(dlg) || !pair || !pairNav.items.length) return;
  pairNav.idx = (i + pairNav.items.length) % pairNav.items.length;
  var img = pairNav.items[pairNav.idx];
  var lab = document.getElementById("lightbox-label");
  if (lab) lab.textContent = (img.dataset.label || "").replace(/&middot;/g, "·");
  pair.innerHTML = "";
  [img.dataset.full, img.dataset.opposite].forEach(function (src) {
    if (!src) return;
    var full = document.createElement("img");
    full.src = src;
    pair.appendChild(full);
  });
  var pos = document.getElementById("lightbox-pair-pos");
  if (pos) pos.textContent = (pairNav.idx + 1) + "/" + pairNav.items.length;
  var prev = dlg.querySelector(".media-nav-prev");
  var next = dlg.querySelector(".media-nav-next");
  if (prev) prev.disabled = pairNav.items.length < 2;
  if (next) next.disabled = pairNav.items.length < 2;
}

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
      var on = p.dataset.tier === tab.dataset.tier;
      p.classList.toggle("hidden", !on);
      if (on) revealLazy(p);
    });
    if (album === "coverage") rememberRosterTier(tab.dataset.tier);
    return;
  }

  var rename = e.target.closest(".js-rename-char");
  if (rename) {
    e.preventDefault();
    e.stopPropagation();
    var dlg = document.getElementById("rename-char");
    var form = document.getElementById("rename-char-form");
    if (!dlg || !form) return;
    form.action = rename.getAttribute("data-action") || "";
    var field = rename.getAttribute("data-field") || "name";
    var input = form.querySelector("input[type=text]");
    if (input) {
      input.name = field;
      input.value = rename.getAttribute("data-name") || "";
      input.maxLength = parseInt(rename.getAttribute("data-max") || "60", 10) || 60;
    }
    if (!dlg.open) dlg.showModal();
    if (input) input.focus();
    return;
  }

  var gtab = e.target.closest(".gallery-char-tab");
  if (gtab) {
    var groot = gtab.closest(".tier-panel") || document;
    var gkey = gtab.getAttribute("data-char");
    groot.querySelectorAll(".gallery-char-tab").forEach(function (t) {
      t.classList.toggle("active", t === gtab);
    });
    groot.querySelectorAll(".gallery-char-panel").forEach(function (p) {
      var on = p.getAttribute("data-char") === gkey;
      p.classList.toggle("hidden", !on);
      if (on) revealLazy(p);
    });
    return;
  }

  var ftab = e.target.closest(".family-tab");
  if (ftab) {
    var root = ftab.closest(".gallery-char-panel") || ftab.closest(".tier-panel")
      || ftab.closest(".gallery-section") || document;
    root.querySelectorAll(".family-tab").forEach(function (t) {
      t.classList.toggle("active", t === ftab);
      t.setAttribute("aria-selected", t === ftab ? "true" : "false");
    });
    root.querySelectorAll(".family-panel").forEach(function (p) {
      p.classList.toggle("hidden", p.dataset.family !== ftab.dataset.family);
    });
    return;
  }

  var pairDlg = document.getElementById("anchor-lightbox");
  if (isPairLightbox(pairDlg) && pairDlg.open) {
    if (e.target.closest("#anchor-lightbox .media-nav-prev")) {
      e.preventDefault(); paintPair(pairNav.idx - 1); return;
    }
    if (e.target.closest("#anchor-lightbox .media-nav-next")) {
      e.preventDefault(); paintPair(pairNav.idx + 1); return;
    }
  }

  // a sheet opens beside its opposite view -- a character sheet is read as a
  // pair, front checked against back
  var img = e.target.closest(".anchor-open");
  if (img && isPairLightbox(document.getElementById("anchor-lightbox"))) {
    pairNav.items = Array.prototype.slice.call(
      document.querySelectorAll(".anchor-open[data-full]"));
    var at = pairNav.items.indexOf(img);
    if (at < 0) { pairNav.items = [img]; at = 0; }
    paintPair(at);
    document.getElementById("anchor-lightbox").showModal();
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
    var body = edit.closest(".playlist-body");
    var target = body && body.id ? "#" + body.id : "body";
    fix.querySelectorAll("form").forEach(function (f) {
      f.action = "/anchors/" + edit.dataset.anchor + "/fix";
      f.setAttribute("hx-post", f.action);
      f.setAttribute("hx-target", target);
      f.setAttribute("hx-swap", "innerHTML");
      f.setAttribute("hx-encoding", "multipart/form-data");
      if (window.htmx) htmx.process(f);
    });
    // the mask painter reads the source off the form it belongs to
    var maskForm = fix.querySelector(".mask-form");
    if (maskForm) {
      maskForm.dataset.src = edit.dataset.src;
      maskForm.querySelector("[name=mask_data]").value = "";
      var state = maskForm.querySelector(".js-mask-state");
      if (state) { state.hidden = true; state.textContent = "ready"; }
      maskForm.querySelector(".js-mask-submit").disabled = true;
    }
    fix.showModal();
  }
});

document.addEventListener("keydown", function (e) {
  var dlg = document.getElementById("anchor-lightbox");
  if (!isPairLightbox(dlg) || !dlg.open) return;
  if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
  if (e.key === "ArrowLeft") { e.preventDefault(); paintPair(pairNav.idx - 1); }
  if (e.key === "ArrowRight") { e.preventDefault(); paintPair(pairNav.idx + 1); }
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
function formatLocalTimes(root) {
  var scope = root && root.querySelectorAll ? root : document;
  var stamp = {year: "numeric", month: "short", day: "numeric",
               hour: "2-digit", minute: "2-digit"};
  scope.querySelectorAll("time.local-time").forEach(function (el) {
    var d = new Date(el.getAttribute("datetime"));
    if (isNaN(d)) return;
    el.textContent = d.toLocaleString(undefined, stamp);
    el.title = el.getAttribute("datetime") + " (UTC)";
  });
  scope.querySelectorAll("option[data-created]").forEach(function (opt) {
    var d = new Date(opt.getAttribute("data-created"));
    if (isNaN(d)) return;
    var label = opt.getAttribute("data-label") || opt.value;
    opt.textContent = label + " · " + d.toLocaleString(undefined, stamp);
  });
}
document.addEventListener("DOMContentLoaded", function () {
  formatLocalTimes(document);
  applyRerollChip(document.getElementById("job-chip"));
  applyClipsChip(document.getElementById("job-chip"));
});

// ---- keyboard review ------------------------------------------------------
// Fifty frames is a lot of mousing. J/K move, A approves the focused clip, R
// rerolls it. Ignored while typing, or the reroll note would trigger both.
document.addEventListener("keydown", function (e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  var t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" ||
            t.isContentEditable)) return;
  if (document.querySelector("dialog[open]")) return;
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

function initNavDrop() {
  var OPEN_MS = 300;
  var HOLD_MS = 2000;
  var drops = document.querySelectorAll(".nav-drop");
  if (!drops.length) return;

  function closeDrop(drop) {
    drop.classList.remove("open", "pinned");
    var t = drop.querySelector(":scope > a");
    if (t) t.setAttribute("aria-expanded", "false");
  }

  function openDrop(drop, pinned) {
    drops.forEach(function (other) {
      if (other !== drop) closeDrop(other);
    });
    drop.classList.add("open");
    if (pinned) drop.classList.add("pinned");
    var t = drop.querySelector(":scope > a");
    if (t) t.setAttribute("aria-expanded", "true");
  }

  drops.forEach(function (drop) {
    var trigger = drop.querySelector(":scope > a");
    if (!trigger) return;
    var openTimer = null;
    var closeTimer = null;
    function clearTimers() {
      clearTimeout(openTimer);
      clearTimeout(closeTimer);
    }
    drop.addEventListener("mouseenter", function () {
      clearTimers();
      if (drop.classList.contains("open")) return;
      openTimer = setTimeout(function () { openDrop(drop, false); }, OPEN_MS);
    });
    drop.addEventListener("mouseleave", function () {
      clearTimers();
      closeTimer = setTimeout(function () { closeDrop(drop); }, HOLD_MS);
    });
    drop.addEventListener("focusin", function () {
      clearTimers();
      openDrop(drop, false);
    });
    drop.addEventListener("focusout", function (e) {
      if (drop.contains(e.relatedTarget)) return;
      clearTimers();
      closeTimer = setTimeout(function () { closeDrop(drop); }, HOLD_MS);
    });
    trigger.addEventListener("click", function (e) {
      if (drop.classList.contains("open")) return;
      e.preventDefault();
      clearTimers();
      openDrop(drop, true);
    });
  });

  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest(".nav-drop")) return;
    drops.forEach(closeDrop);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    drops.forEach(closeDrop);
  });
}

document.addEventListener("DOMContentLoaded", function () {
  initGenreSelects("genre-select", "subgenre-select");
  initGenreSelects("genre2-select", "subgenre2-select");
  initGenreSelects("bulk-genre-select", "bulk-subgenre-select");
  initGenreSelects("bulk-genre2-select", "bulk-subgenre2-select");
  initGenreSelects("set-genre-select", "set-subgenre-select");
  initGenreSelects("set-genre2-select", "set-subgenre2-select");
  initNavDrop();
  initLibraryBulk();
  initAnchors();
  initClassificationLibrary();
  initAnchorBatch();
  initAnchorPrompts();
  initAnchorPaste();
  initViewCheckAll();
  initActorPick();
  initJobForms();       // every page, not just the ones with an anchor grid
  initSongPage();       // song page forms: fetch, no full-page submit
  initRunHistory();
  initAnchorPlan();
  hydrateLazy(document);
  sweepPendingClipCards();
  setInterval(sweepPendingClipCards, 3000);
});

// Off-screen plates / stills / clips stay as data-src until they approach
// the viewport. Native loading=lazy is not enough after an htmx panel swap
// of fifty scenes: the browser still queues every <video preload=metadata>.
function revealLazy(root) {
  if (!root) return;
  if (window.htmx) {
    root.querySelectorAll("[hx-get]").forEach(function (el) {
      if (el.getAttribute("hx-trigger") && el.getAttribute("hx-trigger").indexOf("revealed") !== -1) {
        window.htmx.trigger(el, "revealed");
      }
    });
  }
  hydrateLazy(root);
}

function hydrateLazy(root, eager) {
  var scope = root && root.querySelectorAll ? root : document;
  var nodes = scope.querySelectorAll("img.lazy-src[data-src], video.lazy-src[data-src]");
  if (!nodes.length) return;
  function load(el) {
    var src = el.getAttribute("data-src");
    if (!src) return;
    el.src = src;
    el.removeAttribute("data-src");
    el.classList.remove("lazy-src");
    if (el.tagName === "VIDEO") {
      el.muted = true;
      el.playsInline = true;
      el.addEventListener("loadeddata", function () { seekNonBlackFrame(el); }, {once: true});
    }
  }
  // Still thumbs must not wait for IntersectionObserver. After an htmx swap
  // (upload, pick, delete) a missed observe leaves the 3/4 grey tile forever.
  // Videos stay deferred — a panel of clips still must not all preload.
  var stills = [];
  var videos = [];
  Array.prototype.forEach.call(nodes, function (el) {
    if (el.tagName === "VIDEO") videos.push(el);
    else stills.push(el);
  });
  Array.prototype.forEach.call(stills, load);
  // Clip tiles sit in overflow-x strips / closed <details>. IntersectionObserver
  // misses them the same way pose thumbs did — the well stays empty. One or two
  // 4.8s takes per open scene; load them now.
  var clipVids = [];
  var restVids = [];
  Array.prototype.forEach.call(videos, function (el) {
    if (el.closest(".clip-frame")) clipVids.push(el);
    else restVids.push(el);
  });
  Array.prototype.forEach.call(clipVids, load);
  videos = restVids;
  if (!videos.length) return;
  if (eager || !("IntersectionObserver" in window)) {
    Array.prototype.forEach.call(videos, load);
    return;
  }
  if (!window._lazyMediaObs) {
    window._lazyMediaObs = new IntersectionObserver(function (ents) {
      ents.forEach(function (ent) {
        if (!ent.isIntersecting) return;
        load(ent.target);
        window._lazyMediaObs.unobserve(ent.target);
      });
    }, {rootMargin: "240px 0px", threshold: 0.01});
  }
  Array.prototype.forEach.call(videos, function (el) {
    window._lazyMediaObs.observe(el);
  });
}
document.body.addEventListener("htmx:beforeSwap", function (e) {
  var t = e.detail && e.detail.target;
  if (!t || !t.classList || !t.classList.contains("playlist-body")) return;
  var open = [];
  t.querySelectorAll("details.pl-fold[id]").forEach(function (d) {
    if (d.open) open.push(d.id);
  });
  var cast = t.querySelector(".cast-tab.active");
  var look = t.querySelector(".look-tab.active");
  t._plChrome = {
    open: open,
    cast: cast ? cast.getAttribute("data-cast") : "",
    look: look ? look.getAttribute("data-look") : ""
  };
});
document.body.addEventListener("htmx:beforeSwap", function (e) {
  var form = document.getElementById("anchor-form");
  var tgt = e.detail && e.detail.target;
  if (!form || !tgt || tgt.id !== "anchor-form") return;
  window._afOpen = [];
  form.querySelectorAll("details.disclose[data-fold]").forEach(function (d) {
    if (d.open) window._afOpen.push(d.getAttribute("data-fold"));
  });
});
document.body.addEventListener("htmx:afterSwap", function (e) {
  var target = e.detail && e.detail.target ? e.detail.target : e.target;
  formatLocalTimes(target);
  hydrateLazy(target);
  bindReorder(target);
  var af = document.getElementById("anchor-form");
  if (af && window._afOpen) {
    af.querySelectorAll("details.disclose[data-fold]").forEach(function (d) {
      if (window._afOpen.indexOf(d.getAttribute("data-fold")) >= 0) d.open = true;
    });
  }
  var chrome = target && target._plChrome;
  if (chrome) {
    (chrome.open || []).forEach(function (id) {
      var d = document.getElementById(id);
      if (!d) return;
      d.open = true;
      fillDeferredFold(d);
    });
    if (chrome.cast) {
      var ct = target.querySelector('.cast-tab[data-cast="' + chrome.cast + '"]');
      if (ct) ct.click();
    }
    if (chrome.look) {
      var lt = target.querySelector('.look-tab[data-look="' + chrome.look + '"]');
      if (lt) lt.click();
    }
  }
  var chip = (target && target.id === "job-chip") ? target
    : document.getElementById("job-chip");
  applyRerollChip(chip);
  applyClipsChip(chip);
});
document.addEventListener("toggle", function (e) {
  if (e.target && e.target.tagName === "DETAILS" && e.target.open) {
    hydrateLazy(e.target, true);
  }
}, true);

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

function initActorPick() {
  function syncPrimary(form) {
    var hid = form.querySelector('input[type="hidden"][name="character_id"]');
    if (!hid) return;
    var lead = form.querySelector('[name="actor_id"][value="lead"]');
    var extra = [];
    form.querySelectorAll('[name="actor_id"]:checked').forEach(function (cb) {
      if (cb.value !== "lead") extra.push(cb.value);
    });
    hid.value = ((!lead || !lead.checked) && extra.length === 1) ? extra[0] : "";
  }
  function swap(form) {
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
  }
  document.addEventListener("change", function (e) {
    var form = document.getElementById("anchor-form");
    if (!form || !e.target.closest || !e.target.closest("#anchor-form")) return;
    if (e.target.classList && e.target.classList.contains("actor-check-all")) {
      var on = e.target.checked;
      form.querySelectorAll('[name="actor_id"]').forEach(function (cb) { cb.checked = on; });
      syncPrimary(form);
      swap(form);
      return;
    }
    if (e.target.name === "actor_id") {
      var all = form.querySelector(".actor-check-all");
      var boxes = form.querySelectorAll('[name="actor_id"]');
      var n = 0;
      boxes.forEach(function (cb) { if (cb.checked) n++; });
      if (all) all.checked = boxes.length > 0 && n === boxes.length;
      syncPrimary(form);
      swap(form);
    }
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
    if (opt.value) api("/prompt-versions/select", {id: opt.value}).catch(function () {});
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
  if (!list) return;
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
  if (typeof htmx === "undefined") return;
  var chip = document.getElementById("job-chip");
  if (chip) htmx.ajax("GET", "/queue?chip=1", {target: "#job-chip", swap: "outerHTML"});
  var dlg = document.getElementById("jobs-modal");
  var body = document.getElementById("jobs-modal-body");
  if (dlg && dlg.open && body) {
    htmx.ajax("GET", "/queue", {target: "#jobs-modal-body", swap: "innerHTML"});
  }
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

// Song page: every control is a fetch. The same POST still 303s without JS.
function initSongPage() {
  var page = document.getElementById("song-page");
  if (!page) return;
  var songId = page.getAttribute("data-song-id");
  var status = document.getElementById("song-status") || document.getElementById("job-status");

  function flash(msg, isErr) {
    if (!status) return;
    status.hidden = false;
    status.textContent = msg;
    status.classList.toggle("err", !!isErr);
  }

  function paintSong(d) {
    if (!d || !d.song) return;
    var title = page.querySelector("h1");
    if (title) {
      var tag = title.querySelector(".tag.explicit");
      if (d.song.explicit && !tag) {
        title.insertAdjacentHTML("beforeend", ' <span class="tag explicit">EXPLICIT</span>');
      } else if (!d.song.explicit && tag) {
        tag.remove();
      }
    }
    var expBtn = page.querySelector('form[action$="/explicit"] button');
    if (expBtn) expBtn.textContent = d.song.explicit ? "Mark clean" : "Mark explicit";
    var lyricsTa = page.querySelector('textarea[name="lyrics_text"]');
    if (lyricsTa && d.song.lyrics != null && lyricsTa.value === lyricsTa.defaultValue) {
      lyricsTa.value = d.song.lyrics;
      lyricsTa.defaultValue = d.song.lyrics;
    }
    var styleTa = page.querySelector('textarea[name="style_text"]');
    if (styleTa && d.song.style_text != null && styleTa.value === styleTa.defaultValue) {
      styleTa.value = d.song.style_text;
      styleTa.defaultValue = d.song.style_text;
    }
    var bpmLine = page.querySelector("#fold-analysis .meta");
    if (bpmLine && d.song.bpm) {
      var bits = [Number(d.song.bpm).toFixed(1) + " BPM"];
      if (d.song.key) bits.push("key " + d.song.key);
      if (d.song.energy != null) bits.push("energy " + Number(d.song.energy).toFixed(3));
      bpmLine.textContent = bits.join(" · ");
    }
    if (d.storyboards && d.storyboards.length) {
      var list = page.querySelector(".tier-links");
      if (!list) {
        var sbCard = page.querySelector("#sb-form") && page.querySelector("#sb-form").closest(".card");
        if (sbCard) {
          list = document.createElement("div");
          list.className = "tier-actions tier-links";
          var form = page.querySelector("#sb-form");
          sbCard.insertBefore(list, form);
        }
      }
      if (list) {
        d.storyboards.forEach(function (b) {
          if (list.querySelector('[data-tier="' + b.tier + '"]')) return;
          var label = b.tier === "xxx" ? "XXX" : b.tier === "pg13" ? "PG-13"
            : String(b.tier || "").toUpperCase();
          var det = document.createElement("details");
          det.className = "tier-board";
          det.dataset.tier = b.tier;
          det.setAttribute("hx-get", "/songs/" + songId + "/storyboard/" + b.tier + "/panel");
          det.setAttribute("hx-trigger", "toggle once");
          det.setAttribute("hx-target", "find .tier-board-body");
          det.setAttribute("hx-swap", "innerHTML");
          det.innerHTML = "<summary title=\"" + label + ": click to expand or collapse scenes\">" +
            "<span>" + label + " · " +
            (b.scene_count || "?") + " scenes</span></summary>" +
            "<div class=\"tier-board-body\"><p class=\"muted\">Loading scenes…</p></div>";
          list.appendChild(det);
          if (typeof htmx !== "undefined") htmx.process(det);
        });
      }
    }
  }

  function refreshSong() {
    return api("/api/songs/" + songId).then(paintSong);
  }

  function followJob(d, form) {
    var jid = d.job_id || (d.job_ids && d.job_ids[0]);
    if (!jid) {
      flash("Saved.");
      return refreshSong();
    }
    refreshQueue();
    flash("Queued job #" + jid + (d.kind ? " (" + d.kind + ")" : ""));
    if (form && form.classList.contains("reroll-bar")) {
      paintRerollPlaceholders(form, d);
    }
    if (form && form.classList.contains("clip-bar")) {
      paintClipPlaceholders(form, d);
    }
    watchJob(jid, "song-status", function (job) {
      refreshQueue();
      if (job.status === "done") {
        if (form && (form.classList.contains("reroll-bar") ||
                     form.classList.contains("clip-bar"))) refreshSceneRow(form);
        else refreshSong();
        return;
      }
      if (job.status === "failed" || job.status === "cancelled") {
        clearRerollPlaceholders(jid);
        if (form && form.classList.contains("clip-bar")) refreshSceneRow(form);
        else clearClipPlaceholders(jid);
      }
    });
  }

  page.addEventListener("submit", function (e) {
    var form = e.target.closest("form");
    if (!form || !page.contains(form)) return;
    if (e.defaultPrevented) return;
    var action = form.getAttribute("action") || "";
    if (action.indexOf("/jobs/") === 0) return;
    if (form.hasAttribute("hx-post") || form.hasAttribute("hx-get")) return;
    e.preventDefault();
    var btn = e.submitter || form.querySelector("button[type=submit], button:not([type])");
    if (btn) btn.disabled = true;
    var dest = (e.submitter && e.submitter.getAttribute("formaction")) || action;
    var note = saveNoteNear(form);
    if (note) say2(note, "saving…");
    if (form.id && form.id.indexOf("sb-del-") === 0) {
      var nField = form.querySelector("[name=n]");
      var verSel = (form.closest(".sb-panel") || page).querySelector("select.sb-ver");
      if (nField && verSel) nField.value = verSel.value;
    }
    api(dest, new FormData(form))
      .then(function (d) {
        if (d.deleted != null && form.classList.contains("delete-song")) {
          location.href = "/";
          return;
        }
        if (d.explicit !== undefined && form.getAttribute("action") &&
            form.getAttribute("action").indexOf("/explicit") !== -1) {
          if (btn) btn.textContent = d.explicit ? "Mark clean" : "Mark explicit";
          var tag = page.querySelector("h1 .tag.explicit");
          if (d.explicit && !tag) {
            page.querySelector("h1").insertAdjacentHTML(
              "beforeend", ' <span class="tag explicit">EXPLICIT</span>');
          } else if (!d.explicit && tag) {
            tag.remove();
          }
          flash(d.explicit ? "Marked explicit." : "Marked clean.");
          return;
        }
        if (d.job_id || (d.job_ids && d.job_ids.length)) return followJob(d, form);
        if (d.versions || d.version) {
          paintSbVersions(form, d.versions, d.version && d.version.n);
          if (note) {
            if (form.id && form.id.indexOf("sb-del-") === 0) say2(note, "deleted");
            else if (form.id && form.id.indexOf("sb-restore-") === 0) say2(note, "restored");
            else say2(note, "version saved");
          }
          if (form.id && form.id.indexOf("sb-restore-") === 0) reloadSbPanel(form);
          return;
        }
        if (form.classList.contains("pose-bind")) {
          paintPoseBind(form, d);
          say2(note, d.source === "saved" ? "pinned" : (d.sheet_id ? "saved" : "cleared"));
          return;
        }
        if (form.classList.contains("still-pick")) {
          paintStillApprove(form.closest(".ref-frame"), !!d.approved);
          if (note) say2(note, d.approved ? "approved" : "unapproved");
          return;
        }
        if (d.deleted != null && /\/refs\/\d+\/delete$/.test(action)) {
          var goneFig = form.closest(".ref-frame");
          if (goneFig) goneFig.remove();
          if (note) say2(note, "deleted");
          return;
        }
        if (note) {
          if (form.id && form.id.indexOf("sb-snap-") === 0) say2(note, "version saved");
          else if (form.id && form.id.indexOf("sb-restore-") === 0) say2(note, "restored");
          else say2(note, "saved");
          return;
        }
        flash("Saved.");
        return refreshSong();
      })
      .catch(function (err) {
        if (note) say2(note, err.message, true);
        else flash(err.message, true);
      })
      .then(function () { if (btn) btn.disabled = false; });
  });

  page.addEventListener("click", function (e) {
    var none = e.target.closest && e.target.closest(".js-pose-none");
    if (!none || !page.contains(none)) return;
    applyPose(none.closest(".pose-bind"), "0");
  });

}

var POSE_BIND_COPY = {
  saved: ["Pinned", "Pinned: you chose this plate. Generate refs uses it as the pose (image2). Change the list and save to pick another, or clear bind to let the matcher decide."],
  auto: ["Suggested", "Suggested: the matcher picked this from the scene pose word. Not pinned — save to keep this plate if you regenerate refs."],
  missing: ["Missing sheet", "The pinned sheet is gone from the album. Pick another plate and save."],
  none: ["No plate", "No plate. Generate refs uses identity front only. Pick a plate and save to pin one."]
};

function saveNoteNear(form) {
  if (!form) return null;
  return form.querySelector(".save-note")
    || (form.closest(".preview-stills") && form.closest(".preview-stills").querySelector(".save-note"))
    || (form.closest(".preview-clips") && form.closest(".preview-clips").querySelector(".save-note"))
    || (form.closest(".sb-panel") && form.closest(".sb-panel").querySelector(".save-note"));
}

function sayPending(el, msg) {
  if (!el) return;
  el.textContent = msg || "";
  el.className = (el.className.replace(/\s*flash-(ok|fail)\b/g, "").replace(/\s+/g, " ").trim());
}

function seekNonBlackFrame(video) {
  var d = video.duration;
  if (!isFinite(d) || d <= 0) return;
  var canvas = document.createElement("canvas");
  var ctx = canvas.getContext("2d", {willReadFrequently: true});
  var times = [0.2, 0.4, 0.7, 1.1, 1.6, d * 0.12, d * 0.2, d * 0.3, d * 0.45];
  var seen = {};
  var queue = [];
  times.forEach(function (t) {
    t = Math.min(Math.max(0.08, t), Math.max(0.08, d - 0.05));
    var key = t.toFixed(2);
    if (seen[key]) return;
    seen[key] = true;
    queue.push(t);
  });
  queue.sort(function (a, b) { return a - b; });
  var i = 0;
  function frameIsLit() {
    var w = 24, h = 24;
    canvas.width = w;
    canvas.height = h;
    try {
      ctx.drawImage(video, 0, 0, w, h);
      var data = ctx.getImageData(0, 0, w, h).data;
    } catch (err) {
      return true;
    }
    var sum = 0;
    for (var p = 0; p < data.length; p += 4) sum += data[p] + data[p + 1] + data[p + 2];
    return (sum / (w * h)) > 24;
  }
  function step() {
    if (i >= queue.length) return;
    var t = queue[i++];
    var onSeek = function () {
      video.removeEventListener("seeked", onSeek);
      if (frameIsLit()) return;
      step();
    };
    video.addEventListener("seeked", onSeek);
    try { video.currentTime = t; } catch (err) { step(); }
  }
  step();
}

function paintStillApprove(fig, approved) {
  if (!fig) return;
  fig.classList.toggle("approved", !!approved);
  var pickBtn = fig.querySelector(".still-pick button");
  if (pickBtn) {
    var label = approved ? "Unapprove this still" : "Use this still as the scene reference";
    pickBtn.classList.toggle("on", !!approved);
    pickBtn.title = label;
    pickBtn.setAttribute("aria-label", label);
    if (!pickBtn.querySelector("svg")) pickBtn.textContent = approved ? "Unapprove" : "Use this still";
  }
  var strip = fig.closest(".scene-refs, .preview-stills");
  if (approved && strip) {
    strip.querySelectorAll(".ref-frame").forEach(function (other) {
      if (other === fig) return;
      other.classList.remove("approved");
      var ob = other.querySelector(".still-pick button");
      if (ob) ob.textContent = "Use this still";
      var tag = other.querySelector(".tag.done");
      if (tag) tag.remove();
    });
    if (!fig.querySelector(".tag.done")) {
      var cap = fig.querySelector("figcaption");
      if (cap) {
        var t = document.createElement("span");
        t.className = "tag done";
        t.textContent = "approved";
        cap.appendChild(document.createTextNode(" "));
        cap.appendChild(t);
      }
    }
  } else {
    var gone = fig.querySelector(".tag.done");
    if (gone) gone.remove();
  }
}

function markPosePick(form, sheetId) {
  if (!form) return;
  var want = String(sheetId == null ? 0 : sheetId);
  var hid = form.querySelector('input[name=sheet_id]');
  if (hid) hid.value = want;
  form.querySelectorAll(".pose-pick").forEach(function (lab) {
    var id = lab.getAttribute("data-sheet-id");
    if (id == null) {
      var inp = lab.querySelector("input[name=sheet_id]");
      id = inp ? inp.value : "";
    }
    var on = String(id) === want;
    lab.classList.toggle("on", on);
    var inp = lab.querySelector("input[name=sheet_id]");
    if (inp) inp.checked = on;
  });
}

function applyPose(form, sheetId) {
  if (!form) return;
  markPosePick(form, sheetId);
  var dest = form.getAttribute("action");
  if (!dest) return;
  var note = form.querySelector(".save-note");
  if (note) say2(note, "saving…");
  return api(dest, new FormData(form)).then(function (d) {
    paintPoseBind(form, d);
    if (note) say2(note, d.source === "saved" ? "pinned" : (d.sheet_id ? "saved" : "cleared"));
    return d;
  }).catch(function (err) {
    if (note) say2(note, err.message, true);
    throw err;
  });
}

document.addEventListener("submit", function (e) {
  var form = e.target && e.target.closest && e.target.closest("form.pose-bind");
  if (!form) return;
  e.preventDefault();
  var hid = form.querySelector('input[name=sheet_id]');
  applyPose(form, hid ? hid.value : "0");
}, true);

document.addEventListener("submit", function (e) {
  var form = e.target && e.target.closest && e.target.closest("form.clip-bar");
  if (!form) return;
  e.preventDefault();
  var dest = form.getAttribute("action");
  if (!dest) return;
  var note = form.querySelector(".save-note");
  if (note) say2(note, "saving…");
  var btn = form.querySelector('button[type=submit], button:not([type])');
  if (btn) btn.disabled = true;
  api(dest, new FormData(form)).then(function (d) {
    if (note) say2(note, d.job_id ? ("queued #" + d.job_id) : "queued");
    paintClipPlaceholders(form, d);
    var jid = d.job_id || (d.job_ids && d.job_ids[0]);
    if (!jid) return;
    refreshQueue();
    watchJob(jid, "song-status", function (job) {
      if (job.status === "failed" || job.status === "cancelled") {
        clearClipPlaceholders(jid);
      }
      if (job.status === "done" || job.status === "failed" ||
          job.status === "cancelled") {
        refreshSceneRow(form);
        refreshQueue();
      }
    });
  }).catch(function (err) {
    if (note) say2(note, err.message, true);
  }).then(function () { if (btn) btn.disabled = false; });
}, true);

function scenePromptCtx(el) {
  var scene = el && el.closest && el.closest(".scene");
  if (!scene) return null;
  return {
    scene: scene,
    song: scene.getAttribute("data-song"),
    tier: scene.getAttribute("data-tier"),
    num: scene.getAttribute("data-num"),
    note: scene.querySelector(".scene-save-row .save-note")
  };
}

function sceneFieldUrl(ctx, tail) {
  return "/songs/" + ctx.song + "/storyboard/" + encodeURIComponent(ctx.tier) +
    "/scene/" + ctx.num + "/" + tail;
}

function fillSceneVerSelect(sel, versions, keep) {
  if (!sel) return;
  var want = keep != null ? String(keep) : sel.value;
  sel.innerHTML = "";
  var cur = document.createElement("option");
  cur.value = "";
  cur.textContent = "current";
  sel.appendChild(cur);
  (versions || []).forEach(function (v) {
    var opt = document.createElement("option");
    opt.value = v.n;
    opt.textContent = v.label || ("v" + v.n);
    sel.appendChild(opt);
  });
  if (want) sel.value = want;
}

document.addEventListener("click", function (e) {
  var del = e.target.closest && e.target.closest(".js-clip-del");
  if (del) {
    e.preventDefault();
    e.stopPropagation();
    var ctx = scenePromptCtx(del);
    var idx = del.getAttribute("data-clip-idx");
    if (!ctx || idx == null) return;
    api("/songs/" + ctx.song + "/clips/" + idx + "/delete", {tier: ctx.tier}).then(function () {
      document.querySelectorAll(
        '.js-clip-preview[data-clip-idx="' + idx + '"]'
      ).forEach(function (el) {
        if (ctx.tier && el.getAttribute("data-tier") &&
            el.getAttribute("data-tier") !== ctx.tier) return;
        var card = el.closest(".clip-frame") || el;
        if (card.parentNode) card.remove();
      });
    }).catch(function (err) {
      if (ctx.note) say2(ctx.note, err.message, true);
    });
    return;
  }
  var dismiss = e.target.closest && e.target.closest(".js-clip-fail-dismiss");
  if (dismiss) {
    e.preventDefault();
    var ctx = scenePromptCtx(dismiss);
    var jid = dismiss.getAttribute("data-job-id");
    if (!ctx || !jid) return;
    api(sceneFieldUrl(ctx, "clip-job/" + jid + "/dismiss"), {}).then(function () {
      var fig = dismiss.closest(".clip-failed");
      if (fig) fig.remove();
    }).catch(function (err) {
      if (ctx.note) say2(ctx.note, err.message, true);
    });
    return;
  }
  var draft = e.target.closest && e.target.closest(".js-scene-draft");
  if (draft) {
    e.preventDefault();
    var ctx = scenePromptCtx(draft);
    var field = draft.getAttribute("data-field");
    if (!ctx || !field) return;
    draft.disabled = true;
    if (ctx.note) say2(ctx.note, "suggesting…");
    api(sceneFieldUrl(ctx, "draft"), {field: field}).then(function (d) {
      var ta = ctx.scene.querySelector('textarea[name="' + field + '"]');
      if (ta && d.text) ta.value = d.text;
      if (ctx.note) say2(ctx.note, "suggested — save the scene to keep it");
    }).catch(function (err) {
      if (ctx.note) say2(ctx.note, err.message, true);
    }).then(function () { draft.disabled = false; });
    return;
  }
  var saveV = e.target.closest && e.target.closest(".js-scene-ver-save");
  if (saveV) {
    e.preventDefault();
    var ctx = scenePromptCtx(saveV);
    var field = saveV.getAttribute("data-field");
    var box = saveV.closest(".prompt-field");
    var ta = box && box.querySelector("textarea");
    if (!ctx || !field || !ta) return;
    api(sceneFieldUrl(ctx, "field-version"), {field: field, text: ta.value}).then(function (d) {
      var sel = box.querySelector(".js-scene-ver");
      var hold = box.querySelector(".js-scene-ver-json");
      if (hold) hold.textContent = JSON.stringify(d.versions || []);
      fillSceneVerSelect(sel, d.versions, d.n);
      if (ctx.note) say2(ctx.note, "version saved");
    }).catch(function (err) {
      if (ctx.note) say2(ctx.note, err.message, true);
    });
  }
});

document.addEventListener("change", function (e) {
  var sel = e.target.closest && e.target.closest(".js-scene-ver");
  if (!sel) return;
  var box = sel.closest(".prompt-field");
  var hold = box && box.querySelector(".js-scene-ver-json");
  var ta = box && box.querySelector("textarea");
  var ctx = scenePromptCtx(sel);
  if (!hold || !ta || !sel.value || !ctx) return;
  var vers = [];
  try { vers = JSON.parse(hold.textContent || "[]"); } catch (err) { return; }
  var hit = vers.filter(function (v) { return String(v.n) === String(sel.value); })[0];
  if (hit && hit.text != null) ta.value = hit.text;
  api(sceneFieldUrl(ctx, "field-version/apply"), {
    field: sel.getAttribute("data-field"), n: sel.value
  }).then(function (d) {
    if (d.text != null) ta.value = d.text;
    if (ctx.note) say2(ctx.note, "version current");
  }).catch(function (err) {
    if (ctx.note) say2(ctx.note, err.message, true);
  });
});

document.addEventListener("error", function (e) {
  var img = e.target;
  if (!img || img.tagName !== "IMG") return;
  if (!img.classList.contains("pose-pick-thumb") &&
      !(img.closest && img.closest(".pose-under"))) return;
  img.classList.add("pose-thumb-empty");
  img.removeAttribute("src");
  img.alt = "";
}, true);

function paintPoseBind(form, d) {
  if (!form || !d) return;
  var src = d.source || "none";
  var pair = POSE_BIND_COPY[src] || POSE_BIND_COPY.none;
  var label = form.querySelector(".pose-bind-label");
  var help = form.querySelector(".help-tip");
  if (label) {
    label.setAttribute("data-source", src);
    label.textContent = pair[0];
  }
  if (help) {
    help.title = "What " + pair[0] + " means";
    help.setAttribute("aria-label", "What " + pair[0] + " means");
    help.setAttribute("data-label", pair[0]);
    help.setAttribute("data-help", pair[1]);
  }
  markPosePick(form, d.sheet_id);
  var under = form.querySelector(".pose-under");
  var btn = under && under.querySelector(".thumb-open");
  var empty = under && under.querySelector(":scope > .pose-thumb-empty");
  var pick = form.querySelector(".pose-pick.on");
  var pickThumb = pick && (pick.getAttribute("data-thumb") || pick.getAttribute("data-full"));
  if (d.url && under) {
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.className = "js-pose-open thumb-open";
      if (empty) empty.replaceWith(btn);
      else under.insertBefore(btn, under.firstChild);
    }
    btn.setAttribute("data-full", d.url);
    btn.setAttribute("data-thumb", d.url);
    btn.setAttribute("data-sheet-id", String(d.sheet_id || 0));
    btn.setAttribute("data-label", d.label || "pose plate");
    btn.title = "Open the pose plate full size";
    var img = btn.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      img.className = "anchor-thumb";
      img.alt = "";
      btn.appendChild(img);
    }
    img.src = (pickThumb || d.url);
    img.removeAttribute("data-src");
    img.classList.remove("lazy-src");
  } else if (btn) {
    var span = document.createElement("span");
    span.className = "anchor-thumb pose-thumb-empty";
    span.setAttribute("aria-hidden", "true");
    btn.replaceWith(span);
  }
  var on = form.querySelector(".pose-pick.on");
  if (on && on.scrollIntoView) on.scrollIntoView({inline: "nearest", block: "nearest"});
}

(function () {
  var dlg = document.getElementById("pose-gallery");
  if (!dlg) return;
  var img = document.getElementById("pose-gallery-img");
  var q = document.getElementById("pose-gallery-q");
  var gridBtn = document.getElementById("pose-gallery-grid");
  var thumbs = document.getElementById("pose-gallery-thumbs");
  var useBtn = document.getElementById("pose-gallery-use");
  var searchBtn = document.getElementById("pose-gallery-search-btn");
  var clearBtn = document.getElementById("pose-gallery-clear");
  var form = null;
  var items = [];
  var shown = [];
  var idx = 0;

  function current() { return shown[idx] || null; }

  function hay(el) {
    return ((el.getAttribute("data-label") || "") + " " +
            (el.getAttribute("title") || "")).toLowerCase();
  }

  function filtered() {
    var needle = ((q && q.value) || "").trim().toLowerCase();
    if (!needle) return items.slice();
    return items.filter(function (el) { return hay(el).indexOf(needle) >= 0; });
  }

  function setGallery(on) {
    if (thumbs) thumbs.hidden = !on;
    dlg.classList.toggle("gallery-on", !!on);
    if (gridBtn) gridBtn.setAttribute("aria-pressed", on ? "true" : "false");
  }

  function syncSearchIcon() {
    var focused = q && document.activeElement === q;
    if (searchBtn) searchBtn.hidden = !!focused;
    if (clearBtn) clearBtn.hidden = !focused;
  }

  function applyCurrent() {
    var el = current();
    if (!form || !el) return;
    applyPose(form, el.getAttribute("data-sheet-id") || "0");
    dlg.close();
  }

  function paintGrid() {
    if (!thumbs) return;
    thumbs.innerHTML = "";
    shown.forEach(function (el, i) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "pose-pick" + (i === idx ? " on" : "");
      b.setAttribute("data-i", String(i));
      var src = el.getAttribute("data-thumb") || el.getAttribute("data-full") || "";
      if (src) {
        var im = document.createElement("img");
        im.className = "pose-pick-thumb";
        im.src = src;
        im.alt = el.getAttribute("data-label") || "";
        b.appendChild(im);
      } else {
        var empty = document.createElement("span");
        empty.className = "pose-pick-thumb pose-thumb-empty";
        b.appendChild(empty);
      }
      var cap = document.createElement("span");
      cap.className = "pose-pick-cap";
      cap.textContent = el.getAttribute("data-label") || "";
      b.appendChild(cap);
      thumbs.appendChild(b);
    });
  }

  function show(i) {
    shown = filtered();
    if (!shown.length) {
      if (img) img.removeAttribute("src");
      var emptyLab = document.getElementById("pose-gallery-label");
      if (emptyLab) emptyLab.textContent = "No plates match";
      var emptyPos = document.getElementById("pose-gallery-pos");
      if (emptyPos) emptyPos.textContent = "0 / 0";
      paintGrid();
      return;
    }
    idx = ((i % shown.length) + shown.length) % shown.length;
    var el = shown[idx];
    if (img) img.src = el.getAttribute("data-full") || "";
    var lab = document.getElementById("pose-gallery-label");
    if (lab) lab.textContent = el.getAttribute("data-label") || "Pose plate";
    var pos = document.getElementById("pose-gallery-pos");
    if (pos) pos.textContent = (idx + 1) + " / " + shown.length;
    paintGrid();
  }

  function openFrom(el) {
    form = el.closest(".pose-bind");
    var strip = form && form.querySelector(".pose-picks");
    items = strip ? Array.prototype.slice.call(strip.querySelectorAll(".js-pose-open[data-full]")) : [];
    if (!items.length && el.getAttribute("data-full")) items = [el];
    if (q) q.value = "";
    var at = items.indexOf(el);
    if (at < 0) {
      items.forEach(function (it, i) {
        if (it.getAttribute("data-sheet-id") === el.getAttribute("data-sheet-id")) at = i;
      });
    }
    setGallery(false);
    show(at < 0 ? 0 : at);
    if (typeof dlg.showModal === "function") dlg.showModal();
    if (q) q.focus();
    syncSearchIcon();
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("#pose-gallery .media-nav-prev")) {
      e.preventDefault();
      show(idx - 1);
      return;
    }
    if (e.target.closest("#pose-gallery .media-nav-next")) {
      e.preventDefault();
      show(idx + 1);
      return;
    }
    var cell = e.target.closest("#pose-gallery-thumbs .pose-pick");
    if (cell) {
      e.preventDefault();
      show(parseInt(cell.getAttribute("data-i"), 10) || 0);
      applyCurrent();
      return;
    }
    var btn = e.target.closest(".js-pose-open");
    if (btn && btn.getAttribute("data-full")) {
      e.preventDefault();
      openFrom(btn);
    }
  });

  if (q) {
    q.addEventListener("input", function () {
      if (q.value.trim()) setGallery(true);
      show(idx);
    });
    q.addEventListener("focus", syncSearchIcon);
    q.addEventListener("blur", syncSearchIcon);
  }
  if (clearBtn) {
    clearBtn.addEventListener("pointerdown", function (e) {
      e.preventDefault();
      if (q) {
        q.value = "";
        q.focus();
      }
      show(0);
    });
  }

  if (gridBtn) gridBtn.addEventListener("click", function () {
    setGallery(thumbs && thumbs.hidden);
    show(idx);
  });

  if (useBtn) useBtn.addEventListener("click", applyCurrent);

  document.addEventListener("keydown", function (e) {
    if (!dlg.open) return;
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); show(idx - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); show(idx + 1); }
  });
})();

function paintSbVersions(form, versions, selected) {
  var panel = form && form.closest(".sb-panel");
  if (!panel) return;
  var sel = panel.querySelector("select.sb-ver");
  if (!sel) return;
  var keep = selected != null ? String(selected) : sel.value;
  sel.innerHTML = "";
  (versions || []).forEach(function (v) {
    var opt = document.createElement("option");
    opt.value = v.n;
    var label = v.label || ("v" + v.n);
    opt.setAttribute("data-label", label);
    if (v.created) {
      var iso = typeof v.created === "number"
        ? new Date(v.created * 1000).toISOString()
        : String(v.created);
      opt.setAttribute("data-created", iso.indexOf("Z") === -1 && iso.indexOf("T") === -1
        ? new Date(Number(v.created) * 1000).toISOString()
        : iso);
    }
    opt.textContent = label;
    sel.appendChild(opt);
  });
  if (!versions || !versions.length) {
    var empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "No snapshots yet";
    sel.appendChild(empty);
  }
  if (keep) sel.value = keep;
  formatLocalTimes(sel);
  var none = !versions || !versions.length;
  var del = panel.querySelector(".sb-ver-del");
  var rest = panel.querySelector(".sb-ver-restore");
  if (del) del.disabled = none;
  if (rest) rest.disabled = none;
}

function reloadSbPanel(form) {
  var board = form && form.closest(".tier-board");
  var dest = board && board.getAttribute("hx-get");
  var body = board && board.querySelector(".tier-board-body");
  if (!dest || !body || typeof htmx === "undefined") return;
  htmx.ajax("GET", dest, {target: body, swap: "innerHTML"});
}

function paintRerollPlaceholders(form, d) {
  var row = form && form.closest(".stills-row");
  if (!row) return;
  var n = Math.max(1, parseInt(d.n, 10) || 4);
  var strip = row.querySelector(".scene-refs");
  if (!strip) {
    strip = document.createElement("div");
    strip.className = "media-strip scene-refs";
    var empty = row.querySelector("p.empty");
    if (empty) empty.replaceWith(strip);
    else row.appendChild(strip);
  }
  form.dataset.rerollJob = String(d.job_id);
  clearRerollPlaceholders(d.job_id, strip);
  for (var i = 0; i < n; i++) {
    var fig = document.createElement("figure");
    fig.className = "ref-frame clip-tile still-pending";
    fig.setAttribute("data-job-id", String(d.job_id));
    fig.setAttribute("aria-label", "Rendering still");
    fig.innerHTML = "<div class=\"still-thumb\">" +
      "<div class=\"thumb-open still-skeleton\" aria-hidden=\"true\"></div>" +
      "</div><figcaption>rendering…</figcaption>" +
      "<div class=\"still-icons\" aria-hidden=\"true\"></div>";
    strip.appendChild(fig);
  }
}

function clearRerollPlaceholders(jobId, root) {
  var scope = root || document;
  if (!jobId) return;
  scope.querySelectorAll('.still-pending[data-job-id="' + jobId + '"]').forEach(function (el) {
    el.remove();
  });
}

function paintClipPlaceholders(form, d) {
  var row = form && form.closest(".clips-row");
  if (!row) return;
  var n = Math.max(1, parseInt(d.n, 10) || (d.job_ids && d.job_ids.length) || 1);
  var strip = row.querySelector(".scene-clips");
  if (!strip) {
    strip = document.createElement("div");
    strip.className = "media-strip scene-clips";
    var empty = row.querySelector("p.empty");
    if (empty) empty.replaceWith(strip);
    else row.appendChild(strip);
  }
  var emptyP = strip.querySelector("p.empty");
  if (emptyP) emptyP.remove();
  var jid = d.job_id || (d.job_ids && d.job_ids[0]);
  if (jid) form.dataset.clipJob = String(jid);
  clearClipPlaceholders(jid, strip);
  for (var i = 0; i < n; i++) {
    var fig = document.createElement("figure");
    fig.className = "clip-frame clip-tile clip-pending";
    if (jid) fig.setAttribute("data-job-id", String(jid));
    fig.setAttribute("aria-label", "Rendering clip");
    fig.innerHTML = "<div class=\"still-thumb\">" +
      "<div class=\"thumb-open still-skeleton\" aria-hidden=\"true\"></div>" +
      "</div><figcaption>rendering…</figcaption>";
    strip.appendChild(fig);
  }
}

function clearClipPlaceholders(jobId, root) {
  var scope = root || document;
  if (!jobId) return;
  scope.querySelectorAll('.clip-pending[data-job-id="' + jobId + '"]').forEach(function (el) {
    el.remove();
  });
}

var _pendingClipAsk = {};
function sweepPendingClipCards() {
  var cards = document.querySelectorAll(".clip-pending[data-job-id]");
  if (!cards.length) return;
  var seen = {};
  Array.prototype.forEach.call(cards, function (fig) {
    var jid = fig.getAttribute("data-job-id");
    if (!jid || seen[jid]) return;
    seen[jid] = true;
    var now = Date.now();
    if (_pendingClipAsk[jid] && now - _pendingClipAsk[jid] < 2000) return;
    _pendingClipAsk[jid] = now;
    var scene = fig.closest(".scene");
    fetch("/jobs/" + jid, {headers: {Accept: "application/json"}})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (job) {
        if (!job) return;
        if (job.status === "failed" || job.status === "cancelled") {
          clearClipPlaceholders(jid);
          if (scene) {
            refreshSceneEl(scene, scene.getAttribute("data-song"),
                           scene.getAttribute("data-tier"), jid);
          }
          return;
        }
        if (job.status === "done") {
          if (scene) {
            refreshSceneEl(scene, scene.getAttribute("data-song"),
                           scene.getAttribute("data-tier"), jid);
          } else {
            clearClipPlaceholders(jid);
          }
        }
      })
      .catch(function () {});
  });
}

function songIdFromForm(form) {
  var page = document.getElementById("song-page");
  if (page && page.getAttribute("data-song-id")) return page.getAttribute("data-song-id");
  var action = (form && form.getAttribute("action")) || "";
  var m = action.match(/\/songs\/(\d+)\//);
  return m ? m[1] : "";
}

function sceneTier(form) {
  var panel = form && form.closest(".sb-panel");
  if (panel && panel.getAttribute("data-tier")) return panel.getAttribute("data-tier");
  var inp = form && form.querySelector("[name=tier]");
  return inp ? inp.value : "";
}

function refreshSceneRow(form) {
  var scene = form && form.closest(".scene");
  refreshSceneEl(scene, songIdFromForm(form), sceneTier(form),
                 form && (form.dataset.rerollJob || form.dataset.clipJob));
}

function sceneElForClip(tier, clipIdx) {
  var sel = '.sb-panel[data-tier="' + tier + '"] .reroll-bar input[name=clip_idx][value="' + clipIdx + '"]';
  var input = document.querySelector(sel);
  return input ? input.closest(".scene") : null;
}

function refreshSceneEl(scene, songId, tier, jobId) {
  if (!scene || !scene.id || !songId || !tier) return;
  var num = scene.id.replace("scene-", "");
  fetch("/songs/" + songId + "/storyboard/" + encodeURIComponent(tier) + "/scene/" + num, {
    headers: {"Accept": "text/html"}
  }).then(function (r) {
    if (!r.ok) throw new Error("could not refresh scene");
    return r.text();
  }).then(function (html) {
    var wrap = document.createElement("div");
    wrap.innerHTML = html.trim();
    var next = wrap.querySelector(".scene") || wrap.firstElementChild;
    if (!next) return;
    var wasOpen = scene.open;
    scene.replaceWith(next);
    next.open = wasOpen || true;
    if (typeof htmx !== "undefined") htmx.process(next);
    formatLocalTimes(next);
    hydrateLazy(next, true);
  }).catch(function () {
    if (jobId) {
      clearRerollPlaceholders(jobId);
      clearClipPlaceholders(jobId);
    }
  });
}

var _appliedReroll = {};

function applyRerollChip(chip) {
  if (!chip || chip.getAttribute("data-kind") !== "reroll") return;
  var jid = chip.getAttribute("data-job-id");
  var status = chip.getAttribute("data-status");
  if (!jid || !status) return;
  var key = jid + ":" + status;
  if (_appliedReroll[key]) return;
  var page = document.getElementById("song-page");
  var songId = page && page.getAttribute("data-song-id");
  var chipSong = chip.getAttribute("data-song-id");
  if (songId && chipSong && String(songId) !== String(chipSong)) return;
  var tier = chip.getAttribute("data-tier");
  var clips = (chip.getAttribute("data-clips") || "").split(",").filter(Boolean);
  if (status === "queued" || status === "running") {
    var n = parseInt(chip.getAttribute("data-n"), 10) || 4;
    clips.forEach(function (ci) {
      var scene = sceneElForClip(tier, ci);
      var form = scene && scene.querySelector(".reroll-bar");
      if (form) paintRerollPlaceholders(form, {job_id: jid, n: n});
    });
    return;
  }
  if (status === "failed" || status === "cancelled") {
    _appliedReroll[key] = true;
    clearRerollPlaceholders(jid);
    return;
  }
  if (status !== "done") return;
  var any = false;
  clips.forEach(function (ci) {
    var scene = sceneElForClip(tier, ci);
    if (!scene) return;
    any = true;
    refreshSceneEl(scene, songId || chipSong, tier, jid);
  });
  if (any) _appliedReroll[key] = true;
}

function sceneElForSceneNum(tier, sceneNum) {
  if (sceneNum == null || sceneNum === "") return null;
  var inputs = document.querySelectorAll(".clip-bar input[name=scene]");
  for (var i = 0; i < inputs.length; i++) {
    if (String(inputs[i].value) !== String(sceneNum)) continue;
    var form = inputs[i].closest(".clip-bar");
    if (tier) {
      var t = form && form.querySelector("[name=tier]");
      if (t && t.value && t.value !== tier) continue;
    }
    return inputs[i].closest(".scene");
  }
  return null;
}

function applyClipsChip(chip) {
  sweepPendingClipCards();
  if (!chip || chip.getAttribute("data-kind") !== "clips") return;
  var jid = chip.getAttribute("data-job-id");
  var status = chip.getAttribute("data-status");
  if (!jid || !status) return;
  var key = "clips:" + jid + ":" + status;
  if (_appliedReroll[key]) return;
  var page = document.getElementById("song-page");
  var songId = (page && page.getAttribute("data-song-id")) || chip.getAttribute("data-song-id");
  var chipSong = chip.getAttribute("data-song-id");
  if (songId && chipSong && String(songId) !== String(chipSong)) return;
  var tier = chip.getAttribute("data-tier");
  var scene = sceneElForSceneNum(tier, chip.getAttribute("data-scene"));
  var form = scene && scene.querySelector(".clip-bar");
  var n = parseInt(chip.getAttribute("data-n"), 10) || 1;
  if (status === "queued" || status === "running") {
    if (form) paintClipPlaceholders(form, {job_id: jid, n: n});
    return;
  }
  if (status === "failed" || status === "cancelled") {
    _appliedReroll[key] = true;
    clearClipPlaceholders(jid);
    return;
  }
  if (status !== "done") return;
  if (scene) {
    refreshSceneEl(scene, songId || chipSong, tier, jid);
    _appliedReroll[key] = true;
  }
}

// Coverage roster tab. Reload used to pick the tier with the most rows (G
// with 97 beats XXX with 26), so an upload from XXX landed back on G.
function coverageAlbumName() {
  var q = new URLSearchParams(location.search);
  return q.get("scope_value") || q.get("album") ||
    ((document.querySelector("#anchor-form [name=album]") || {}).value) || "";
}
function rememberRosterTier(tier) {
  var album = coverageAlbumName();
  if (album && tier) {
    try { sessionStorage.setItem("meowp-roster-tier:" + album, tier); } catch (err) {}
  }
}
function restoreRosterTier() {
  var tabs = document.querySelector('.tier-tabs[data-album="coverage"]');
  if (!tabs) return;
  var q = new URLSearchParams(location.search).get("roster_tier");
  var album = coverageAlbumName();
  var want = q;
  if (!want && album) {
    try { want = sessionStorage.getItem("meowp-roster-tier:" + album) || ""; } catch (err) {}
  }
  if (!want) return;
  var tab = tabs.querySelector('.tier-tab[data-tier="' + want + '"]');
  if (tab && !tab.classList.contains("active")) tab.click();
}

function paintUploadedPose(form, d) {
  var row = form.closest(".pose-roster-row");
  if (!row) return;
  row.classList.remove("missing");
  row.classList.add("have");
  var src = d.media_url || "";
  var ph = row.querySelector(".pose-ph");
  if (ph && src) {
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "pose-roster-open";
    btn.setAttribute("data-full", src);
    btn.setAttribute("data-label", d.label || "");
    btn.title = "Preview this sheet";
    btn.innerHTML = '<img class="lazy-src" alt="" decoding="async">';
    btn.querySelector("img").setAttribute("src", src);
    ph.replaceWith(btn);
  }
  var sel = row.querySelector("select[name=sheet_id]");
  if (sel && d.id) {
    var opt = document.createElement("option");
    opt.value = String(d.id);
    opt.textContent = (d.label || "uploaded") + " · in use";
    opt.selected = true;
    sel.appendChild(opt);
  }
  var brief = row.querySelector(".js-pose-brief");
  if (brief) brief.remove();
  var ta = row.querySelector(".pose-brief-text");
  if (ta) ta.remove();
  form.remove();
}

document.addEventListener("submit", function (e) {
  var form = e.target.closest && e.target.closest(".pose-upload");
  if (!form) return;
  if (form.getAttribute("hx-post")) return;
  e.preventDefault();
  var file = form.querySelector('input[type="file"]');
  if (!file || !file.files || !file.files.length) return;
  var tier = (form.querySelector('[name="tier"]') || {}).value || "";
  api(form.action, new FormData(form)).then(function (d) {
    rememberRosterTier(d.tier || tier);
    paintUploadedPose(form, d);
  }).catch(function (err) {
    var row = form.closest(".pose-roster-row");
    var note = row && row.querySelector(".pose-roster-copy .muted");
    if (note) note.textContent = "not uploaded: " + err.message;
  });
});

restoreRosterTier();

// T4-21 / T4-23: seed classification_json from the anchors page (no GPU).
function initClassificationLibrary() {
  var box = document.getElementById("classification-library");
  if (!box) return;
  var album = box.getAttribute("data-album") || "";
  var songId = box.getAttribute("data-song-id") || "";
  var tier = box.getAttribute("data-tier") || "";
  var note = document.getElementById("classification-note");
  function say(msg) { if (note) note.textContent = msg || ""; }

  var fromSheets = document.getElementById("classification-from-sheets");
  if (fromSheets) {
    fromSheets.addEventListener("click", function () {
      say("Tagging chosen sheets…");
      api("/api/albums/" + encodeURIComponent(album) + "/classification/from-sheets", {})
        .then(function () { location.reload(); })
        .catch(function (err) { say(err.message); });
    });
  }

  var dlg = document.getElementById("hole-pick");
  var grid = document.getElementById("hole-pick-grid");
  var empty = document.getElementById("hole-pick-empty");
  var useBtn = document.getElementById("hole-pick-use");
  var genBtn = document.getElementById("hole-pick-gen");
  var hole = null;
  var ward = "clothed";
  var picked = null;

  function paintToggles() {
    box.querySelectorAll("#hole-pick-ward .toggle").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute("data-ward") === ward);
    });
  }

  function loadSheets() {
    if (!grid) return;
    grid.innerHTML = "";
    picked = null;
    if (useBtn) useBtn.disabled = true;
    api("/api/albums/" + encodeURIComponent(album) + "/sheets?family=" + encodeURIComponent(ward))
      .then(function (data) {
        var sheets = (data && data.sheets) || [];
        if (empty) empty.hidden = sheets.length > 0;
        sheets.forEach(function (s) {
          var btn = document.createElement("button");
          btn.type = "button";
          btn.className = "hole-pick-cell";
          btn.setAttribute("data-id", String(s.id));
          btn.setAttribute("data-path", s.path || "");
          btn.title = (s.pose || s.label || "") + " · " + (s.view || "");
          var img = document.createElement("img");
          img.src = (s.url || "") + (s.url && s.url.indexOf("?") >= 0 ? "&" : "?") + "w=360";
          img.alt = s.label || "";
          img.decoding = "async";
          var cap = document.createElement("span");
          var who = (s.actors && s.actors.length) ? s.actors.join(" · ") : "";
          cap.textContent = (s.pose || s.label || s.view || "") + (who ? " · " + who : "");
          btn.appendChild(img);
          btn.appendChild(cap);
          grid.appendChild(btn);
        });
      })
      .catch(function (err) { say(err.message); });
  }

  function openHole(btn) {
    hole = {
      pose: btn.getAttribute("data-pose") || "",
      view: btn.getAttribute("data-view") || "front",
      wardrobe: btn.getAttribute("data-wardrobe") || "clothed",
      scenes: btn.getAttribute("data-scenes") || "",
      tier: btn.getAttribute("data-tier") || tier,
    };
    ward = hole.wardrobe === "nude" ? "nude" : "clothed";
    if (hole.tier) tier = hole.tier;
    var title = document.getElementById("hole-pick-title");
    var meta = document.getElementById("hole-pick-meta");
    var poseLab = hole.pose === "unspecified" ? "no pose named" : hole.pose;
    if (title) title.textContent = (tier || "sheet") + " · " + poseLab + " · " + hole.view;
    if (meta) {
      meta.textContent = "Generate or tag a " + (tier || "") + " " + ward +
        " sheet. Scenes " + (hole.scenes || "?") +
        ". Switch Nude if that is what you have, then Generate clothed.";
    }
    paintToggles();
    loadSheets();
    if (dlg && typeof dlg.showModal === "function") dlg.showModal();
  }

  box.addEventListener("click", function (e) {
    var chip = e.target.closest && e.target.closest(".js-hole-pick");
    if (chip) {
      e.preventDefault();
      openHole(chip);
      return;
    }
    var tog = e.target.closest && e.target.closest("#hole-pick-ward .toggle");
    if (tog) {
      ward = tog.getAttribute("data-ward") || "clothed";
      paintToggles();
      loadSheets();
      return;
    }
    var cell = e.target.closest && e.target.closest(".hole-pick-cell");
    if (cell && grid && grid.contains(cell)) {
      grid.querySelectorAll(".hole-pick-cell").forEach(function (c) {
        c.classList.toggle("on", c === cell);
      });
      picked = {id: cell.getAttribute("data-id"), path: cell.getAttribute("data-path")};
      if (useBtn) useBtn.disabled = !picked.path;
    }
  });

  if (useBtn) {
    useBtn.addEventListener("click", function () {
      if (!hole || !picked || !picked.path) return;
      say("Tagging sheet…");
      api("/api/albums/" + encodeURIComponent(album) + "/classification/keeper", {
        id: "anchor-" + (picked.id || ""),
        path: picked.path,
        kind: "operator",
        view: hole.view,
        pose: hole.pose,
        wardrobe: ward,
        usable: "pose",
      }).then(function () { location.reload(); })
        .catch(function (err) { say(err.message); });
    });
  }

  function sheetViewKey(view, wardrobe) {
    var map = {
      front: "front", back: "back", side: "profile",
      "3qtr": "three_quarter", "3qtr-rear": "back",
      profile: "profile", three_quarter: "three_quarter"
    };
    var base = map[view] || view || "front";
    if (wardrobe === "nude") {
      return /nude/.test(base) ? base : base + "_nude";
    }
    return String(base).replace(/_nude$/, "");
  }

  if (genBtn) {
    genBtn.addEventListener("click", function () {
      if (!hole) return;
      var form = document.getElementById("anchor-form");
      var meta = document.getElementById("hole-pick-meta");
      if (!form) {
        if (meta) meta.textContent = "Generate form is not on this page.";
        return;
      }
      var wantTier = hole.tier || tier || "xxx";
      var wantView = sheetViewKey(hole.view, ward);
      var tierBox = form.querySelector('input[name="tier"][value="' + wantTier + '"]');
      var viewBox = form.querySelector('input[name="view"][value="' + wantView + '"]');
      if (!tierBox || !viewBox) {
        if (meta) {
          meta.textContent = "No " + wantTier + " / " + wantView +
            " on the generate form. Tick that cell by hand.";
        }
        return;
      }
      form.querySelectorAll('input[name="tier"]').forEach(function (el) {
        el.removeAttribute("hx-trigger");
        el.checked = el === tierBox;
      });
      form.querySelectorAll('input[name="view"]').forEach(function (el) {
        el.removeAttribute("hx-trigger");
        el.checked = el === viewBox;
      });
      if (!form.querySelector('input[name="ref_id"]:checked')) {
        var firstRef = form.querySelector('input[name="ref_id"]');
        if (firstRef) firstRef.checked = true;
      }
      var sec = document.getElementById("generate-pose");
      var fold = sec && sec.querySelector("details");
      if (fold) fold.open = true;
      if (dlg && dlg.open) dlg.close();
      form.scrollIntoView({behavior: "smooth", block: "start"});
      if (typeof form.requestSubmit === "function") {
        form.requestSubmit(document.getElementById("anchor-generate"));
      } else {
        form.submit();
      }
    });
  }
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
    box.querySelector(".lightbox-pos").textContent = (at.idx + 1) + "/" + all.length;
    var prev = box.querySelector(".media-nav-prev");
    var next = box.querySelector(".media-nav-next");
    if (prev) prev.disabled = all.length < 2;
    if (next) next.disabled = all.length < 2;
    fillLightboxPose(card);
    var actorsBtn = box.querySelector(".lightbox-actors");
    if (actorsBtn) actorsBtn.hidden = !(card.dataset.anchor);
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
    if (box && box.open && (e.target === box || e.target.closest(".modal-close, .lightbox-close"))) box.close();
  });

  document.addEventListener("keydown", function (e) {
    // opening from the grid, for keyboard users who never touch the mouse
    var thumb = e.target.closest && e.target.closest(THUMB_SEL);
    if (thumb && (e.key === "Enter" || e.key === " ")) {
      e.preventDefault(); show(thumb.closest(ITEM_SEL)); return;
    }
    if (!box || !box.open || !current) return;
    // arrows / Delete belong to the pose select while it is focused
    if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === "ArrowRight") { e.preventDefault(); step(0, 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); step(0, -1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); step(1, 0); }
    else if (e.key === "ArrowUp") { e.preventDefault(); step(-1, 0); }
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); removeShown(); }
    // Esc is <dialog>'s own; nothing to add
  });

  box && box.querySelector(".lightbox-delete").addEventListener("click", removeShown);
  box && box.querySelector(".media-nav-prev") &&
    box.querySelector(".media-nav-prev").addEventListener("click", function () { step(0, -1); });
  box && box.querySelector(".media-nav-next") &&
    box.querySelector(".media-nav-next").addEventListener("click", function () { step(0, 1); });
  box && box.querySelector(".lightbox-actors") &&
    box.querySelector(".lightbox-actors").addEventListener("click", function () {
      var card = current;
      var dlg = document.getElementById("actor-tag");
      var form = document.getElementById("actor-tag-form");
      if (!card || !card.dataset.anchor || !dlg || !form) return;
      form.setAttribute("action", "/anchors/" + card.dataset.anchor + "/actors");
      form.querySelector('[name="sheet_id"]').value = card.dataset.anchor;
      var have = (card.dataset.actors || "").split("|").filter(Boolean);
      var want = {};
      have.forEach(function (n) { want[n.toLowerCase()] = true; });
      Array.prototype.forEach.call(form.querySelectorAll('[name="actor_name"]'), function (cb) {
        cb.checked = !!want[(cb.value || "").toLowerCase()];
      });
      if (!dlg.open) dlg.showModal();
    });
  var actorForm = document.getElementById("actor-tag-form");
  actorForm && actorForm.addEventListener("submit", function (e) {
    e.preventDefault();
    var form = e.target;
    var card = current;
    var dlg = document.getElementById("actor-tag");
    if (!card || !card.dataset.anchor) return;
    api(form.action, new FormData(form)).then(function (d) {
      card.dataset.actors = (d.actors || []).join("|");
      if (dlg && dlg.open) dlg.close();
    }).catch(function (err) {
      if (box) box.querySelector(".lightbox-pos").textContent = "not tagged: " + err.message;
      if (dlg && dlg.open) dlg.close();
    });
  });

  function fillLightboxPose(card) {
    var form = box && box.querySelector(".lightbox-pose-form");
    if (!form) return;
    var isSheet = card.classList.contains("candidate") && card.dataset.anchor;
    var sel = form.querySelector("select");
    var hasPoses = sel && sel.querySelector("option[data-tier]");
    form.hidden = !isSheet || !hasPoses;
    if (form.hidden || !sel) return;
    var album = card.dataset.album || "";
    var tier = card.dataset.tier || "";
    var who = card.dataset.who || "";
    form.querySelector('[name="album"]').value = album;
    form.querySelector('[name="tier"]').value = tier;
    form.querySelector('[name="sheet_id"]').value = card.dataset.anchor;
    var sheetId = String(card.dataset.anchor || "");
    var title = (box.querySelector(".lightbox-title").textContent || "").trim().toLowerCase();
    var match = "";
    Array.prototype.forEach.call(sel.options, function (o) {
      if (!o.value) return;
      var hide = (tier && o.getAttribute("data-tier") !== tier)
        || (who && o.getAttribute("data-who") && o.getAttribute("data-who") !== who);
      o.hidden = hide;
      if (hide) return;
      if (o.getAttribute("data-sheet") === sheetId) match = o.value;
    });
    if (!match && title) {
      Array.prototype.forEach.call(sel.options, function (o) {
        if (match || o.hidden || !o.value) return;
        var label = (o.getAttribute("data-label") || o.textContent || "").toLowerCase();
        if (label.indexOf(title) !== -1 || title.indexOf(label) !== -1) match = o.value;
      });
    }
    sel.value = match;
  }

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
        var sec = card.closest("section.anchor-group") || card.closest("section.card");
        card.remove();
        if (next) { show(next); }
        else { box.close(); }
        dropEmptyGroup(sec);
        if (sec && sec.parentNode) refreshGroup(sec);
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
  function sectionOf(el) {
    return el.closest("section.anchor-group") || el.closest("[data-group]")
      || el.closest("section.card");
  }
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

  function dropEmptyGroup(sec) {
    if (!sec || sec.querySelectorAll(".candidate").length) return;
    var head = sec.previousElementSibling;
    sec.remove();
    if (head && head.classList && head.classList.contains("anchor-row-head")) {
      var nxt = head.nextElementSibling;
      if (!nxt || !nxt.classList.contains("anchor-group")) head.remove();
    }
  }
  function removeCards(sec, ids) {
    ids.forEach(function (id) {
      var card = sec.querySelector('.candidate[data-anchor="' + id + '"]');
      if (card) card.remove();
    });
    dropEmptyGroup(sec);
    if (sec && sec.parentNode) refreshGroup(sec);
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

    if ((form = e.target.closest(".lightbox-pose-form"))) {
      e.preventDefault();
      var key = form.querySelector('[name="key"]').value;
      if (!key) {
        box.querySelector(".lightbox-pos").textContent = "pick a pose first";
        return;
      }
      var btn = form.querySelector("button[type=submit]");
      if (btn) btn.disabled = true;
      api(form.action, new FormData(form)).then(function (d) {
        var card = current;
        if (card && d.group) {
          var sec = sectionOf(card);
          d.group.forEach(function (p) {
            var c = sec && sec.querySelector('.candidate[data-anchor="' + p.id + '"]');
            if (c) c.classList.toggle("picked", p.chosen);
          });
        }
        var want = d.key || key;
        var opt = null;
        Array.prototype.forEach.call(form.querySelectorAll("option"), function (o) {
          if (o.value === want) opt = o;
        });
        if (opt) {
          opt.setAttribute("data-sheet", String(d.sheet_id || (card && card.dataset.anchor) || ""));
          if (d.label) opt.setAttribute("data-label", d.label);
        }
        if (d.label && box.querySelector(".lightbox-title")) {
          box.querySelector(".lightbox-title").textContent = d.label;
        }
        if (card) fillLightboxPose(card);
        var at = card && where(card);
        if (at) {
          var all = cardsIn(at.row);
          box.querySelector(".lightbox-pos").textContent = (at.idx + 1) + "/" + all.length;
        }
      }).catch(function (err) {
        box.querySelector(".lightbox-pos").textContent = "not classified: " + err.message;
      }).then(function () { if (btn) btn.disabled = false; });
      return;
    }
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
  var all = document.querySelector(".pick-all");
  var count = document.getElementById("bulk-count");
  var note = document.getElementById("bulk-note");
  var val = function (id) { var e = document.getElementById(id); return e ? e.value : ""; };

  // rows currently SHOWN. An accordion hides the other albums; either way
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
    document.querySelectorAll(".pick-all").forEach(function (box) {
      box.checked = vis.length > 0 && n === vis.length;
      box.indeterminate = n > 0 && n < vis.length;
      box.title = "Select all " + vis.length + " shown";
    });
    if (!n) {
      bar.hidden = true;
      if (count) { count.hidden = true; count.textContent = ""; }
      return;
    }
    bar.hidden = false;
    if (count) count.hidden = false;
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

  if (all) all.addEventListener("change", function () {
    shown().forEach(function (r) { r.querySelector(".pick-song").checked = all.checked; });
    refresh();
  });
  document.addEventListener("change", function (e) {
    if (!e.target.classList || !e.target.classList.contains("pick-all")) return;
    if (e.target === all) return;
    var on = e.target.checked;
    shown().forEach(function (r) { r.querySelector(".pick-song").checked = on; });
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
    var cell = row.querySelector(".genre-text");
    if (!cell) return;
    cell.textContent = "";
    [g.genre, g.subgenre, g.genre2, g.subgenre2].forEach(function (name) {
      if (!name) return;
      var tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = name;
      cell.appendChild(tag);
    });
  }

  function albumSection(album) {
    var root = document.getElementById("library-albums");
    if (!root) return null;
    return root.querySelector(
      '.library-album[data-album="' + String(album || "").replace(/"/g, '\\"') + '"]');
  }

  function fillUploadGenres(album) {
    var head = albumSection(album);
    if (!head) return;
    setSel("genre-select", head.getAttribute("data-genre"));
    setSel("subgenre-select", head.getAttribute("data-subgenre"));
    setSel("genre2-select", head.getAttribute("data-genre2"));
    setSel("subgenre2-select", head.getAttribute("data-subgenre2"));
  }

  var albumIn = document.getElementById("upload-album");
  if (albumIn) {
    albumIn.addEventListener("change", function () {
      fillUploadGenres((albumIn.value || "").trim());
    });
    albumIn.addEventListener("input", function () {
      fillUploadGenres((albumIn.value || "").trim());
    });
  }

  function setGroupOpen(head, open) {
    if (!head) return;
    if (open) {
      document.querySelectorAll(".library-album.open").forEach(function (sec) {
        if (sec !== head) setGroupOpen(sec, false);
      });
    }
    head.classList.toggle("open", !!open);
    var btn = head.querySelector(".album-fold");
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    var body = head.querySelector(".library-album-body");
    if (body) body.hidden = !open;
    if (typeof refresh === "function") refresh();
  }

  document.addEventListener("click", function (e) {
    var fold = e.target.closest && e.target.closest("button.album-fold");
    if (!fold) return;
    var head = fold.closest(".library-album");
    var open = fold.getAttribute("aria-expanded") !== "true";
    setGroupOpen(head, open);
  });

  function ensureAlbumGroup(root, album, genres) {
    var head = albumSection(album);
    if (head) return head;
    var listRoot = root || document.getElementById("library-albums");
    if (!listRoot) return null;
    var sec = document.createElement("section");
    sec.className = "library-album";
    sec.setAttribute("data-album", album);
    sec.setAttribute("data-genre", (genres && genres.genre) || "");
    sec.setAttribute("data-subgenre", (genres && genres.subgenre) || "");
    sec.setAttribute("data-genre2", (genres && genres.genre2) || "");
    sec.setAttribute("data-subgenre2", (genres && genres.subgenre2) || "");
    sec.innerHTML =
      '<div class="album-group-head">' +
        '<button type="button" class="album-fold" aria-expanded="false">' +
          (album || "No album") + ' <span class="muted">(0)</span></button>' +
      '</div>' +
      '<div class="library-album-body library-scroll table-scroll" hidden>' +
        '<table class="list"><thead><tr>' +
          '<th class="pick"><input type="checkbox" class="pick-all" title="Select all shown"></th>' +
          '<th>Title</th><th>Genre</th><th class="num">Length</th>' +
          '<th class="num">BPM</th><th>Key</th><th class="num">Energy</th>' +
          '<th>Video</th><th>Sets</th><th></th>' +
        '</tr></thead><tbody></tbody></table></div>';
    listRoot.insertBefore(sec, listRoot.firstChild);
    var list = document.getElementById("album-names");
    if (list && album) {
      var opt = document.createElement("option");
      opt.value = album;
      list.appendChild(opt);
    }
    return sec;
  }

  function recountGroup(head) {
    if (!head) return;
    var n = head.querySelectorAll("tr[data-song]").length;
    var muted = head.querySelector(".album-fold .muted");
    if (muted) muted.textContent = "(" + n + ")";
    if (!n) head.remove();
  }

  var genreDlg = document.getElementById("genre-set");
  var genreSong = null;
  function genreNote(msg) {
    var n = document.getElementById("genre-set-note");
    if (n) n.textContent = msg || "";
  }
  function setSel(id, value) {
    var el = document.getElementById(id);
    if (!el) return;
    el.value = value || "";
    el.dispatchEvent(new Event("change"));
  }
  var genreAlbum = null;
  document.addEventListener("click", function (e) {
    var albumBtn = e.target.closest && e.target.closest(".js-album-genre-set");
    if (albumBtn && genreDlg) {
      var head = albumBtn.closest(".library-album");
      if (!head) return;
      genreAlbum = head.getAttribute("data-album") || "";
      genreSong = null;
      var title = document.getElementById("genre-set-title");
      if (title) title.textContent = "Set album genre — " + genreAlbum;
      setSel("set-genre-select", head.getAttribute("data-genre"));
      setSel("set-subgenre-select", head.getAttribute("data-subgenre"));
      setSel("set-genre2-select", head.getAttribute("data-genre2"));
      setSel("set-subgenre2-select", head.getAttribute("data-subgenre2"));
      genreNote("Saves as the album default and copies to every song on " + genreAlbum + ".");
      if (typeof genreDlg.showModal === "function") genreDlg.showModal();
      return;
    }
    var btn = e.target.closest && e.target.closest(".js-genre-set");
    if (!btn || !genreDlg) return;
    var row = btn.closest("tr[data-song]");
    if (!row) return;
    genreAlbum = null;
    genreSong = row.getAttribute("data-song");
    var title = document.getElementById("genre-set-title");
    var name = row.querySelector("a");
    if (title) title.textContent = "Set genre" + (name ? " — " + name.textContent : "");
    setSel("set-genre-select", row.getAttribute("data-genre"));
    setSel("set-subgenre-select", row.getAttribute("data-subgenre"));
    setSel("set-genre2-select", row.getAttribute("data-genre2"));
    setSel("set-subgenre2-select", row.getAttribute("data-subgenre2"));
    genreNote("");
    if (typeof genreDlg.showModal === "function") genreDlg.showModal();
  });
  var ask = document.getElementById("genre-set-suggest");
  if (ask) ask.addEventListener("click", function () {
    if (!genreSong) return;
    genreNote("asking…");
    post("/songs/genres/suggest", {song_ids: [Number(genreSong)]})
      .then(function (d) {
        var s = (d.suggestions || [])[0];
        if (!s) {
          genreNote((d.dropped && d.dropped[0] && d.dropped[0].why) || "no suggestion");
          return;
        }
        setSel("set-genre-select", s.genre);
        setSel("set-subgenre-select", s.subgenre);
        setSel("set-genre2-select", s.genre2);
        setSel("set-subgenre2-select", s.subgenre2);
        genreNote("Suggested from: " + (s.evidence || d.model || "AI") + " — Save to keep.");
      })
      .catch(function (err) { genreNote(err.message); });
  });
  function stampGenre(row, u) {
    if (!row || !u) return;
    paintGenre(row, u);
    row.setAttribute("data-genre", u.genre || "");
    row.setAttribute("data-subgenre", u.subgenre || "");
    row.setAttribute("data-genre2", u.genre2 || "");
    row.setAttribute("data-subgenre2", u.subgenre2 || "");
  }
  var keep = document.getElementById("genre-set-save");
  if (keep) keep.addEventListener("click", function () {
    if (genreAlbum) {
      genreNote("saving album defaults…");
      post("/albums/genres", {
        album: genreAlbum,
        genre: val("set-genre-select"),
        subgenre: val("set-subgenre-select"),
        genre2: val("set-genre2-select"),
        subgenre2: val("set-subgenre2-select")
      }).then(function (d) {
        var head = albumSection(genreAlbum);
        if (head && d.defaults) {
          head.setAttribute("data-genre", d.defaults.genre || "");
          head.setAttribute("data-subgenre", d.defaults.subgenre || "");
          head.setAttribute("data-genre2", d.defaults.genre2 || "");
          head.setAttribute("data-subgenre2", d.defaults.subgenre2 || "");
        }
        (d.updated || []).forEach(function (u) {
          stampGenre(document.querySelector('tr[data-song="' + u.song_id + '"]'), u);
        });
        if (genreDlg && typeof genreDlg.close === "function") genreDlg.close();
      }).catch(function (err) { genreNote(err.message); });
      return;
    }
    if (!genreSong) return;
    genreNote("saving…");
    post("/songs/genres", {song_ids: [Number(genreSong)],
                            genre: val("set-genre-select"),
                            subgenre: val("set-subgenre-select"),
                            genre2: val("set-genre2-select"),
                            subgenre2: val("set-subgenre2-select")})
      .then(function (d) {
        stampGenre(document.querySelector('tr[data-song="' + genreSong + '"]'),
                   (d.updated || [])[0]);
        if (genreDlg && typeof genreDlg.close === "function") genreDlg.close();
      })
      .catch(function (err) { genreNote(err.message); });
  });
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
            var listRoot = document.getElementById("library-albums");
            var wrap = document.createElement("tbody");
            wrap.innerHTML = html.trim();
            var row = wrap.querySelector("tr[data-song]");
            if (listRoot && row) {
              var album = row.getAttribute("data-album") || "";
              var genres = {
                genre: row.getAttribute("data-genre") || "",
                subgenre: row.getAttribute("data-subgenre") || "",
                genre2: row.getAttribute("data-genre2") || "",
                subgenre2: row.getAttribute("data-subgenre2") || ""
              };
              var head = ensureAlbumGroup(listRoot, album, genres);
              var body = head && head.querySelector("tbody");
              if (body) {
                row.classList.remove("hidden");
                body.insertBefore(row, body.firstChild);
                setGroupOpen(head, true);
                recountGroup(head);
              }
            }
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
      .then(function () {
        var head = row.closest(".library-album");
        row.remove();
        recountGroup(head);
        refresh();
        busy(false, "Deleted.");
      })
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
  function refineGenres(ids, done) {
    if (!ids || !ids.length) return done("");
    post("/songs/genres/suggest", {song_ids: ids})
      .then(function (d) {
        var sug = d.suggestions || [];
        var writes = sug.map(function (s) {
          return post("/songs/genres", {
            song_ids: [s.song_id],
            genre: s.genre, subgenre: s.subgenre,
            genre2: s.genre2, subgenre2: s.subgenre2
          }).then(function (w) {
            stampGenre(document.querySelector('tr[data-song="' + s.song_id + '"]'),
                       (w.updated || [])[0] || s);
          });
        });
        return Promise.all(writes).then(function () {
          var msg = sug.length + " genre" + (sug.length === 1 ? "" : "s") + " refined";
          if (d.dropped && d.dropped.length) msg += ", " + d.dropped.length + " skipped";
          done(msg);
        });
      })
      .catch(function (err) { done("genre refine failed: " + err.message); });
  }

  var form = document.getElementById("analyse-all");
  if (form) form.addEventListener("submit", function (e) {
    e.preventDefault();
    busy(true, "queueing…");
    api("/songs/analyse-all", {})
      .then(function (d) {
        var want = (d.queued || []).map(function (q) { return q.song_id; });
        var genreIds = d.genre_ids || Array.prototype.map.call(
          document.querySelectorAll("tr[data-song]"),
          function (r) { return Number(r.getAttribute("data-song")); });
        var gmsg = "";
        var bpmDone = !want.length;
        function finish() {
          if (!bpmDone) return;
          var bits = [];
          if (want.length) bits.push("Analysed " + want.length + ".");
          else bits.push("Nothing to analyse — every song already has a bpm.");
          if (gmsg) bits.push(gmsg);
          busy(false, bits.join(" "));
        }
        refineGenres(genreIds, function (msg) { gmsg = msg; finish(); });
        if (!want.length) return;
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
              busy(true, (want.length - left.length) + " of " + want.length + " analysed…");
              if (!left.length) {
                clearInterval(tick);
                bpmDone = true;
                finish();
              }
            })
            .catch(function () {
              clearInterval(tick);
              bpmDone = true;
              busy(false, "Stopped watching; reload to see results.");
            });
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

(function () {
  var dlg = document.getElementById("jobs-modal");
  if (!dlg) return;
  function openJobs() {
    var body = document.getElementById("jobs-modal-body");
    if (body && typeof htmx !== "undefined") {
      htmx.ajax("GET", "/queue", {target: "#jobs-modal-body", swap: "innerHTML"});
    }
    if (typeof dlg.showModal === "function") dlg.showModal();
  }
  document.addEventListener("click", function (e) {
    if (!e.target.closest("[data-open-jobs]")) return;
    e.preventDefault();
    if (dlg.open) dlg.close();
    else openJobs();
  });
  dlg.addEventListener("click", function (e) {
    var r = dlg.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right ||
        e.clientY < r.top || e.clientY > r.bottom) {
      dlg.close();
    }
  });
})();

(function () {
  var overlay = document.getElementById("page-loading");
  var label = document.getElementById("page-loading-label");
  if (!overlay) return;
  document.querySelectorAll("header nav a, header a.brand").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button) return;
      var href = a.getAttribute("href") || "";
      if (!href || href.charAt(0) === "#") return;
      if (label) {
        label.textContent = href.indexOf("/playlists") === 0
          ? "Loading playlists…" : "Loading…";
      }
      overlay.hidden = false;
    });
  });
  window.addEventListener("pageshow", function () { overlay.hidden = true; });
  document.querySelectorAll("dialog.video-modal").forEach(function (d) {
    d.addEventListener("close", function () {
      d.querySelectorAll("video, audio").forEach(function (v) {
        v.pause();
        v.removeAttribute("src");
        if (typeof v.load === "function") v.load();
      });
    });
  });
})();

document.addEventListener("click", function (e) {
  var play = e.target.closest("a.js-media-play");
  if (!play) return;
  var dlg = document.getElementById("media-player");
  if (!dlg || typeof dlg.showModal !== "function") return;
  e.preventDefault();
  var src = play.getAttribute("href") || "";
  var kind = play.getAttribute("data-kind") || "video";
  var lab = document.getElementById("media-player-label");
  if (lab) lab.textContent = play.getAttribute("data-label") || play.textContent.trim() || "Play";
  var dl = document.getElementById("media-player-download");
  if (dl) dl.setAttribute("href", src);
  var vid = document.getElementById("media-player-video");
  var aud = document.getElementById("media-player-audio");
  function mute(el) {
    if (!el) return;
    el.pause();
    el.removeAttribute("src");
    if (typeof el.load === "function") el.load();
    el.hidden = true;
  }
  if (kind === "audio") {
    mute(vid);
    if (aud) {
      aud.hidden = false;
      aud.src = src;
      var p = aud.play();
      if (p && typeof p.catch === "function") p.catch(function () {});
    }
  } else {
    mute(aud);
    if (vid) {
      vid.hidden = false;
      vid.src = src;
      var q = vid.play();
      if (q && typeof q.catch === "function") q.catch(function () {});
    }
  }
  dlg.showModal();
});

(function () {
  var dlg = document.getElementById("pose-preview");
  if (!dlg) return;
  var items = [];
  var idx = 0;

  function thumbs() {
    return Array.prototype.slice.call(document.querySelectorAll(".pose-roster-open[data-full]"));
  }
  function show(i) {
    if (!items.length) return;
    idx = (i + items.length) % items.length;
    var el = items[idx];
    var img = dlg.querySelector("img");
    if (img) img.src = el.getAttribute("data-full") || "";
    var lab = document.getElementById("pose-preview-label");
    if (lab) lab.textContent = el.getAttribute("data-label") || "";
    var prev = dlg.querySelector(".media-nav-prev");
    var next = dlg.querySelector(".media-nav-next");
    if (prev) prev.disabled = items.length < 2;
    if (next) next.disabled = items.length < 2;
  }
  document.addEventListener("click", function (e) {
    if (e.target.closest("#pose-preview .media-nav-prev")) { e.preventDefault(); show(idx - 1); return; }
    if (e.target.closest("#pose-preview .media-nav-next")) { e.preventDefault(); show(idx + 1); return; }
    var btn = e.target.closest(".pose-roster-open");
    if (!btn) return;
    items = thumbs();
    var at = items.indexOf(btn);
    if (at < 0) { items = [btn]; at = 0; }
    show(at);
    dlg.showModal();
  });
  document.addEventListener("keydown", function (e) {
    if (!dlg.open) return;
    if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); show(idx - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); show(idx + 1); }
  });
})();

(function () {
  var vdlg = document.getElementById("clip-preview");
  if (!vdlg) return;
  var vid = vdlg.querySelector("video");
  var items = [];
  var idx = 0;

  function thumbs(fromEl) {
    var root = (fromEl && fromEl.closest(".scene-clips")) || document;
    var nodes = root.querySelectorAll(".js-clip-preview.thumb-open[data-video]");
    var seen = {};
    var out = [];
    Array.prototype.forEach.call(nodes, function (el) {
      var key = (el.getAttribute("data-clip-idx") || "") + "|" +
                (el.getAttribute("data-video") || "");
      if (seen[key]) return;
      seen[key] = true;
      out.push(el);
    });
    return out.sort(function (a, b) {
      var na = parseInt(a.getAttribute("data-clip-idx") || "0", 10);
      var nb = parseInt(b.getAttribute("data-clip-idx") || "0", 10);
      return na - nb;
    });
  }

  function current() { return items[idx] || null; }

  function motionFor(el) {
    var m = el && el.getAttribute("data-motion");
    if (m) return m;
    var num = el && el.getAttribute("data-scene");
    var scene = (el && el.closest(".scene")) ||
                (num && document.getElementById("scene-" + num));
    var ta = scene && scene.querySelector('textarea[name="video_motion_prompt"]');
    return (ta && ta.value) || "";
  }

  function show(i) {
    if (!items.length) return;
    idx = (i + items.length) % items.length;
    var el = items[idx];
    vid.removeAttribute("src");
    vid.load();
    vid.src = el.getAttribute("data-video") || "";
    vid.play().catch(function () {});
    var lab = document.getElementById("clip-preview-label");
    if (lab) lab.textContent = el.getAttribute("data-label") || "Clip";
    var pos = document.getElementById("clip-preview-pos");
    if (pos) pos.textContent = (idx + 1) + " / " + items.length;
    var prev = vdlg.querySelector(".media-nav-prev");
    var next = vdlg.querySelector(".media-nav-next");
    if (prev) prev.disabled = items.length < 2;
    if (next) next.disabled = items.length < 2;
    var motion = document.getElementById("clip-motion");
    if (motion) motion.value = motionFor(el);
    var wrap = document.getElementById("clip-motion-wrap");
    if (wrap) wrap.hidden = true;
    var stillBtn = document.getElementById("clip-open-still");
    if (stillBtn) stillBtn.disabled = !el.getAttribute("data-still");
  }

  function openFrom(el) {
    items = thumbs(el);
    var at = items.indexOf(el);
    if (at < 0) {
      var src = el.getAttribute("data-video");
      at = -1;
      items.forEach(function (it, i) {
        if (at < 0 && it.getAttribute("data-video") === src) at = i;
      });
    }
    if (at < 0) {
      items = [el];
      at = 0;
    }
    show(at);
    if (typeof vdlg.showModal === "function") vdlg.showModal();
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("#clip-preview .media-nav-prev")) { e.preventDefault(); show(idx - 1); return; }
    if (e.target.closest("#clip-preview .media-nav-next")) { e.preventDefault(); show(idx + 1); return; }
    if (e.target.closest(".js-clip-del") || e.target.closest(".js-clip-fail-dismiss")) return;
    var clip = e.target.closest(".js-clip-preview");
    if (!clip) return;
    if (clip.getAttribute("data-playlist") && !clip.getAttribute("data-video")) {
      var list = (clip.getAttribute("data-playlist") || "").split("|").filter(Boolean);
      if (!list.length) return;
      items = list.map(function (src, n) {
        var fake = document.createElement("button");
        fake.setAttribute("data-video", src);
        fake.setAttribute("data-label", (clip.getAttribute("data-label") || "Clip") + " · part " + (n + 1));
        return fake;
      });
      show(0);
      if (typeof vdlg.showModal === "function") vdlg.showModal();
      return;
    }
    if (clip.getAttribute("data-video")) openFrom(clip);
  });

  document.addEventListener("keydown", function (e) {
    if (!vdlg.open) return;
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); show(idx - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); show(idx + 1); }
  });

  function songId() {
    var page = document.getElementById("song-page");
    return page && page.getAttribute("data-song-id");
  }

  function note(msg, bad) {
    say2(document.getElementById("clip-preview-note"), msg, bad);
  }

  var rerender = document.getElementById("clip-rerender");
  if (rerender) rerender.addEventListener("click", function () {
    var el = current();
    var sid = songId();
    if (!el || !sid) return note("no clip", true);
    var fd = new FormData();
    fd.append("tier", el.getAttribute("data-tier") || "");
    if (el.getAttribute("data-scene")) fd.append("scene", el.getAttribute("data-scene"));
    if (el.getAttribute("data-clip-idx") != null) fd.append("clip_idx", el.getAttribute("data-clip-idx"));
    if (document.getElementById("clip-refine") && document.getElementById("clip-refine").checked) {
      fd.append("refine", "true");
    }
    note("queueing…");
    api("/songs/" + sid + "/clips", fd).then(function (d) {
      note(d.job_id ? ("queued job #" + d.job_id) : "queued");
      if (d.job_id && typeof refreshQueue === "function") refreshQueue();
    }).catch(function (err) { note(err.message, true); });
  });

  var editBtn = document.getElementById("clip-edit-motion");
  if (editBtn) editBtn.addEventListener("click", function () {
    var wrap = document.getElementById("clip-motion-wrap");
    if (wrap) wrap.hidden = !wrap.hidden;
  });

  var saveMotion = document.getElementById("clip-save-motion");
  if (saveMotion) saveMotion.addEventListener("click", function () {
    var el = current();
    var sid = songId();
    var scene = el && el.getAttribute("data-scene");
    var tier = el && el.getAttribute("data-tier");
    if (!el || !sid || !scene || !tier) return note("this clip has no scene prompt", true);
    var fd = new FormData();
    fd.append("video_motion_prompt", document.getElementById("clip-motion").value);
    note("saving…");
    api("/songs/" + sid + "/storyboard/" + tier + "/scene/" + scene, fd).then(function () {
      el.setAttribute("data-motion", document.getElementById("clip-motion").value);
      note("saved — re-render to apply");
    }).catch(function (err) { note(err.message, true); });
  });

  if (vid) {
    vid.addEventListener("error", function () {
      note("this take is gone — deleted or the file is missing. Close and play the current tile.", true);
    });
  }

  var stillBtn = document.getElementById("clip-open-still");
  if (stillBtn) stillBtn.addEventListener("click", function () {
    var el = current();
    var still = el && el.getAttribute("data-still");
    if (!still) return note("no approved still on this clip", true);
    vdlg.close();
    var thumb = document.querySelector('.js-ref-preview[data-full="' + still + '"]');
    if (thumb) {
      document.dispatchEvent(new CustomEvent("meowp:open-ref", {detail: {el: thumb}}));
    } else {
      var dlg = document.getElementById("ref-preview");
      if (!dlg) return;
      dlg.querySelector("img").src = still;
      var lab = document.getElementById("ref-preview-label");
      if (lab) lab.textContent = "approved still — fix or reroll, then re-render the clip";
      if (typeof dlg.showModal === "function") dlg.showModal();
    }
    var scene = el.getAttribute("data-scene");
    var row = scene && document.getElementById("scene-" + scene);
    if (row) row.scrollIntoView({block: "nearest"});
  });

  vdlg.addEventListener("close", function () {
    vid.pause();
  });
})();

(function () {
  var dlg = document.getElementById("ref-preview");
  if (!dlg) return;
  var img = dlg.querySelector("img");
  var items = [];
  var idx = 0;

  function current() { return items[idx] || null; }

  function figureOf(el) {
    return el && el.closest(".ref-frame");
  }

  function note(msg, bad) {
    say2(document.getElementById("ref-preview-note"), msg, bad);
  }

  function thumbsAround(el) {
    var strip = el && el.closest(".scene-refs, .preview-stills");
    if (strip) {
      return Array.prototype.slice.call(strip.querySelectorAll(".js-ref-preview[data-full]"));
    }
    return el ? [el] : [];
  }

  function syncActions() {
    var fig = figureOf(current());
    var can = !!(fig && fig.querySelector(".still-pick"));
    ["ref-approve", "ref-fix", "ref-delete"].forEach(function (id) {
      var b = document.getElementById(id);
      if (b) b.hidden = !can;
    });
    var approve = document.getElementById("ref-approve");
    if (approve && can) {
      approve.textContent = fig.classList.contains("approved") ? "Unapprove" : "Use this still";
    }
    var prev = dlg.querySelector(".media-nav-prev");
    var next = dlg.querySelector(".media-nav-next");
    if (prev) prev.disabled = items.length < 2;
    if (next) next.disabled = items.length < 2;
  }

  function show(i) {
    if (!items.length) return;
    idx = (i + items.length) % items.length;
    var el = items[idx];
    img.src = el.getAttribute("data-full") || "";
    var lab = document.getElementById("ref-preview-label");
    if (lab) lab.textContent = el.getAttribute("data-label") || "";
    var pos = document.getElementById("ref-preview-pos");
    if (pos) pos.textContent = (idx + 1) + " / " + items.length;
    syncActions();
    note("");
  }

  function openFrom(el) {
    if (!el) return;
    items = thumbsAround(el);
    var at = items.indexOf(el);
    if (at < 0) {
      items = [el];
      at = 0;
    }
    show(at);
    if (typeof dlg.showModal === "function") dlg.showModal();
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest("#ref-preview .media-nav-prev")) { e.preventDefault(); show(idx - 1); return; }
    if (e.target.closest("#ref-preview .media-nav-next")) { e.preventDefault(); show(idx + 1); return; }
    var btn = e.target.closest(".js-ref-preview");
    if (btn && btn.getAttribute("data-full")) openFrom(btn);
  });

  document.addEventListener("meowp:open-ref", function (e) {
    if (e.detail && e.detail.el) openFrom(e.detail.el);
  });

  document.addEventListener("keydown", function (e) {
    if (!dlg.open) return;
    var t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
    if (e.key === "ArrowLeft") { e.preventDefault(); show(idx - 1); }
    if (e.key === "ArrowRight") { e.preventDefault(); show(idx + 1); }
  });

  var approve = document.getElementById("ref-approve");
  if (approve) approve.addEventListener("click", function () {
    var fig = figureOf(current());
    var form = fig && fig.querySelector(".still-pick");
    if (!form) return note("this still cannot be approved here", true);
    note("saving…");
    api(form.getAttribute("action"), new FormData(form)).then(function (d) {
      paintStillApprove(fig, !!d.approved);
      syncActions();
      note(d.approved ? "approved" : "unapproved");
    }).catch(function (err) { note(err.message, true); });
  });

  var fix = document.getElementById("ref-fix");
  if (fix) fix.addEventListener("click", function () {
    var fig = figureOf(current());
    var btn = fig && fig.querySelector(".js-ref-fix");
    if (!btn) return note("no fix on this still", true);
    dlg.close();
    btn.click();
  });

  var del = document.getElementById("ref-delete");
  if (del) del.addEventListener("click", function () {
    var fig = figureOf(current());
    var form = fig && fig.querySelector('form[action*="/refs/"][action$="/delete"]');
    if (!form) return note("this still cannot be deleted here", true);
    note("deleting…");
    api(form.getAttribute("action"), new FormData(form)).then(function () {
      items.splice(idx, 1);
      fig.remove();
      if (!items.length) { dlg.close(); return; }
      show(idx);
      note("deleted");
    }).catch(function (err) { note(err.message, true); });
  });
})();

function syncT2iDelete(row) {
  if (!row) return;
  var n = row.querySelectorAll(".js-t2i-select:checked").length;
  var btn = row.querySelector(".js-t2i-delete");
  if (!btn) return;
  btn.hidden = n === 0;
  btn.textContent = n ? ("Delete selected (" + n + ")") : "Delete selected";
}

document.addEventListener("change", function (e) {
  var box = e.target.closest && e.target.closest(".js-t2i-select");
  if (!box) return;
  syncT2iDelete(box.closest(".t2i-row"));
});

document.addEventListener("click", function (e) {
  var btn = e.target.closest && e.target.closest(".js-t2i-delete");
  if (!btn) return;
  var row = btn.closest(".t2i-row");
  if (!row) return;
  var picked = Array.prototype.slice.call(row.querySelectorAll(".js-t2i-select:checked"));
  if (!picked.length) return;
  var ids = picked.map(function (el) { return parseInt(el.value, 10); }).filter(Boolean);
  if (!ids.length) return;
  btn.disabled = true;
  var note = row.querySelector(".save-note");
  api("/media/images/delete", {ids: ids}).then(function () {
    picked.forEach(function (el) {
      var fig = el.closest(".ref-frame");
      if (fig) fig.remove();
    });
    btn.disabled = false;
    syncT2iDelete(row);
    if (!row.querySelector(".js-t2i-select") && note) {
      note.textContent = "deleted";
    }
  }).catch(function (err) {
    btn.disabled = false;
    if (note) note.textContent = err.message;
  });
});

function syncStillsDelete(row) {
  if (!row) return;
  var n = row.querySelectorAll(".js-still-select:checked").length;
  var btn = row.querySelector(".js-stills-delete");
  if (!btn) return;
  btn.hidden = n === 0;
  btn.textContent = n ? ("Delete selected (" + n + ")") : "Delete selected";
}

document.addEventListener("change", function (e) {
  var box = e.target.closest && e.target.closest(".js-still-select");
  if (!box) return;
  syncStillsDelete(box.closest(".stills-row"));
});

document.addEventListener("click", function (e) {
  var btn = e.target.closest && e.target.closest(".js-stills-delete");
  if (!btn) return;
  var row = btn.closest(".stills-row");
  if (!row) return;
  var picked = Array.prototype.slice.call(row.querySelectorAll(".js-still-select:checked"));
  if (!picked.length) return;
  btn.disabled = true;
  var note = row.querySelector(".save-note") || row.querySelector(".stills-head");
  function next() {
    var input = picked.shift();
    if (!input) {
      btn.disabled = false;
      syncStillsDelete(row);
      return;
    }
    var fig = input.closest(".ref-frame");
    var form = fig && fig.querySelector("form.still-del");
    if (!form) return next();
    api(form.getAttribute("action"), new FormData(form)).then(function () {
      if (fig) fig.remove();
      next();
    }).catch(function (err) {
      btn.disabled = false;
      if (note && note.classList.contains("save-note")) say2(note, err.message, true);
    });
  }
  next();
});

document.addEventListener("click", function (e) {
  if (e.target && e.target.id === "pose-brief-copy") {
    var ta = document.getElementById("pose-brief-text");
    if (!ta) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(ta.value);
    } else {
      ta.select();
      document.execCommand("copy");
    }
    e.target.textContent = "Copied";
    setTimeout(function () { e.target.textContent = "Copy prompt"; }, 1500);
    return;
  }
  var beat = e.target.closest && e.target.closest(".song-arc-beat");
  if (beat) {
    var open = !beat.classList.contains("is-open");
    beat.classList.toggle("is-open", open);
    beat.setAttribute("aria-expanded", open ? "true" : "false");
    return;
  }
  var ptab = e.target.closest && e.target.closest(".pose-who-tab");
  if (ptab) {
    var panel = ptab.closest(".tier-panel") || ptab.closest("details") || ptab.parentElement;
    var want = ptab.getAttribute("data-who") || "";
    panel.querySelectorAll(".pose-who-tab").forEach(function (t) {
      t.classList.toggle("active", t === ptab);
    });
    panel.querySelectorAll(".pose-roster-row").forEach(function (row) {
      var parts = (row.getAttribute("data-who") || "").split("+");
      row.classList.toggle("hidden", !!(want && parts.indexOf(want) < 0));
    });
    return;
  }
  var brief = e.target.closest && e.target.closest(".js-pose-brief");
  if (brief) {
    var dlg = document.getElementById("pose-brief");
    if (!dlg || typeof dlg.showModal !== "function") return;
    var title = document.getElementById("pose-brief-title");
    var meta = document.getElementById("pose-brief-meta");
    var ta = document.getElementById("pose-brief-text");
    var src = brief.parentElement && brief.parentElement.querySelector(".pose-brief-text");
    if (title) title.textContent = "Generate: " + (brief.getAttribute("data-label") || "pose");
    if (meta) {
      var bits = [];
      if (brief.getAttribute("data-who")) bits.push(brief.getAttribute("data-who"));
      if (brief.getAttribute("data-album")) bits.push(brief.getAttribute("data-album"));
      if (brief.getAttribute("data-tier")) bits.push(brief.getAttribute("data-tier"));
      if (brief.getAttribute("data-scenes")) {
        bits.push(brief.getAttribute("data-scenes") + " scene(s)");
      }
      if (brief.getAttribute("data-songs")) bits.push(brief.getAttribute("data-songs"));
      meta.textContent = bits.join(" · ");
    }
    var actorsEl = document.getElementById("pose-brief-actors");
    var actorsList = document.getElementById("pose-brief-actors-list");
    if (actorsEl && actorsList) {
      var raw = brief.getAttribute("data-actors") || brief.getAttribute("data-who") || "";
      var names = raw.split(" · ").map(function (s) { return s.trim(); }).filter(Boolean);
      var who = brief.getAttribute("data-who") || "";
      actorsList.textContent = "";
      names.forEach(function (name) {
        var li = document.createElement("li");
        li.textContent = name;
        if (who && name === who) {
          var mark = document.createElement("span");
          mark.className = "muted";
          mark.textContent = " — this sheet";
          li.appendChild(mark);
        }
        actorsList.appendChild(li);
      });
      actorsEl.hidden = !names.length;
    }
    if (ta) ta.value = src ? src.value : "";
    dlg.showModal();
    var album = brief.getAttribute("data-album") || "";
    var pose = brief.getAttribute("data-label") || "";
    var tid = brief.getAttribute("data-tier-id") || "";
    var cid = brief.getAttribute("data-character-id") || "";
    if (album && pose && typeof api === "function") {
      var qs = new URLSearchParams();
      qs.set("pose", pose);
      if (tid) qs.set("tier", tid);
      if (cid) qs.set("character_id", cid);
      api("/api/albums/" + encodeURIComponent(album) + "/sheet-prompt?" + qs)
        .then(function (d) {
          if (d && d.prompt && ta && dlg.open) ta.value = d.prompt;
        })
        .catch(function () {});
    }
    return;
  }
  var tip = e.target.closest && e.target.closest(".help-tip");
  if (!tip) return;
  e.preventDefault();
  var dlg = document.getElementById("tip-modal");
  if (!dlg || typeof dlg.showModal !== "function") return;
  var title = document.getElementById("tip-modal-title");
  var body = document.getElementById("tip-modal-body");
  if (title) title.textContent = tip.getAttribute("data-label") || "Help";
  if (body) body.textContent = tip.getAttribute("data-help") || tip.title || "";
  dlg.showModal();
});

document.addEventListener("click", function (e) {
  var look = e.target.closest && e.target.closest(".look-tab");
  if (look) {
    var root = look.closest("form") || look.parentElement;
    var key = look.getAttribute("data-look");
    root.querySelectorAll(".look-tab").forEach(function (t) {
      t.classList.toggle("active", t === look);
    });
    (look.closest("form") || document).querySelectorAll(".look-panel").forEach(function (p) {
      var on = p.getAttribute("data-look") === key;
      p.classList.toggle("hidden", !on);
      if (on) revealLazy(p);
    });
    return;
  }
  var wtab = e.target.closest && e.target.closest(".wardrobe-tab");
  if (wtab) {
    var wroot = wtab.closest(".look-panel") || wtab.parentElement;
    var wkey = wtab.getAttribute("data-ward");
    wroot.querySelectorAll(".wardrobe-tab").forEach(function (t) {
      t.classList.toggle("active", t === wtab);
    });
    wroot.querySelectorAll(".wardrobe-panel").forEach(function (p) {
      var on = p.getAttribute("data-ward") === wkey;
      p.classList.toggle("hidden", !on);
      if (on) revealLazy(p);
    });
    return;
  }
  var ctab = e.target.closest && e.target.closest(".cast-tab");
  if (ctab) {
    var box = ctab.closest(".pl-fold") || ctab.parentElement.parentElement;
    if (ctab.hasAttribute("data-filter")) {
      var want = ctab.getAttribute("data-filter") || "";
      var head = ctab.closest(".section-head") || box;
      head.querySelectorAll(".cast-tab").forEach(function (t) {
        t.classList.toggle("active", t === ctab);
      });
      box.querySelectorAll(".anchor-tile").forEach(function (tile) {
        tile.classList.toggle("hidden", want && tile.dataset.character !== want);
      });
      return;
    }
    var key = ctab.getAttribute("data-cast");
    box.querySelectorAll(".look-chrome .cast-tab, .cast-tabs .cast-tab").forEach(function (t) {
      if (t.hasAttribute("data-filter")) return;
      t.classList.toggle("active", t === ctab);
    });
    if (key === "world") {
      box.querySelectorAll(".cast-panel").forEach(function (p) {
        p.classList.toggle("hidden", p.getAttribute("data-cast") !== "lead");
      });
      var lead = box.querySelector('.cast-panel[data-cast="lead"]');
      if (lead) {
        lead.querySelectorAll(".look-tab").forEach(function (t) {
          t.classList.remove("active");
        });
        lead.querySelectorAll(".look-panel").forEach(function (p) {
          var on = p.getAttribute("data-look") === "world";
          p.classList.toggle("hidden", !on);
        });
      }
      return;
    }
    box.querySelectorAll(".cast-panel").forEach(function (p) {
      var on = p.getAttribute("data-cast") === key;
      p.classList.toggle("hidden", !on);
      if (on) {
        revealLazy(p);
        var first = p.querySelector(".look-tab");
        if (first) first.click();
      }
    });
    return;
  }
  var sub = e.target.closest && e.target.closest(".cast-subtab");
  if (sub) {
    var panel = sub.closest(".cast-panel");
    var key = sub.getAttribute("data-sub");
    panel.querySelectorAll(".cast-subtab").forEach(function (t) {
      t.classList.toggle("active", t === sub);
    });
    panel.querySelectorAll(".cast-sub").forEach(function (p) {
      p.classList.toggle("hidden", p.getAttribute("data-sub") !== key);
    });
    return;
  }
  var pick = e.target.closest && e.target.closest(".js-pick-anchor");
  if (pick) {
    var dlg = document.getElementById(pick.getAttribute("data-dialog") || "");
    if (dlg && typeof dlg.showModal === "function") dlg.showModal();
    return;
  }
});

document.addEventListener("click", function (e) {
  var cover = e.target.closest && e.target.closest(".js-cover-open");
  if (!cover) return;
  var card = cover.closest(".playlist-card");
  e.preventDefault();
  e.stopPropagation();
  if (card && !card.open) {
    card.open = true;
    return;
  }
  var box = document.getElementById("cover-preview");
  if (!box) return;
  var img = document.getElementById("cover-preview-img");
  if (img) img.src = cover.getAttribute("data-full") || "";
  var pid = cover.getAttribute("data-playlist");
  var rep = document.getElementById("cover-replace");
  var del = document.getElementById("cover-delete");
  if (rep && pid) {
    rep.setAttribute("action", "/playlists/" + pid + "/image");
    rep.setAttribute("hx-post", "/playlists/" + pid + "/image");
    rep.setAttribute("hx-target", "#cover-slot-" + pid);
    rep.setAttribute("hx-swap", "innerHTML");
    if (window.htmx) htmx.process(rep);
  }
  if (del && pid) {
    del.setAttribute("action", "/playlists/" + pid + "/image/delete");
    del.setAttribute("hx-post", "/playlists/" + pid + "/image/delete");
    del.setAttribute("hx-target", "#cover-slot-" + pid);
    del.setAttribute("hx-swap", "innerHTML");
    if (window.htmx) htmx.process(del);
  }
  if (typeof box.showModal === "function") box.showModal();
}, true);

document.addEventListener("submit", function (e) {
  var busy = e.target.closest && e.target.closest(".js-busy-form");
  if (busy) busy.classList.add("is-busy");
});

document.addEventListener("change", function (e) {
  var pv = e.target.closest && e.target.closest(".js-pv-pick");
  if (pv) {
    if (!pv.value) return;
    var wrap = pv.closest(".js-pv");
    var ta = wrap && wrap.querySelector("textarea");
    api("/prompt-versions/select", {id: pv.value}).then(function (d) {
      if (ta && d.text != null) ta.value = d.text;
    }).catch(function () {});
    return;
  }
  var sel = e.target.closest && e.target.closest(".js-look-hist");
  if (!sel || !sel.value) return;
  var ta = document.getElementById(sel.getAttribute("data-target") || "");
  if (!ta) return;
  api("/prompt-versions/select", {id: sel.value}).then(function (d) {
    if (d && d.text != null) ta.value = d.text;
  }).catch(function () {
    fetch("/prompt-versions/" + sel.value + "/text")
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) { if (j && j.text != null) ta.value = j.text; });
  });
});

document.addEventListener("click", function (e) {
  var save = e.target.closest && e.target.closest(".js-pv-save");
  if (!save) return;
  e.preventDefault();
  var wrap = save.closest(".js-pv");
  var ta = wrap && wrap.querySelector("textarea");
  if (!wrap || !ta) return;
  api("/prompt-versions/touch", {
    scope: wrap.getAttribute("data-scope") || "",
    type: wrap.getAttribute("data-ptype") || "",
    tier: wrap.getAttribute("data-tier") || "",
    text: ta.value,
    label: "saved"
  }).then(function (d) {
    var pick = wrap.querySelector(".js-pv-pick");
    if (pick && d.versions) {
      pick.innerHTML = "";
      var cur = document.createElement("option");
      cur.value = "";
      cur.textContent = "current";
      pick.appendChild(cur);
      (d.versions || []).forEach(function (v) {
        var o = document.createElement("option");
        o.value = v.id;
        o.textContent = v.label || ("v" + v.version_number);
        pick.appendChild(o);
      });
      pick.value = String(d.id);
    }
  }).catch(function () {});
});
