/* Job Search Dashboard — G9 join + O6 polish (deployed, widgets, run.log) */

const JOIN_STATUSES = ["completed", "approved", "rejected", "new", "active"];
const EXEC_STATUSES = ["in_progress", "failed", "completed", "deployed"];
const JOIN_COUNT_CLASS = {
  Total: "count-blue",
  new: "count-blue",
  active: "count-blue",
  approved: "count-green",
  completed: "count-green",
  rejected: "count-red",
};
const POLL_MS = 30000;
const LOG_PATH = "../orchestrator/run.log";
const BOTTOM_PX = 16;
const LOG_TRAILER_DELIMITER = "--- orch-telemetry ---";
const TELEMETRY_FIELDS = [
  ["started_at", "Started"],
  ["ended_at", "Ended"],
  ["tokens_in", "Tokens in"],
  ["tokens_out", "Tokens out"],
  ["cache_tokens_in", "Cache tokens in"],
  ["thinking_tokens", "Thinking tokens"],
  ["context_usage_percent", "Context usage %"],
  ["context_metric_status", "Context metric"],
];

async function fetchJson(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} for ${path}`);
  }
  return res.json();
}

async function fetchText(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} for ${path}`);
  }
  return res.text();
}

async function listDirectory(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    return [];
  }
  const html = await res.text();
  const matches = [...html.matchAll(/href="([^"]+)\/?"/gi)];
  return matches
    .map((m) => decodeURIComponent(m[1]))
    .filter((name) => name && name !== "../" && !name.startsWith("?") && !name.startsWith("/"));
}

function encodeJobId(jobId) {
  return String(jobId).replaceAll(":", "-");
}

function currentAnalysis(sidecar) {
  if (!sidecar || !Array.isArray(sidecar.analyses)) return null;
  return sidecar.analyses.find((row) => row && row.is_current === true) || null;
}

function executionStatus(queueRow) {
  if (!queueRow) return "not_started";
  if (queueRow.status) return queueRow.status;
  if (queueRow.id && queueRow.approved_at) return "approved";
  return "not_started";
}

function pipelineStatus(job, analysis, queueRow) {
  const exec = executionStatus(queueRow);
  if (exec === "completed" || exec === "deployed") return "completed";
  if (exec === "in_progress" || exec === "failed" || exec === "approved") return "approved";
  const decision = analysis && analysis.decision;
  if (decision === "approved") return "approved";
  if (decision === "rejected") return "rejected";
  if (job.status === "new" || job.status === "active") return job.status;
  return job.status || "unknown";
}

async function datedSrcDates(platform) {
  const base = `../${platform}/src/`;
  const entries = await listDirectory(base);
  return entries
    .map((e) => e.replace(/\/$/, ""))
    .filter((e) => /^\d{4}-\d{2}-\d{2}$/.test(e))
    .sort();
}

function recordTitleIndex(index, job) {
  if (!job || !job.id) return;
  const title = typeof job.title === "string" ? job.title.trim() : "";
  const company = typeof job.company === "string" ? job.company.trim() : "";
  if (!title && !company) return;
  const prev = index.get(job.id) || { title: "", company: "" };
  index.set(job.id, {
    title: title || prev.title,
    company: company || prev.company,
  });
}

async function loadApprovedMap(platform) {
  const map = new Map();
  try {
    const data = await fetchJson(`../${platform}/approved-jobs.json`);
    for (const job of data.jobs || []) {
      if (job.id) map.set(job.id, job);
    }
  } catch {
    /* missing ledger is valid in 1b */
  }
  return map;
}

async function loadSidecar(platform, jobId) {
  const path = `../${platform}/analyses/${encodeJobId(jobId)}-analysis.json`;
  try {
    return { ok: true, data: await fetchJson(path), error: null };
  } catch (err) {
    if (String(err.message).startsWith("404")) {
      return { ok: false, data: null, error: null };
    }
    return { ok: false, data: null, error: err.message };
  }
}

