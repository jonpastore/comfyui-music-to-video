const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

const scenes = [
  { n: "01", title: "Station arrival", pose: "Three-quarter walk · rain platform", state: "Ready", cls: "still-1", duration: "7.2 s" },
  { n: "02", title: "Window reflection", pose: "Profile seated · train interior", state: "Ready", cls: "still-2", duration: "8.0 s" },
  { n: "03", title: "Crosswalk turn", pose: "Back view · wet street", state: "Ready", cls: "still-3", duration: "6.4 s" },
  { n: "04", title: "Neon close-up", pose: "Front · alley light", state: "Hold · identity repair", cls: "still-2", duration: "8.0 s", error: true },
  { n: "05", title: "Roofline dance", pose: "Full body · dawn roof", state: "Ready", cls: "still-1", duration: "9.6 s" },
  { n: "06", title: "Street chorus", pose: "Wide ensemble · night", state: "Ready", cls: "still-3", duration: "8.0 s" },
  { n: "07", title: "Direct address", pose: "Front · club doorway", state: "Ready · WAN route", cls: "still-2", duration: "7.5 s", lip: true },
  { n: "08", title: "Homeward walk", pose: "Side walk · blue hour", state: "Ready", cls: "still-1", duration: "7.0 s" },
  { n: "09", title: "End frame", pose: "Back silhouette · platform", state: "Preview running", cls: "still-3", duration: "6.6 s" },
];

const sceneGrid = $("#scene-grid");
sceneGrid.innerHTML = scenes.map(scene => `<article class="scene-card"><div class="mock-thumb ${scene.cls}" role="img" aria-label="Mock reference for scene ${scene.n}"></div><div><h2>${scene.n} · ${scene.title}</h2><p>${scene.pose}</p><footer><span class="badge">${scene.duration}</span>${scene.lip ? '<span class="badge lip">Lip sync · WAN</span>' : '<span class="badge">LTX only</span>'}<span class="badge ${scene.error ? 'error' : ''}">${scene.state}</span></footer></div></article>`).join("");

const inspectorContent = {
  repair: `<div class="eyebrow">Hard blocker · Scene 04 · plan v12</div><h2>Scene 04 exhausted four repair attempts</h2><div class="mock-thumb wide still-2" role="img" aria-label="Mock degraded scene frame"></div><p>Identity diverged during the reference-to-motion handoff. Audio and 8.0 s duration passed validation.</p><div class="metric-row"><span class="metric">92% confidence</span><span class="metric">2 min estimate</span><span class="metric">Local only</span></div><b>Recommended next action</b><p>Authorize a bounded fifth attempt against the reference stage only; successful motion work remains intact.</p><div class="button-stack"><button class="primary" data-open-dialog="exception">Authorize exception repair</button><button data-open-dialog="override">Override finding</button><button data-open-dialog="evidence">Open all evidence</button></div>`,
  approve: `<div class="eyebrow">Decision · plan version 12</div><h2>Approve eight scene plans</h2><div class="mock-thumb wide still-1"></div><p>References, locations, poses, and motion previews are ready. Scene 04 remains held and will not enter the expensive batch.</p><div class="metric-row"><span class="metric">8 ready</span><span class="metric">1 held</span><span class="metric">9 min preview</span></div><div class="button-stack"><a class="primary" href="#plan">Review approval package</a><button data-toast="Approval reminder snoozed in mock state">Remind me in 1 hour</button></div>`,
  cloud: `<div class="eyebrow">Authorization required · immutable binding</div><h2>Cloud lip-sync repair</h2><p><b>Scene 07 · plan v12 · source attempt 3 · current as of 10:42.</b> VoiceForge would receive decoded frames and the selected audio segment to produce the bound lip-sync repair output. This is not self-hosted work.</p><div class="metric-row"><span class="metric">Max $1.80</span><span class="metric">1 repair job</span><span class="metric">Expires in 30 min</span><span class="metric">No retries</span></div><div class="button-stack"><button class="primary" data-open-dialog="cloud">Review authorization</button><button data-toast="Cloud option declined in mock state">Keep local only</button></div>`,
  keeper: `<div class="eyebrow">Verification required · Scene 04</div><h2>Confirm this keeper’s canonical identity</h2><div class="mock-thumb wide still-2" role="img" aria-label="Mock keeper needing identity verification"></div><p>This asset is held from new reference use because its membership context does not match the available evidence. Existing scene evidence, timing, and historical records remain intact.</p><div class="metric-row"><span class="metric">No new reuse</span><span class="metric">Existing evidence retained</span><span class="metric">No automatic rewrite</span></div><b>Safe next action</b><p>Compare the accepted anchor and membership context, then record a verification decision. This mock action changes no keeper data.</p><div class="button-stack"><button class="primary" data-toast="Keeper verification opened in mock state">Compare canonical evidence</button><button data-toast="Keeper remains held in mock state">Keep reference use on hold</button></div>`,
  fleet: `<div class="eyebrow">System blocked · fleet</div><h2>peaches is unavailable</h2><p>Local preview jobs moved to cerberus. No active clips were interrupted and no decision is required unless you want to investigate the worker.</p><div class="metric-row"><span class="metric">3 rerouted</span><span class="metric">0 lost</span><span class="metric">9 min age</span></div><div class="button-stack"><button data-toast="Operations opened in mock state">Open operations</button><button data-toast="Worker notification acknowledged">Acknowledge</button></div>`
};
const inspector = $("#attention-inspector");
function selectAttention(item) { $$(".attention-item").forEach(el => el.classList.toggle("selected", el.dataset.item === item)); inspector.innerHTML = inspectorContent[item]; bindDynamicButtons(inspector); }
selectAttention("repair");
$$(".attention-item").forEach(item => item.addEventListener("click", () => selectAttention(item.dataset.item)));
document.addEventListener("click", event => {
  const opener = event.target.closest("[data-attention-item]");
  if (opener) selectAttention(opener.dataset.attentionItem);
});

