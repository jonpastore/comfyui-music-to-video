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

// Drag-to-reorder for playlist rows. Native HTML5 drag and drop -- a sortable
// library would be a dependency for what is one dragover handler and a POST.
// The row order in the DOM is the source of truth; on drop the new order of
// playlist_item ids is posted and the server renumbers positions.
document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var body = table.tBodies[0];
    var dragging = null;

    body.addEventListener("dragstart", function (e) {
      dragging = e.target.closest("tr");
      if (dragging) dragging.classList.add("dragging");
      // Firefox will not start a drag without data on the transfer
      if (e.dataTransfer) e.dataTransfer.setData("text/plain", "");
    });

    body.addEventListener("dragover", function (e) {
      e.preventDefault();
      var over = e.target.closest("tr");
      if (!dragging || !over || over === dragging) return;
      var rect = over.getBoundingClientRect();
      var after = (e.clientY - rect.top) > rect.height / 2;
      body.insertBefore(dragging, after ? over.nextSibling : over);
    });

    body.addEventListener("dragend", function () {
      if (!dragging) return;
      dragging.classList.remove("dragging");
      dragging = null;
      var ids = Array.prototype.map.call(body.rows, function (r) { return r.dataset.item; });
      Array.prototype.forEach.call(body.rows, function (r, i) {
        var pos = r.querySelector(".pos");
        if (pos) pos.textContent = i + 1;
      });
      var form = new FormData();
      form.append("order", ids.join(","));
      fetch("/playlists/" + table.dataset.playlist + "/reorder", {method: "POST", body: form});
    });
  });
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
  var plForm = e.target.closest(".delete-playlist");
  if (plForm && !confirm("Delete playlist " + plForm.dataset.name +
                         "? Songs and rendered videos are kept.")) {
    e.preventDefault();
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
});