async function discoverPlatforms() {
  const entries = await listDirectory("../");
  const skip = new Set([
    "dashboard",
    "dashboard/",
    "queue",
    "queue/",
    "serve-dashboard.ps1",
    "companies.json",
  ]);
  const platforms = [];
  for (const entry of entries) {
    const name = entry.replace(/\/$/, "");
    if (skip.has(entry) || skip.has(name) || name.endsWith(".ps1") || name.endsWith(".md") || name.endsWith(".py")) {
      continue;
    }
    try {
      const srcProbe = await fetch(`../${name}/src/`, { method: "HEAD", cache: "no-store" });
      if (srcProbe.ok) platforms.push(name);
    } catch {
      /* ignore */
    }
  }
  return [...new Set(platforms)];
}

const TITLE_UNAVAILABLE = "(title unavailable)";

let state = {
  rows: [],
  titleIndex: new Map(),
  pendingAnalysis: [],
  prReady: [],
  inProgress: [],
  failed: [],
  joinFilters: new Set(),
  execFilters: new Set(),
  sourceFilter: "",
  companyFilter: "",
  catalogCompanies: [],
  platforms: [],
  selectedId: null,
  panelJobId: null,
  panelOpenByJob: {},
  runLog: null,
  runLogLength: 0,
  logPinned: true,
};

function ingestSliceRows() {
  return state.rows.filter((row) => {
    if (state.sourceFilter && row.platform !== state.sourceFilter) return false;
    if (state.companyFilter && (row.company || "") !== state.companyFilter) return false;
    return true;
  });
}

function filteredRows() {
  return ingestSliceRows().filter((row) => {
    if (state.joinFilters.size && !state.joinFilters.has(row.pipeline)) return false;
    if (state.execFilters.size && !state.execFilters.has(row.execution)) return false;
    return true;
  });
}

function toggleFilter(set, value) {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

function kebabToDisplay(slug) {
  return String(slug || "")
    .replace(/\/+$/, "")
    .split("-")
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? part : part.charAt(0).toUpperCase() + part.slice(1)))
    .join(" ")
    .trim();
}

function companyDisplay(name) {
  const raw = String(name || "").trim();
  if (!raw) return "";
  // Already human-readable (has whitespace): keep as-is.
  if (/\s/.test(raw)) return raw;
  // Slug form (kebab/snake): title-case each segment.
  return raw
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => (/^\d+$/.test(part) ? part : part.charAt(0).toUpperCase() + part.slice(1)))
    .join(" ")
    .trim();
}

function positionSlugFromLedger(job) {
  const sandbox = String((job && job.sandbox_path) || "")
    .replace(/\\/g, "/")
    .replace(/\/+$/, "");
  if (sandbox) {
    const parts = sandbox.split("/").filter(Boolean);
    if (parts.length) return parts[parts.length - 1];
  }
  const branch = String((job && job.feature_branch) || "").trim();
  if (!branch) return "";
  return branch.startsWith("feature/") ? branch.slice("feature/".length) : branch;
}

function titleFor(jobId, ledgerJob) {
  const live = state.rows.find((item) => item.id === jobId);
  const liveTitle = live && typeof live.title === "string" ? live.title.trim() : "";
  if (liveTitle) return liveTitle;
  const hist = state.titleIndex.get(jobId);
  if (hist && hist.title) return hist.title;
  const slugTitle = kebabToDisplay(positionSlugFromLedger(ledgerJob));
  return slugTitle || TITLE_UNAVAILABLE;
}

function withWidgetTitle(job) {
  return { ...job, title: titleFor(job.id, job) };
}

function optionsHtml(items, selected) {
  const opts = [`<option value="">All</option>`];
  for (const item of items) {
    const sel = item.value === selected ? " selected" : "";
    opts.push(`<option value="${escapeAttr(item.value)}"${sel}>${escapeHtml(item.label)}</option>`);
  }
  return opts.join("");
}