const toast = $("#toast");
let toastTimer;
function showToast(message) { toast.textContent = message; toast.classList.add("show"); clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.classList.remove("show"), 2800); }
function bindDynamicButtons(root = document) { $$('[data-toast]', root).forEach(button => button.addEventListener("click", () => showToast(button.dataset.toast))); }
bindDynamicButtons();

const dialog = $("#dialog"), dialogContent = $("#dialog-content");
const dialogs = {
  help: `<h2>Keyboard help</h2><p>Use <kbd>?</kbd> for help, <kbd>Esc</kbd> to close dialogs, and <kbd>Tab</kbd> to move through decisions. This prototype uses working controls only to demonstrate feedback; it never writes production data.</p>`,
  compare: `<h2>Compare attempts</h2><p>Attempt 1 kept the anchor but had weak motion. Attempts 2–4 pass motion validation but drift from the accepted face. The recommended action targets only the reference stage.</p><div class="mock-thumb wide still-1"></div><div class="dialog-actions"><button data-close-dialog>Cancel</button><button class="primary" data-toast="Attempt 1 selected as comparison">Select attempt 1</button></div>`,
  override: `<h2>Override QC finding</h2><p>Record why this hard blocker is acceptable. This becomes auditable local training evidence; it does not send data to a cloud service.</p><label>Reason <select><option>Identity difference is intentional</option><option>QC model is mistaken</option><option>Accepted with creative exception</option></select></label><div class="dialog-actions"><button data-close-dialog>Cancel</button><button id="record-override" class="primary" data-close-dialog>Record override</button></div>`,
  storyboard: `<h2>Return to storyboard</h2><p>This would preserve the current assembled attempt and open Scene 04’s storyboard intent, not reset the production.</p><div class="dialog-actions"><button data-close-dialog>Cancel</button><button class="primary" data-toast="Storyboard opened in mock state">Open storyboard</button></div>`,
  evidence: `<h2>Scene 04 evidence</h2><dl><dt>Failure</dt><dd>Identity mismatch at 00:42.3</dd><dt>Stage</dt><dd>Reference → LTX handoff</dd><dt>Duration</dt><dd>8.0 s requested / 8.0 s decoded</dd><dt>Attempts</dt><dd>4 total; attempt limit reached</dd><dt>Settings</dt><dd>Qwen Image Edit 2511 · local</dd></dl>`,
  cloud: `<h2>Authorize paid cloud repair</h2><p><b>Immutable binding:</b> Scene 07 · plan v12 · source attempt 3 · current as of 10:42<br><b>Target output:</b> one VoiceForge lip-sync repair candidate for Scene 07, preserving the 7.5 s requested duration.<br><b>Provider:</b> VoiceForge · <b>Data leaving host:</b> decoded frames and selected audio<br><b>Scope:</b> one repair job; maximum $1.80 · <b>Duration:</b> expires in 30 minutes; no automatic retries</p><p>If plan, source attempt, or audio changes, this authorization is invalid and a revised request must be reviewed.</p><div class="dialog-actions"><button data-close-dialog>Cancel</button><button id="confirm-cloud" class="primary">Authorize $1.80 max</button></div>`,
  "set-plan": `<h2>Set plan rationale</h2><p>The proposed arrangement optimizes energy and narrative clarity using the five approved song storyboards, lyric analysis, and musical structure. It proposes four short, non-destructive connective derivatives.</p><div class="dialog-actions"><button data-close-dialog>Cancel</button><button class="primary" data-toast="Set plan approved in mock state">Approve plan</button></div>`,
  "set-approval": `<h2>Approve set plan v6</h2><p><b>Bound plan:</b> v6 · current as of 10:42 · local 41 min · $0. Standalone masters remain immutable.</p><p><b>Manifest:</b><br>First Light v4: 00:00–06:42, trim out 1.2 s / fade derivative.<br>Neon Aftercare v18: 06:41–10:23, replace edge 4 s with street reflection.<br>Glass Ocean v7: 10:19–17:02, bridge with title image 4 s.<br>Afterglow v3: 17:06–24:44, regenerate train-exit connective 5 s.<br>Home Signal v5: 24:49–33:18, dawn-dissolve derivative 7 s.</p><p>If a source master, range, or derivative changes, this approval is stale; review a revised plan request.</p><div class="dialog-actions"><button data-close-dialog>Cancel</button><button id="confirm-set-plan" class="primary">Approve plan v6</button></div>`,
  reauthorize: `<h2>Reauthorize archive delivery</h2><p><b>Target:</b> Partner vault / album 12 · <b>Artifact:</b> Midnight on the Line master v6 · <b>Scope:</b> one delivery retry. The destination account token expired before upload; no duplicate transfer will start until the provider confirms authorization.</p><div class="dialog-actions"><button data-close-dialog>Cancel</button><button class="primary" data-toast="Mock reauthorization started">Continue to provider</button></div>`
};
let dialogOpener;
function openDialog(key, opener = document.activeElement) { dialogOpener = opener; dialogContent.innerHTML = dialogs[key] || '<h2>Mock dialog</h2>'; const title = $("h2", dialogContent); if (title) title.id = "dialog-title"; dialog.showModal(); bindDynamicButtons(dialogContent); }
document.addEventListener("click", event => {
  const opener = event.target.closest("[data-open-dialog]");
  if (opener) openDialog(opener.dataset.openDialog, opener);
});
dialog.addEventListener("click", event => { if (event.target === dialog || event.target.matches("[data-close-dialog]")) dialog.close(); });
dialog.addEventListener("close", () => dialogOpener?.focus());
document.addEventListener("keydown", event => { if (event.key === "?" && !dialog.open) { event.preventDefault(); openDialog("help"); } });

