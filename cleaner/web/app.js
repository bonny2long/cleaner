const el = (id) => document.getElementById(id);

function setCount(id, value, color) {
  const span = el(id);
  if (!span) return;
  span.textContent = value;
  span.style.color = value > 0 && color ? color : "";
}
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

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${(bytes / 1e3).toFixed(0)} KB`;
  return `${bytes} B`;
}

function detailLine(action) {
  const d = action.details;
  if (!d) return "";
  if (action.category === "verified_duplicate") {
    const example = (d.library_matches || [])[0];
    return `${d.matched_files} of ${d.content_files} media files match the library (${formatBytes(d.total_bytes)})`
      + (example ? `. Example: ${example.file} = ${example.library_path}` : "");
  }
  if (action.category === "unrecorded_leftover") {
    if (d.duplicate_check === "pending") return "Not yet checked against the library.";
    const parts = [`${d.matched_files || 0} of ${d.content_files || 0} media files match the library`];
    if ((d.unmatched_examples || []).length) parts.push(`not in a library: ${d.unmatched_examples.join(", ")}`);
    if ((d.other_file_examples || []).length) parts.push(`unrecognised: ${d.other_file_examples.join(", ")}`);
    return parts.join(". ");
  }
  if (action.category === "quarantine_discard_approved") {
    const when = d.eligible_now ? "eligible now" : `eligible after ${String(d.eligible_after || "").slice(0, 10)}`;
    return `Decided ${String(d.decided_at || "").slice(0, 10)} (batch ${d.batch_id}); ${d.file_count} file(s), ${formatBytes(d.size_bytes)}; ${when}`;
  }
  return "";
}

function actionClass(category) {
  if (category === "verified_duplicate" || category === "quarantine_discard_approved") return "ready";
  if (category === "unrecorded_leftover") return "warning";
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
      ${detailLine(action) ? `<p class="detail">${escapeHtml(detailLine(action))}</p>` : ""}
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
    const duplicates = lanes.duplicates || [];
    const discards = lanes.quarantine_discards || [];
    const unrecorded = lanes.unrecorded || [];
    const quarantine = lanes.quarantine_hold || [];
    const blocked = lanes.blocked_by_safety || [];
    const protectedItems = lanes.protected || [];
    const events = data.events || [];

    el("gateTitle").textContent = `Waiting ${config.min_age_days ?? 30}-Day Gate`;
    const executionOn = Boolean(config.execution_enabled);
    const modeText = executionOn
      ? "Cleaner can remove reviewed empty folders. Everything else stays report-only."
      : "Cleaner is running in dry-run mode.";
    el("health").className = executionOn ? "health warn" : ((blocked.length || counts.blocked) ? "health warn" : "health ok");
    el("health").textContent = (blocked.length || counts.blocked)
      ? `${modeText} Some items are blocked by safety gates.`
      : `${modeText} No unsafe cleanup action is enabled.`;
    renderExecuteButton(executionOn, data.reviewed_plan);

    setCount("countSafe", safe.length, "#10B981");
    setCount("countTooNew", tooNew.length, "#f59e0b");
    setCount("countReview", review.length, null);
    setCount("countQuarantine", quarantine.length, null);
    setCount("countDuplicates", duplicates.length, "#10B981");
    setCount("countDiscards", discards.length, "#10B981");
    setCount("countUnrecorded", unrecorded.length, "#f59e0b");
    setCount("countBlocked", blocked.length, "#ef4444");

    el("safeBadge").textContent = safe.length;
    el("newBadge").textContent = tooNew.length;
    el("reviewBadge").textContent = review.length;
    el("duplicateBadge").textContent = duplicates.length;
    el("discardBadge").textContent = discards.length;
    el("unrecordedBadge").textContent = unrecorded.length;
    el("blockedBadge").textContent = blocked.length;
    el("eventBadge").textContent = quarantine.length + protectedItems.length + events.length;

    renderPaths(config);
    renderList("safeList", safe, "No safe empty folders found.");
    renderList("newList", tooNew, "No too-new items.");
    renderList("reviewList", review, "No leftovers needing review.");
    renderList("duplicateList", duplicates, "No verified duplicates.");
    renderList("discardList", discards, "No approved discards.");
    renderList("unrecordedList", unrecorded, "No unrecorded leftovers.");
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

let reviewedPlan = null;

function renderExecuteButton(executionOn, plan) {
  const button = el("executeBtn");
  el("dryRunBtn").textContent = executionOn ? "Write plan to review" : "Run dry plan";
  reviewedPlan = plan || null;
  const count = plan ? plan.remove_empty_folder_count || 0 : 0;
  button.hidden = !executionOn;
  button.disabled = !executionOn || count === 0;
  button.textContent = count ? `Remove ${count} empty folder${count === 1 ? "" : "s"}` : "Remove empty folders";
  button.title = count
    ? `From reviewed plan ${plan.run_id}`
    : "Write a plan first. Only folders listed in that plan can be removed.";
}

async function runExecute() {
  if (!reviewedPlan) return;
  const paths = reviewedPlan.remove_empty_folder_paths || [];
  const confirmed = window.confirm(
    [
      `Remove these ${paths.length} empty folder(s) from plan ${reviewedPlan.run_id}?`,
      "",
      ...paths,
      "",
      "Only folders that are still empty right now are removed. Files are never deleted.",
    ].join(String.fromCharCode(10))
  );
  if (!confirmed) return;
  const button = el("executeBtn");
  button.disabled = true;
  button.textContent = "Removing...";
  try {
    const response = await fetch("/api/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: reviewedPlan.run_id }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    const refused = (result.results || []).filter((item) => item.status === "refused").length;
    el("health").className = "health ok";
    el("health").textContent = `Removed ${result.removed} empty folder(s).`
      + (refused ? ` ${refused} refused by safety checks.` : "")
      + ` Report: ${result.report_path}`;
    await runDryPlan();
  } catch (err) {
    el("health").className = "health warn";
    el("health").textContent = `Cleanup failed: ${err.message}`;
    await loadDashboard();
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
    if (button.textContent === "Writing report...") button.textContent = "Run dry plan";
  }
}

el("refreshBtn").addEventListener("click", loadDashboard);
el("dryRunBtn").addEventListener("click", runDryPlan);
el("executeBtn").addEventListener("click", runExecute);
loadDashboard();
setInterval(loadDashboard, 30000);