function renderIngestFilters() {
  const sourceSel = document.getElementById("source-filter");
  const companySel = document.getElementById("company-filter");
  if (!sourceSel || !companySel) return;

  const sources = (state.platforms && state.platforms.length
    ? state.platforms
    : [...new Set(state.rows.map((r) => r.platform).filter(Boolean))]
  )
    .slice()
    .sort((a, b) => a.localeCompare(b));
  if (state.sourceFilter && !sources.includes(state.sourceFilter)) {
    state.sourceFilter = "";
  }
  sourceSel.innerHTML = optionsHtml(
    sources.map((name) => ({ value: name, label: name })),
    state.sourceFilter
  );

  const companyValues = state.sourceFilter
    ? [
        ...new Set(
          state.rows
            .filter((r) => r.platform === state.sourceFilter)
            .map((r) => (r.company || "").trim())
            .filter(Boolean)
        ),
      ]
    : [...state.catalogCompanies];
  const companies = companyValues
    .map((value) => ({ value, label: companyDisplay(value) }))
    .sort((a, b) => a.label.localeCompare(b.label));
  if (state.companyFilter && !companies.some((c) => c.value === state.companyFilter)) {
    state.companyFilter = "";
  }
  companySel.innerHTML = optionsHtml(companies, state.companyFilter);
}

function renderJoinChips(rows) {
  const joinCounts = Object.fromEntries(JOIN_STATUSES.map((status) => [status, 0]));
  for (const row of rows) {
    if (row.pipeline in joinCounts) joinCounts[row.pipeline] += 1;
  }
  const totalActive = state.joinFilters.size === 0 ? " active" : "";
  const parts = [
    `<button type="button" class="chip ${JOIN_COUNT_CLASS.Total}${totalActive}" data-join-total="1">Total: ${rows.length}</button>`,
  ];
  for (const status of JOIN_STATUSES) {
    const active = state.joinFilters.has(status) ? " active" : "";
    const color = JOIN_COUNT_CLASS[status] || "";
    parts.push(
      `<button type="button" class="chip ${color}${active}" data-join="${escapeAttr(status)}">${escapeHtml(status)}: ${joinCounts[status]}</button>`
    );
  }
  document.getElementById("join-chips").innerHTML = parts.join("");
  document.querySelectorAll("#join-chips [data-join-total]").forEach((el) => {
    el.addEventListener("click", () => {
      state.joinFilters = new Set();
      render();
    });
  });
  document.querySelectorAll("#join-chips [data-join]").forEach((el) => {
    el.addEventListener("click", () => {
      const value = el.getAttribute("data-join");
      state.joinFilters = toggleFilter(state.joinFilters, value);
      render();
    });
  });
}

function renderExecChips(rows) {
  const execCounts = Object.fromEntries(EXEC_STATUSES.map((status) => [status, 0]));
  for (const row of rows) {
    if (row.execution in execCounts) execCounts[row.execution] += 1;
  }
  const parts = EXEC_STATUSES.map((status) => {
    const active = state.execFilters.has(status) ? " active" : "";
    return `<button type="button" class="chip${active}" data-exec="${status}">${status}: ${execCounts[status]}</button>`;
  });
  document.getElementById("exec-chips").innerHTML = parts.join("");
  document.querySelectorAll("#exec-chips [data-exec]").forEach((el) => {
    el.addEventListener("click", () => {
      const value = el.getAttribute("data-exec");
      state.execFilters = toggleFilter(state.execFilters, value);
      render();
    });
  });
}

function renderTable(rows) {
  const body = document.getElementById("jobs-body");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="12">No jobs found.</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((row) => {
      const link = row.url
        ? `<a href="${escapeAttr(row.url)}" target="_blank" rel="noopener noreferrer">Open</a>`
        : "";
      const artifacts =
        row.execution === "deployed" && row.artifacts_url
          ? `<a href="${escapeAttr(row.artifacts_url)}" target="_blank" rel="noopener noreferrer">Open</a>`
          : "";
      const selected = state.selectedId === row.id ? " selected" : "";
      return `<tr data-id="${escapeAttr(row.id)}" class="${selected}">
        <td><span class="status ${escapeAttr(row.pipeline)}">${escapeHtml(row.pipeline)}</span></td>
        <td><span class="status ${escapeAttr(row.execution)}">${escapeHtml(row.execution)}</span></td>
        <td>${escapeHtml(row.title || "")}</td>
        <td>${escapeHtml(row.company || "")}</td>
        <td>${escapeHtml(row.platform || "")}</td>
        <td>${escapeHtml(String(row.id || "").split(":").pop() || "")}</td>
        <td>${escapeHtml(row.location || "")}</td>
        <td>${escapeHtml(row.work_location_type || "")}</td>
        <td>${escapeHtml(row.pulled_at || "")}</td>
        <td>${escapeHtml(row.status_updated_at || "")}</td>
        <td>${link}</td>
        <td>${artifacts}</td>
      </tr>`;
    })
    .join("");
  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      state.selectedId = tr.getAttribute("data-id");
      render();
    });
  });
}