$("#approve-ready").addEventListener("click", () => { if ($("#fixture").value === "stale") return; $("#approve-ready").textContent = "8 scenes approved"; $("#approve-ready").disabled = true; showToast("Eight ready scenes approved; Scene 04 remains held."); });
$("#play-toggle").addEventListener("click", event => { const pressed = event.currentTarget.getAttribute("aria-pressed") === "true"; event.currentTarget.setAttribute("aria-pressed", String(!pressed)); event.currentTarget.textContent = pressed ? "▶ Play" : "Ⅱ Pause"; $(".media-status").textContent = pressed ? "Paused" : "Playing mock"; });
$(".media-play").addEventListener("click", () => $("#play-toggle").click());

function syncActiveNav() {
  const target = location.hash || "#directions";
  $$(".nav-links a").forEach(link => link.classList.toggle("active", link.getAttribute("href") === target));
}
window.addEventListener("hashchange", syncActiveNav);
syncActiveNav();

// Review decisions are version-bound. A visible hard blocker is not an
// approvable master; only an audited repair/override unlocks final approval.
const findings = {
  identity: { time: "00:42.3", title: "Anchor identity drifts", severity: "high", body: "The face differs from the accepted anchor after the reference-to-motion handoff. Audio and 8.0 s duration passed validation.", action: "Authorize exception repair", evidence: "Local identity verifier 0.8 · 92% confidence · attempts 1–4 retained" },
  lipsync: { time: "02:22.0", title: "Lip-sync drift", severity: "med", body: "Visible singing falls behind the decoded audio by 180 ms. Duration is still valid; this scene is routed through WAN at 16 fps using timestamp-sampled LTX frames.", action: "Review lip-sync repair", evidence: "Local sync verifier 0.74 · Scene 07 · requested duration 7.5 s" }
};
const findingPanel = $("#finding-panel");
function renderFinding(key) {
  const finding = findings[key];
  findingPanel.innerHTML = `<div class="finding-header"><span class="severity-icon ${finding.severity}">!</span><div><div class="eyebrow">${finding.time} · assembled master v18</div><h2>${finding.title}</h2></div></div><p>${finding.body}</p><div class="proposed"><b>Recommended repair</b><span>${key === "identity" ? "Attempt 5: regenerate only the reference stage from the accepted anchor; preserve 8.0 s timing." : "Inspect the timestamp-sampled WAN output before a constrained sync repair."}</span><small>Effective policy: production override · affected unit: ${key === "identity" ? "Scene 04" : "Scene 07"} · ${finding.evidence}</small></div><div class="button-stack"><button class="primary" data-open-dialog="exception">${finding.action}</button><button data-open-dialog="override">Record audited override</button><button data-open-dialog="storyboard">Revise storyboard</button></div><details class="evidence"><summary>Evidence and settings</summary><p>${finding.evidence}. Current master v18, current as of 10:42.</p></details>`;
}
renderFinding("identity");
$$(".marker[data-finding]").forEach(marker => marker.addEventListener("click", () => { const time = findings[marker.dataset.finding].time; $(".timecode").textContent = time; $(".playhead").style.left = marker.style.left; $(".playhead").setAttribute("aria-label", `Current time ${time}`); renderFinding(marker.dataset.finding); }));

