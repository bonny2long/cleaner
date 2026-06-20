const el = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function titleCase(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function actionClass(category) {
  if (category === "safe_empty_folder") return "ready";
  if (category === "blocked_too_new") return "waiting";
  if (category === "quarantine_hold" || category === "do_not_touch") return "protected";
  if ((category || "").startsWith("blocked")) return "blocked";
  return "warning";
}

function renderPaths(config) {
  const rows = [
    ["Data root", config.data_root],
    ["Ready", config.ready_dir],
    ["Leftover review", config.leftover_review_dir],
    ["Quarantine", config.quarantine_dir],
    ["Reports", config.reports_dir],
    ["Mode", `${titleCase(config.mode)} / dry-run ${config.dry_run} / ${config.min_age_days}-day age gate`],
  ];
  el("paths").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${escapeHtml(v)}</dd>`).join("");
}

function card(action) {
  const evidence = action.evidence ? `Evidence: ${action.evidence.manifest_path}` : "No matched evidence";
  return `
    <article class="card">
      <h3>${escapeHtml(action.relative_path || action.path)}</h3>
      <div class="meta">
        <span>${escapeHtml(action.action || "report_only")}</span>
        <span>${escapeHtml(action.safety_status || "")}</span>
        <span>${escapeHtml(evidence)}</span>
      </div>
      <span class="status ${actionClass(action.category)}">${escapeHtml(titleCase(action.category))}</span>
      <p class="detail">${escapeHtml(action.reason || "")}</p>
    </article>
  `;
}

function eventRow(event) {
  const title = event.event || "event";
  const time = event.timestamp || "";
  const detail = event.markdown_path || event.json_path || event.run_id || "";
  return `<article class="event"><strong>${escapeHtml(title)}</strong><br>${escapeHtml(time)}<br>${escapeHtml(detail)}</article>`;
}

function renderList(id, items, emptyText, renderer = card) {
  const target = el(id);
  if (!items || items.length === 0) {
    target.className = id === "eventList" ? "events empty" : "cards empty";
    target.textContent = emptyText;
    return;
  }
  target.className = id === "eventList" ? "events" : "cards";
  target.innerHTML = items.map(renderer).join("");
}

async function loadDashboard() {
  const refresh = el("refreshBtn");
  refresh.disabled = true;
  refresh.textContent = "Refreshing...";
  try {
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const lanes = data.lanes || {};
    const counts = data.counts || {};
    const config = data.config || {};

    const safe = lanes.ready_to_clean_later || [];
    const tooNew = lanes.too_new || [];
    const review = lanes.leftovers_need_review || [];
    const quarantine = lanes.quarantine_hold || [];
    const blocked = lanes.blocked_by_safety || [];
    const protectedItems = lanes.protected || [];
    const events = data.events || [];

    el("health").className = (blocked.length || counts.blocked) ? "health warn" : "health ok";
    el("health").textContent = (blocked.length || counts.blocked)
      ? "Cleaner is running in dry-run mode. Some items are blocked by safety gates."
      : "Cleaner is running in dry-run mode. No unsafe cleanup action is enabled.";

    el("countSafe").textContent = safe.length;
    el("countTooNew").textContent = tooNew.length;
    el("countReview").textContent = review.length;
    el("countQuarantine").textContent = quarantine.length;
    el("countBlocked").textContent = blocked.length;

    el("safeBadge").textContent = safe.length;
    el("newBadge").textContent = tooNew.length;
    el("reviewBadge").textContent = review.length;
    el("blockedBadge").textContent = blocked.length;
    el("eventBadge").textContent = quarantine.length + protectedItems.length + events.length;

    renderPaths(config);
    renderList("safeList", safe, "No safe empty folders found.");
    renderList("newList", tooNew, "No too-new items.");
    renderList("reviewList", review, "No leftovers needing review.");
    renderList("blockedList", blocked, "No blocked items.");
    renderList(
      "eventList",
      [...quarantine, ...protectedItems].map((a) => ({ event: titleCase(a.category), timestamp: a.relative_path, json_path: a.reason })).concat(events.slice(-20).reverse()),
      "No reports yet.",
      eventRow
    );
  } catch (err) {
    el("health").className = "health warn";
    el("health").textContent = `Dashboard error: ${err.message}`;
  } finally {
    refresh.disabled = false;
    refresh.textContent = "Refresh";
  }
}

async function runDryPlan() {
  const button = el("dryRunBtn");
  button.disabled = true;
  button.textContent = "Writing report...";
  try {
    const response = await fetch("/api/run-dry-plan", { method: "POST" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    await loadDashboard();
  } catch (err) {
    el("health").className = "health warn";
    el("health").textContent = `Dry-run failed: ${err.message}`;
  } finally {
    button.disabled = false;
    button.textContent = "Run dry plan";
  }
}

el("refreshBtn").addEventListener("click", loadDashboard);
el("dryRunBtn").addEventListener("click", runDryPlan);
loadDashboard();
setInterval(loadDashboard, 30000);