function selectJob(jobId) {
  if (!jobId) return;
  state.selectedId = jobId;
  render();
  const row = document.querySelector(`#jobs-body tr[data-id="${CSS.escape(jobId)}"]`);
  if (row) row.scrollIntoView({ block: "nearest" });
}

function renderRequirementItem(req) {
  const result = req.result || "";
  return `<div class="req-block">
    <div class="req-label">JD excerpt</div>
    <div>${escapeHtml(req.jd_excerpt || req.normalized || "")}</div>
    <div class="req-label">Result</div>
    <div>${result ? `<span class="status ${escapeAttr(result)}">${escapeHtml(result)}</span>` : ""}</div>
    <div class="req-label">Evidence</div>
    <div>${escapeHtml(req.evidence || "")}</div>
    <div class="req-label">Note</div>
    <div>${escapeHtml(req.note || "")}</div>
  </div>`;
}

function defaultPanelOpen(row) {
  return {
    Experience: false,
    Skills: false,
    Constraints: !!(row && row.pipeline === "rejected"),
    Run: false,
  };
}

function snapshotPanelOpen() {
  const jobId = state.panelJobId;
  if (!jobId) return;
  const el = document.getElementById("panel-body");
  if (!el) return;
  const open = {};
  let found = false;
  el.querySelectorAll("details.accordion").forEach((details) => {
    const summary = details.querySelector("summary");
    if (!summary) return;
    found = true;
    open[summary.textContent.trim()] = details.open;
  });
  if (found) state.panelOpenByJob[jobId] = open;
}

function bindPanelAccordions() {
  const el = document.getElementById("panel-body");
  if (!el) return;
  el.querySelectorAll("details.accordion").forEach((details) => {
    details.addEventListener("toggle", snapshotPanelOpen);
  });
}

function mutedDash(value) {
  if (value === null || value === undefined || value === "") {
    return `<span class="muted">—</span>`;
  }
  return escapeHtml(String(value));
}

function renderTelemetryFields(source) {
  return TELEMETRY_FIELDS.map(
    ([key, label]) =>
      `<div class="req-block"><div class="req-label">${escapeHtml(label)}</div><div>${mutedDash(source[key])}</div></div>`
  ).join("");
}

function renderRunAccordion(analysis, open) {
  const body = renderTelemetryFields(analysis || {});
  return `<details class="accordion" ${open ? "open" : ""}><summary>Run</summary>${body}</details>`;
}

function renderRequirements(title, section, open) {
  const items = (section && section.requirements) || [];
  const body = items.length
    ? items.map(renderRequirementItem).join("")
    : `<p class="req-empty">None</p>`;
  return `<details class="accordion" ${open ? "open" : ""}><summary>${escapeHtml(title)}</summary>${body}</details>`;
}

