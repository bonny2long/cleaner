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

// Strays are never moved unless ticked. The ticks survive refreshes; they only count when the item is
// also in the reviewed plan (the server checks that again).
const ticked = new Set();

function tickBox(action) {
  if (action.category !== "unrecorded_leftover" || action.action !== "move_to_trash") return "";
  const inPlan = (reviewedPlan?.trash_candidates || []).some((c) => c.relative_path === action.relative_path);
  return `<label class="tick"><input type="checkbox" data-tick="${escapeHtml(action.relative_path)}"`
    + `${ticked.has(action.relative_path) ? " checked" : ""}${inPlan ? "" : " disabled"}> `
    + `${inPlan ? "Move to trash hold" : "Write a plan to review before ticking"}</label>`;
}

function card(action) {
  const evidence = action.evidence ? `Evidence: ${action.evidence.manifest_path}` : "No matched evidence";
  return `
    <article class="card">
      <h3>${escapeHtml(action.relative_path || action.path)}</h3>
      ${tickBox(action)}
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
    const trashOn = Boolean(config.trash_enabled);
    reviewedPlan = data.reviewed_plan || null;
    let modeText = "Cleaner is running in dry-run mode.";
    if (trashOn) modeText = `Cleaner can move reviewed items into a ${config.trash_hold_days}-day recoverable trash hold. Nothing is deleted.`;
    else if (executionOn) modeText = "Cleaner can remove reviewed empty folders. Everything else stays report-only.";
    const cautious = executionOn || trashOn;
    el("health").className = cautious ? "health warn" : ((blocked.length || counts.blocked) ? "health warn" : "health ok");
    el("health").textContent = (blocked.length || counts.blocked)
      ? `${modeText} Some items are blocked by safety gates.`
      : `${modeText} No unsafe cleanup action is enabled.`;
    renderExecuteButton(executionOn, data.reviewed_plan);
    renderTrashButton(trashOn);
    renderTrash(data.trash || {}, config);

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

// ---- trash hold ----------------------------------------------------------------------------------------

function trashSelection() {
  // Duplicates and ready discards go on the plan alone; strays only if ticked.
  return (reviewedPlan?.trash_candidates || []).filter((c) => !c.needs_tick || ticked.has(c.relative_path));
}

function renderTrashButton(trashOn) {
  const button = el("trashBtn");
  button.hidden = !trashOn;
  const selection = trashSelection();
  button.disabled = !trashOn || selection.length === 0;
  button.textContent = selection.length ? `Move ${selection.length} to trash hold` : "Move to trash hold";
  button.title = selection.length
    ? `From reviewed plan ${reviewedPlan.run_id}`
    : "Write a plan first. Only items in that plan can be moved, and strays also need a tick.";
}

function holdRow(run, entry, config) {
  const held = entry.status === "in_trash";
  const when = held
    ? (entry.expired ? "hold expired, can be purged" : `${entry.days_left} day(s) left`)
    : titleCase(entry.status);
  const restore = held && !entry.missing
    ? `<button type="button" data-restore="${escapeHtml(entry.relative_path)}" data-run="${escapeHtml(run.run_id)}">Restore</button>`
    : "";
  return `
    <article class="card">
      <h3>${escapeHtml(entry.relative_path)}</h3>
      <div class="meta">
        <span>${escapeHtml(titleCase(entry.category))}</span>
        <span>${entry.file_count ?? 0} file(s), ${formatBytes(entry.total_bytes)}</span>
        <span>${escapeHtml(run.run_id)}</span>
      </div>
      <span class="status ${held ? (entry.expired ? "warning" : "waiting") : "protected"}">${escapeHtml(when)}</span>
      ${entry.missing ? '<p class="detail">The held copy is missing from the trash folder.</p>' : ""}
      ${restore}
    </article>`;
}

function renderTrash(trash, config) {
  const holds = trash.holds || [];
  const target = el("trashList");
  const rows = holds.flatMap((run) => (run.entries || []).map((entry) => holdRow(run, entry, config)));
  el("trashBadge").textContent = trash.items_held || 0;
  el("trashSummary").textContent = trash.items_held
    ? `${trash.items_held} item(s), ${formatBytes(trash.bytes_held)} held for ${config.trash_hold_days} days each. ${trash.expired_items || 0} expired.`
    : "";
  target.className = rows.length ? "cards" : "cards empty";
  target.innerHTML = rows.length ? rows.join("") : "Nothing is in the trash hold.";
  const button = el("purgeBtn");
  const canPurge = Boolean(config.purge_enabled) && (trash.expired_items || 0) > 0;
  button.hidden = !config.purge_enabled;
  button.disabled = !canPurge;
  button.title = canPurge ? "" : "Only expired items can be purged.";
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
  return result;
}

function say(kind, text) {
  el("health").className = `health ${kind}`;
  el("health").textContent = text;
}

async function runTrashMove() {
  const selection = trashSelection();
  if (!reviewedPlan || selection.length === 0) return;
  const lines = selection.map((c) => `${c.relative_path}  (${c.file_count ?? "?"} files, ${formatBytes(c.total_bytes)})`);
  const confirmed = window.confirm(
    [
      `Move these ${selection.length} item(s) from plan ${reviewedPlan.run_id} into the trash hold?`,
      "",
      ...lines,
      "",
      "They are moved aside, not deleted, and can be restored until they are purged.",
      "Anything that changed since the plan was written is skipped.",
    ].join(String.fromCharCode(10))
  );
  if (!confirmed) return;
  const button = el("trashBtn");
  button.disabled = true;
  button.textContent = "Moving...";
  try {
    const result = await postJson("/api/trash/move", {
      run_id: reviewedPlan.run_id,
      include_paths: selection.map((c) => c.relative_path),
    });
    const skipped = (result.results || []).filter((r) => r.status !== "moved_to_trash" && r.status !== "skipped_needs_your_tick");
    say("ok", `Moved ${result.moved} item(s) to the trash hold.`
      + (skipped.length ? ` ${skipped.length} skipped or refused by safety checks.` : "")
      + ` Report: ${result.report_path}`);
    ticked.clear();
    await runDryPlan();
  } catch (err) {
    say("warn", `Moving to the trash hold failed: ${err.message}`);
    await loadDashboard();
  }
}

async function runRestore(trashRun, relativePath) {
  if (!window.confirm(`Restore ${relativePath} to where it came from?`)) return;
  try {
    const result = await postJson("/api/trash/restore", { trash_run: trashRun, relative_path: relativePath });
    say("ok", `Restored ${result.restored}.`);
  } catch (err) {
    say("warn", `Restore failed: ${err.message}`);
  }
  await loadDashboard();
}

async function runPurge() {
  const expired = [];
  try {
    const data = await (await fetch("/api/trash", { cache: "no-store" })).json();
    for (const run of data.holds || []) {
      for (const entry of run.entries || []) {
        if (entry.status === "in_trash" && entry.expired) expired.push({ trash_run: run.run_id, relative_path: entry.relative_path });
      }
    }
  } catch (err) {
    say("warn", `Could not read the trash hold: ${err.message}`);
    return;
  }
  if (!expired.length) return;
  const confirmed = window.confirm(
    [
      `Permanently delete these ${expired.length} expired item(s)?`,
      "",
      ...expired.map((e) => e.relative_path),
      "",
      "This cannot be undone.",
    ].join(String.fromCharCode(10))
  );
  if (!confirmed) return;
  try {
    const result = await postJson("/api/trash/purge", { entries: expired });
    const refused = (result.results || []).filter((r) => r.status === "refused").length;
    say("ok", `Purged ${result.purged} item(s).` + (refused ? ` ${refused} refused by safety checks.` : ""));
  } catch (err) {
    say("warn", `Purge failed: ${err.message}`);
  }
  await loadDashboard();
}

document.addEventListener("change", (event) => {
  const box = event.target.closest?.("[data-tick]");
  if (!box) return;
  if (box.checked) ticked.add(box.dataset.tick);
  else ticked.delete(box.dataset.tick);
  renderTrashButton(!el("trashBtn").hidden);
});

document.addEventListener("click", (event) => {
  const button = event.target.closest?.("[data-restore]");
  if (button) runRestore(button.dataset.run, button.dataset.restore);
});

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
el("trashBtn").addEventListener("click", runTrashMove);
el("purgeBtn").addEventListener("click", runPurge);
loadDashboard();
setInterval(loadDashboard, 30000);