// One bounded exception request replaces a misleading ordinary retry after the
// fourth attempt. It leaves durable inline confirmation rather than a toast.
dialogs.exception = `<h2>Authorize exception repair</h2><p><b>Attempt:</b> 5 of 5 · <b>Target:</b> Scene 04 reference stage only · <b>Changed input:</b> accepted anchor v12 replaces the drifted reference.</p><p><b>Execution:</b> self-hosted / local · 2 min estimate · $0 · no cloud data transfer.<br><b>Effective scope:</b> Production “Neon Aftercare” override; blast radius is Scene 04 only.<br><b>Version:</b> scene plan v12 / master v18; request escalates again on failure.</p><div class="dialog-actions"><button data-close-dialog>Cancel</button><button id="confirm-exception" class="primary">Authorize attempt 5</button></div>`;
document.addEventListener("click", event => {
  if (event.target.id !== "confirm-exception") return;
  event.target.disabled = true;
  event.target.textContent = "Accepted · request UX-204 · queued";
  const approval = $("#video-approval");
  approval.disabled = true;
  approval.textContent = "Repair queued · approval blocked";
  findingPanel.insertAdjacentHTML("afterbegin", `<p class="status success">Accepted · request UX-204 · queued</p><p class="audit-event">Audit · Operator · now · Scene 04 / attempt 5 / plan v12 · exception repair authorized · local learning signal recorded (not identity).</p>`);
});
document.addEventListener("click", event => {
  if (event.target.id !== "record-override") return;
  findingPanel.insertAdjacentHTML("afterbegin", `<p class="audit-event">Audit · Operator · now · master v18 / finding at 00:42 / attempt 4 · reason recorded · production override policy · local learning signal recorded (not identity).</p>`);
  $("#video-approval").disabled = false;
  $("#video-approval").textContent = "Approve master v18";
});
document.addEventListener("click", event => {
  if (event.target.id !== "confirm-cloud") return;
  event.target.disabled = true;
  event.target.textContent = "Accepted · request CLD-071 · provider pending";
  const cloudReview = inspector.querySelector('[data-open-dialog="cloud"]');
  if (cloudReview) { cloudReview.disabled = true; cloudReview.textContent = "Authorized · CLD-071 pending"; }
  inspector.insertAdjacentHTML("afterbegin", `<p class="status approval">Accepted · request CLD-071 · VoiceForge pending</p><p class="audit-event">Bound request: Scene 07 / plan v12 / source attempt 3. Duplicate authorization is disabled; any changed source requires revised request review.</p>`);
});
document.addEventListener("click", event => {
  if (event.target.id !== "confirm-set-plan") return;
  event.target.disabled = true;
  event.target.textContent = "Accepted · request SET-006 · queued";
  const setReview = document.querySelector('[data-open-dialog="set-approval"]');
  if (setReview) { setReview.disabled = true; setReview.textContent = "Accepted · SET-006 queued"; }
  $(".set-summary").insertAdjacentHTML("afterbegin", `<span class="status success">Accepted · request SET-006 · plan v6 queued</span>`);
});
$("#video-approval").addEventListener("click", () => showToast("Mock approval recorded for master v18."));