function renderPanel() {
  snapshotPanelOpen();
  const el = document.getElementById("panel-body");
  const row = state.rows.find((item) => item.id === state.selectedId);
  if (!row) {
    el.innerHTML = `<p class="muted panel-placeholder">Select a job.</p>`;
    state.panelJobId = null;
    return;
  }
  if (row.sidecarError) {
    el.innerHTML = `<p class="error">${escapeHtml(row.sidecarError)}</p>`;
    state.panelJobId = state.selectedId;
    return;
  }
  const analysis = row.analysis;
  if (!analysis || analysis.revision === 0) {
    el.innerHTML = `<div class="panel-placeholder">
      <div>Not yet analyzed</div>
      <div class="stub-note muted">Sidecar is still a pull stub (revision 0).</div>
    </div>`;
    state.panelJobId = state.selectedId;
    return;
  }
  const sources = (analysis.external_context && analysis.external_context.sources) || [];
  const sourceHtml = sources.length
    ? `<ul>${sources
        .map(
          (src) =>
            `<li><a href="${escapeAttr(src.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(src.url)}</a> <span class="muted">${escapeHtml(src.accessed_at || "")}</span></li>`
        )
        .join("")}</ul>`
    : `<p class="muted">none</p>`;
  const decision = analysis.decision || "";
  const saved = state.panelOpenByJob[state.selectedId];
  const openMap = saved ? { ...defaultPanelOpen(row), ...saved } : defaultPanelOpen(row);
  el.innerHTML = `
    <div class="decision-row"><strong>Decision</strong> <span class="status ${escapeAttr(decision)}">${escapeHtml(decision)}</span></div>
    <p><strong>Justification</strong></p>
    <p>${escapeHtml(analysis.justification || "")}</p>
    ${renderRequirements("Experience", analysis.experience, !!openMap.Experience)}
    ${renderRequirements("Skills", analysis.skills, !!openMap.Skills)}
    ${renderRequirements("Constraints", analysis.constraints, !!openMap.Constraints)}
    ${renderRunAccordion(analysis, !!openMap.Run)}
    <p><strong>Research sources</strong></p>
    ${sourceHtml}
  `;
  state.panelJobId = state.selectedId;
  bindPanelAccordions();
}

function bindWidgetClicks(body) {
  body.querySelectorAll("tr[data-id]").forEach((tr) => {
    tr.addEventListener("click", (event) => {
      if (event.target.closest("a")) return;
      selectJob(tr.getAttribute("data-id"));
    });
  });
}

function renderPendingAnalysis(rows) {
  const body = document.getElementById("pending-body");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">None</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (row) => `<tr data-id="${escapeAttr(row.job_id)}">
        <td>${escapeHtml(row.job_id)}</td>
        <td>${escapeHtml(row.run_id)}</td>
        <td>${escapeHtml(String(row.batch_number ?? ""))}</td>
        <td>${escapeHtml(row.filename)}</td>
        <td>${escapeHtml(row.skip_reason || "")}</td>
      </tr>`
    )
    .join("");
  bindWidgetClicks(body);
}

function renderPrReady(rows) {
  const body = document.getElementById("pr-ready-body");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="5" class="muted">None</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((row) => {
      const link = row.pr_url
        ? `<a href="${escapeAttr(row.pr_url)}" target="_blank" rel="noopener noreferrer">Open PR</a>`
        : "";
      const prNumber =
        row.pr_number != null && row.pr_number !== "" ? `#${escapeHtml(row.pr_number)}` : "";
      return `<tr data-id="${escapeAttr(row.id)}">
        <td>${escapeHtml(row.title || titleFor(row.id, row))}</td>
        <td>${escapeHtml(row.id)}</td>
        <td><span class="status completed">${escapeHtml(row.status)}</span></td>
        <td>${prNumber}</td>
        <td>${link}</td>
      </tr>`;
    })
    .join("");
  bindWidgetClicks(body);
}

function renderInProgress(rows) {
  const body = document.getElementById("in-progress-body");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="3" class="muted">None</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (row) => `<tr data-id="${escapeAttr(row.id)}">
        <td>${escapeHtml(row.title || titleFor(row.id, row))}</td>
        <td>${escapeHtml(row.id)}</td>
        <td><span class="status in_progress">${escapeHtml(row.status)}</span></td>
      </tr>`
    )
    .join("");
  bindWidgetClicks(body);
}

function renderFailed(rows) {
  const body = document.getElementById("failed-body");
  if (!body) return;
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="6" class="muted">None</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map((row) => {
      const failure = row.failure || {};
      return `<tr data-id="${escapeAttr(row.id)}">
        <td>${escapeHtml(row.title || titleFor(row.id, row))}</td>
        <td>${escapeHtml(row.id)}</td>
        <td>${escapeHtml(failure.code || "")}</td>
        <td>${escapeHtml(failure.step || "")}</td>
        <td>${escapeHtml(failure.message || "")}</td>
        <td>${escapeHtml(failure.failed_at || "")}</td>
      </tr>`;
    })
    .join("");
  bindWidgetClicks(body);
}

