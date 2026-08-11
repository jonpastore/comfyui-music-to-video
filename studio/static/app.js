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
  var form = e.target.closest(".delete-tier");
  if (form && !confirm("Delete tier " + form.dataset.tier + "?")) {
    e.preventDefault();
  }
});