// Attention uses real tab semantics, roving tabindex, and different panels.
const attentionPanels = {
  action: document.querySelector("#attention-list").innerHTML,
  ready: `<li class="attention-item"><button><span class="severity-icon med">✓</span><span><b>Neon Aftercare master is ready for review</b><small>master v18 · 03:42 · current as of 10:42</small></span><span class="item-meta">Open review</span></button></li><li class="attention-item"><button><span class="severity-icon med">✓</span><span><b>Midnight on the Line plan is ready</b><small>plan v6 · 5 masters + 4 derivatives</small></span><span class="item-meta">41 min local</span></button></li>`,
  system: `<li class="attention-item"><button><span class="severity-icon low">↯</span><span><b>peaches fleet worker is unavailable</b><small>3 previews rerouted; no work lost</small></span><span class="item-meta">Operations</span></button></li>`
};
const attentionTabs = $$(".queue-tabs [role=tab]");
function activateTab(tab) { attentionTabs.forEach(item => { const selected = item === tab; item.setAttribute("aria-selected", selected); item.tabIndex = selected ? 0 : -1; }); const key = tab.id.replace("tab-", ""); $("#attention-list").innerHTML = attentionPanels[key]; $("#attention-panel").setAttribute("aria-labelledby", tab.id); }
attentionTabs.forEach((tab, index) => tab.addEventListener("keydown", event => { const keys = ["ArrowLeft", "ArrowRight", "Home", "End"]; if (!keys.includes(event.key)) return; event.preventDefault(); const next = event.key === "Home" ? 0 : event.key === "End" ? attentionTabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + attentionTabs.length) % attentionTabs.length; attentionTabs[next].focus(); activateTab(attentionTabs[next]); }));
attentionTabs.forEach(tab => tab.addEventListener("click", () => activateTab(tab)));

// Fixture changes are idempotent: start at the base UI before adding a state.
const fixtureBase = { version: "12", approval: "Approve 8 ready scenes" };
const keeperNote = "A scene uses a canonical source asset. Album and tier scope are context, not a second editable copy.";
$("#fixture").addEventListener("change", event => {
  const mode = event.target.value;
  document.body.dataset.fixture = mode;
  $("#empty-queue").hidden = true;
  $("#attention-panel").hidden = false;
  $("#plan-version").textContent = fixtureBase.version;
  $(".approval-banner").classList.remove("stale");
  $("#approve-ready").textContent = fixtureBase.approval;
  $("#approve-ready").disabled = false;
  $("#approve-ready").onclick = null;
  $("#keeper-context").classList.remove("review-required");
  $("#keeper-context-note").textContent = keeperNote;
  $(".media-status").textContent = "Paused";
  selectAttention("repair");
  if (mode === "empty") { $("#empty-queue").hidden = false; $("#attention-panel").hidden = true; }
  if (mode === "cloud") selectAttention("cloud");
  if (mode === "keeper-review") { $("#keeper-context").classList.add("review-required"); $("#keeper-context-note").textContent = "Verification required: this shared keeper is held from new reference use until its canonical identity is confirmed. Existing scene evidence remains intact."; selectAttention("keeper"); }
  if (mode === "degraded") { inspector.innerHTML = `<div class="eyebrow">Missing media · hard blocker</div><h2>Scene 04 evidence is unavailable</h2><div class="mock-thumb wide" aria-label="Media unavailable"><span class="media-status">Artifact unavailable</span></div><p>The decision cannot be approved while the visual evidence is missing. The stored attempt and timing metadata remain intact.</p><div class="button-stack"><button class="primary" data-toast="Artifact recovery queued in mock state">Recover artifact</button><button data-toast="Issue escalated in mock state">Escalate to operations</button></div>`; bindDynamicButtons(inspector); }
  if (mode === "running") $(".media-status").textContent = "Validating · 76%";
  if (mode === "stale") {
    $("#plan-version").textContent = "12 · superseded by v13 (hash 9d70…7bc)";
    $(".approval-banner").classList.add("stale");
    $("#approve-ready").textContent = "Compare / reload plan v13";
    $("#approve-ready").onclick = () => showToast("Plan v13 loaded: approved 01–03, 05–09; held 04; 9 min estimated local work.");
  }
  if (mode === "release") location.hash = "release";
});
