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
      setTimeout(function () { location.reload(); }, 600);
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