function isLogAtBottom(el) {
  return el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_PX;
}

function splitRunLog(text) {
  if (text == null) return { body: null, telemetry: null };
  const idx = text.lastIndexOf(LOG_TRAILER_DELIMITER);
  if (idx === -1) return { body: text, telemetry: null };
  const atLine = idx === 0 || text[idx - 1] === "\n";
  if (!atLine) return { body: text, telemetry: null };
  const body = text.slice(0, idx);
  const jsonPart = text.slice(idx + LOG_TRAILER_DELIMITER.length).trim();
  if (!jsonPart) return { body, telemetry: null };
  try {
    return { body, telemetry: JSON.parse(jsonPart) };
  } catch {
    return { body, telemetry: null };
  }
}

function renderLogTelemetry(telemetry) {
  const el = document.getElementById("log-telemetry");
  if (!el) return;
  if (!telemetry) {
    el.innerHTML = "";
    el.classList.add("empty");
    return;
  }
  el.classList.remove("empty");
  const rows = TELEMETRY_FIELDS.map(
    ([key, label]) => `<dt>${escapeHtml(label)}</dt><dd>${mutedDash(telemetry[key])}</dd>`
  ).join("");
  el.innerHTML = `<dl>${rows}</dl>`;
}

function renderRunLog() {
  const el = document.getElementById("log-viewport");
  if (!el) return;
  const wasPinned = state.logPinned || isLogAtBottom(el);
  const { body, telemetry } = splitRunLog(state.runLog);
  const display = body;
  const nextLength = display == null ? 0 : display.length;
  const grew = nextLength > state.runLogLength;
  if (state.runLog == null || (display === "" && !telemetry)) {
    el.textContent = "No run.log on disk.";
    el.classList.add("placeholder");
  } else if (display === "") {
    el.textContent = "";
    el.classList.remove("placeholder");
  } else {
    el.textContent = display;
    el.classList.remove("placeholder");
  }
  renderLogTelemetry(telemetry);
  if (grew && wasPinned) {
    el.scrollTop = el.scrollHeight;
    state.logPinned = true;
  } else if (!wasPinned) {
    state.logPinned = false;
  }
  state.runLogLength = nextLength;
}

function render() {
  const rail = document.querySelector(".rail");
  const railScroll = rail ? rail.scrollTop : 0;
  const visible = filteredRows();
  const ingestSlice = ingestSliceRows();
  renderIngestFilters();
  renderJoinChips(ingestSlice);
  renderExecChips(ingestSlice);
  renderTable(visible);
  renderPendingAnalysis(state.pendingAnalysis);
  renderPrReady(state.prReady);
  renderInProgress(state.inProgress);
  renderFailed(state.failed);
  renderPanel();
  renderRunLog();
  if (rail) rail.scrollTop = railScroll;
}

async function loadPendingAnalysis() {
  const entries = await listDirectory("../queue/");
  const pending = [];
  for (const entry of entries) {
    const name = entry.replace(/\/$/, "");
    if (!name.endsWith("-analysis-request.json")) continue;
    try {
      const doc = await fetchJson(`../queue/${name}`);
      for (const job of doc.jobs || []) {
        if (!job || job.status === "analysis_complete") continue;
        pending.push({
          job_id: job.id || "",
          run_id: doc.run_id || "",
          batch_number: doc.batch_number,
          filename: name,
          skip_reason: job.skip_reason || "",
        });
      }
    } catch {
      /* missing or unreadable queue file */
    }
  }
  pending.sort((a, b) => {
    const batch = (a.batch_number || 0) - (b.batch_number || 0);
    if (batch !== 0) return batch;
    return `${a.filename}|${a.job_id}`.localeCompare(`${b.filename}|${b.job_id}`);
  });
  return pending;
}

