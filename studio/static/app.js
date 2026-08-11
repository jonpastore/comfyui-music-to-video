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