function collectByStatus(approvedMaps, status) {
  const rows = [];
  for (const map of approvedMaps) {
    for (const job of map.values()) {
      if (job && job.status === status) rows.push(job);
    }
  }
  rows.sort((a, b) => String(a.id || "").localeCompare(String(b.id || "")));
  return rows;
}

function collectPrReady(approvedMaps) {
  return collectByStatus(approvedMaps, "completed").filter((job) => job.pr_url);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/'/g, "&#39;");
}

async function loadRunLog() {
  try {
    return await fetchText(LOG_PATH);
  } catch {
    return null;
  }
}

async function loadCatalogCompanies() {
  try {
    const data = await fetchJson("../companies.json");
    return [
      ...new Set(
        (data.companies || [])
          .map((c) => (c && typeof c.name === "string" ? c.name.trim() : ""))
          .filter(Boolean)
      ),
    ];
  } catch {
    return [];
  }
}

async function main() {
  const logEl = document.getElementById("log-viewport");
  if (logEl) state.logPinned = isLogAtBottom(logEl) || state.runLogLength === 0;
  try {
    const platforms = await discoverPlatforms();
    state.platforms = platforms;
    const allRows = [];
    const approvedMaps = [];
    const titleIndex = new Map();
    state.pendingAnalysis = await loadPendingAnalysis();
    state.runLog = await loadRunLog();
    state.catalogCompanies = await loadCatalogCompanies();

    for (const platform of platforms) {
      const dates = await datedSrcDates(platform);
      if (!dates.length) continue;
      let data = null;
      for (const date of dates) {
        try {
          const dated = await fetchJson(`../${platform}/src/${date}/jobs.json`);
          for (const job of dated.jobs || []) {
            recordTitleIndex(titleIndex, job);
          }
          data = dated;
        } catch (err) {
          console.warn(err);
        }
      }
      if (!data) continue;
      const approved = await loadApprovedMap(platform);
      approvedMaps.push(approved);
      for (const job of data.jobs || []) {
        if (job.status === "closed") continue;
        const sidecarResult = await loadSidecar(platform, job.id);
        const analysis = sidecarResult.ok ? currentAnalysis(sidecarResult.data) : null;
        const queueRow = approved.get(job.id);
        const execution = executionStatus(queueRow);
        const pipeline = sidecarResult.error
          ? job.status === "new" || job.status === "active"
            ? job.status
            : "active"
          : pipelineStatus(job, analysis, queueRow);
        allRows.push({
          ...job,
          platform: data.platform || platform,
          analysis,
          sidecarError: sidecarResult.error,
          execution,
          pipeline,
          artifacts_url: (queueRow && queueRow.artifacts_url) || "",
        });
      }
    }

    allRows.sort((a, b) => {
      const left = `${a.company || ""}|${a.title || ""}|${a.id || ""}`;
      const right = `${b.company || ""}|${b.title || ""}|${b.id || ""}`;
      return left.localeCompare(right);
    });

    state.rows = allRows;
    state.titleIndex = titleIndex;
    state.prReady = collectPrReady(approvedMaps).map(withWidgetTitle);
    state.inProgress = collectByStatus(approvedMaps, "in_progress").map(withWidgetTitle);
    state.failed = collectByStatus(approvedMaps, "failed").map(withWidgetTitle);
    render();
  } catch (err) {
    const join = document.getElementById("join-chips");
    if (join) join.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    document.getElementById("jobs-body").innerHTML = `<tr><td colspan="12" class="error">${escapeHtml(err.message)}</td></tr>`;
  }
}

document.getElementById("refresh-btn").addEventListener("click", () => {
  main();
});
document.getElementById("source-filter").addEventListener("change", (event) => {
  state.sourceFilter = event.target.value;
  state.companyFilter = "";
  render();
});
document.getElementById("company-filter").addEventListener("change", (event) => {
  state.companyFilter = event.target.value;
  render();
});
document.getElementById("log-viewport").addEventListener("scroll", () => {
  const el = document.getElementById("log-viewport");
  state.logPinned = isLogAtBottom(el);
});

main();
setInterval(main, POLL_MS);
