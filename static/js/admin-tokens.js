const selectedTokenIds = new Set();

function syncDeleteSelectedButton() {
  const btn = document.getElementById("btnDeleteSelected");
  if (!btn) return;
  const n = selectedTokenIds.size;
  btn.textContent = n > 0 ? `删除选中(${n})` : "删除选中";
}

function applyRowSelectedState(rowEl, checked) {
  if (!rowEl) return;
  if (checked) rowEl.classList.add("is-selected");
  else rowEl.classList.remove("is-selected");
}

function safePreview(value, head = 8, tail = 6) {
  const s = String(value || "");
  if (!s) return "";
  if (s.length <= head + tail + 3) return s;
  return `${s.slice(0, head)}...${s.slice(-tail)}`;
}

function sanitizeForLog(input, depth = 0) {
  if (input == null) return input;
  if (depth > 4) return "[truncated]";
  if (typeof input === "string") {
    if (input.length > 240) return `${input.slice(0, 240)}...[truncated:${input.length}]`;
    return input;
  }
  if (Array.isArray(input)) return input.map(v => sanitizeForLog(v, depth + 1));
  if (typeof input === "object") {
    const out = {};
    for (const [k, v] of Object.entries(input)) {
      const key = k.toLowerCase();
      if (key.includes("refresh_token") || key.includes("id_token") || key === "api_key" || key === "warp_refresh_token") {
        out[k] = safePreview(v, 10, 8);
        continue;
      }
      out[k] = sanitizeForLog(v, depth + 1);
    }
    return out;
  }
  return input;
}

function summarizeTokenSnapshot(t) {
  if (!t || typeof t !== "object") return null;
  const quotaLimit = t.quota_limit ?? t.total_limit;
  const quotaUsed = t.quota_used ?? t.used_limit;
  const quotaRemain = t.quota_remaining != null
    ? t.quota_remaining
    : (quotaLimit != null && quotaUsed != null ? Math.max(0, Number(quotaLimit) - Number(quotaUsed)) : null);
  const routable = accountRoutableState(t);
  const reason = cellValue(t.last_error_message || t.health_last_error || "");
  return {
    id: t.id,
    status: cellValue(t.status),
    routable: routable.ok,
    routable_reason: routable.reason,
    quota: {
      used: quotaUsed ?? null,
      limit: quotaLimit ?? null,
      remaining: quotaRemain ?? null,
      next_refresh_time: t.quota_next_refresh_time || "",
      refresh_duration: t.quota_refresh_duration || "",
    },
    health: {
      healthy: t.healthy,
      latency_ms: t.health_latency_ms ?? null,
      consecutive_failures: t.health_consecutive_failures ?? 0,
    },
    last_error: {
      code: cellValue(t.last_error_code),
      message: reason === "-" ? "" : reason,
    },
    last_check_at: t.last_check_at || t.health_last_checked_at || "",
    last_success_at: t.last_success_at || t.health_last_success_at || "",
  };
}

function summarizeLogPayload(obj) {
  if (!obj || typeof obj !== "object") return obj;
  if (obj.token && typeof obj.token === "object") {
    return {
      success: !!obj.success,
      token: summarizeTokenSnapshot(obj.token),
    };
  }
  if (Array.isArray(obj.data)) {
    return {
      count: obj.data.length,
      sample: obj.data.slice(0, 3).map((x) => summarizeTokenSnapshot(x)).filter(Boolean),
    };
  }
  if (obj.data && obj.data.token) {
    return {
      success: !!obj.success,
      data: {
        success: !!obj.data.success,
        token: summarizeTokenSnapshot(obj.data.token),
      },
    };
  }
  return obj;
}

function log(msg, obj) {
  const el = document.getElementById("console");
  const payload = obj ? summarizeLogPayload(obj) : null;
  const line = payload ? `${msg}\n${JSON.stringify(sanitizeForLog(payload), null, 2)}` : msg;
  el.textContent = line;
}

async function api(path, options = {}) {
  const token = document.getElementById("adminToken").value.trim();
  const headers = Object.assign({}, options.headers || {}, { "Content-Type": "application/json" });
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(path, Object.assign({}, options, { headers }));
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function statusChip(status) {
  const s = (status || "").trim();
  const tagMap = {
    active: "A",
    cooldown: "C",
    blocked: "B",
    quota_exhausted: "Q",
    disabled: "D",
  };
  const tag = tagMap[s] || "?";
  return `<span class="chip ${s}">${tag} · ${s || "-"}</span>`;
}

function statusUnifiedChip(t) {
  const s = (t.status || "").trim();
  const tagMap = {
    active: "A",
    cooldown: "C",
    blocked: "B",
    quota_exhausted: "Q",
    disabled: "D",
  };
  const tag = tagMap[s] || "?";
  const route = accountRoutableState(t).ok ? "yes" : "no";
  return `<span class="chip ${s}">${tag} · ${s || "-"} · ${route}</span>`;
}

function shortText(v, n = 42) {
  const s = cellValue(v);
  if (s === "-") return s;
  return s.length > n ? `${s.slice(0, n)}...` : s;
}

function fmt(ts) {
  if (!ts) return "-";
  try {
    if (typeof ts === "number") {
      const ms = ts < 1e12 ? ts * 1000 : ts;
      return new Date(ms).toLocaleString();
    }
    if (typeof ts === "string" && /^\d+(\.\d+)?$/.test(ts)) {
      const n = Number(ts);
      const ms = n < 1e12 ? n * 1000 : n;
      return new Date(ms).toLocaleString();
    }
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function fmtQuota(used, limit) {
  if (used == null && limit == null) return "-";
  if (used == null) return `-/ ${limit}`;
  if (limit == null) return `${used} / -`;
  return `${used} / ${limit}`;
}

function fmtQuotaCompact(t) {
  const used = t.quota_used ?? t.used_limit;
  const limit = t.quota_limit ?? t.total_limit;
  const remain = t.quota_remaining != null
    ? Number(t.quota_remaining)
    : (limit != null && used != null ? Math.max(0, Number(limit) - Number(used)) : null);
  const next = t.quota_next_refresh_time ? fmt(t.quota_next_refresh_time) : "-";
  const duration = cellValue(t.quota_refresh_duration);
  if (used == null && limit == null) return `<div class="cell-stack"><div>-</div><div class="muted">next: -</div></div>`;
  if (t.quota_is_unlimited === true || Number(limit) < 0) {
    return `<div class="cell-stack"><div>unlimited</div><div class="muted">next: ${next}</div></div>`;
  }
  const head = `${numberCell(used)} / ${numberCell(limit)}`;
  const sub = `remain ${numberCell(remain)} · ${duration}`;
  return `<div class="cell-stack"><div>${head}</div><div class="muted">${sub}</div><div class="muted">next: ${next}</div></div>`;
}

function compactText(v, head = 10, tail = 6) {
  const s = String(v || "").trim();
  if (!s) return "-";
  if (s.length <= head + tail + 3) return s;
  return `${s.slice(0, head)}...${s.slice(-tail)}`;
}

function isEmptyValue(v) {
  if (v == null) return true;
  if (typeof v === "string") {
    const s = v.trim().toLowerCase();
    return s === "" || s === "null" || s === "undefined";
  }
  return false;
}

function cellValue(v) {
  return isEmptyValue(v) ? "-" : String(v);
}

function numberCell(v) {
  if (v == null) return "-";
  const n = Number(v);
  return Number.isFinite(n) ? String(n) : "-";
}

function accountRoutableState(t) {
  const hasRefresh = Boolean(String(t.warp_refresh_token || "").trim());
  const hasIdToken = Boolean(String(t.id_token || "").trim());
  const hasApiKey = Boolean(String(t.api_key || "").trim());
  const isActive = (t.status || "") === "active";
  const healthy = t.healthy !== false;
  const quotaKnown = t.total_limit != null && t.used_limit != null;
  const remaining = quotaKnown ? Math.max(0, Number(t.total_limit) - Number(t.used_limit)) : null;
  const quotaOk = remaining == null || remaining > 0;
  const ok = hasRefresh && isActive && healthy && quotaOk && (hasIdToken || hasApiKey);
  if (ok) return { ok: true, reason: "ready" };
  const reason =
    !hasRefresh ? "no_refresh" :
    !isActive ? "inactive" :
    !healthy ? "unhealthy" :
    !quotaOk ? "quota_0" :
    "no_id_api";
  return { ok: false, reason };
}

function routableChip(t) {
  const s = accountRoutableState(t);
  if (s.ok) return `<span class="chip ready">yes</span>`;
  return `<span class="chip unready" title="${s.reason}">no</span>`;
}

async function loadReadiness() {
  const body = await api("/admin/api/tokens/readiness");
  const d = body.data || {};
  document.getElementById("cTotal").textContent = d.total_tokens ?? 0;
  document.getElementById("cAvail").textContent = d.available_tokens ?? 0;
  document.getElementById("cCooldown").textContent = d.cooldown_tokens ?? 0;
  document.getElementById("cBlocked").textContent = d.blocked_tokens ?? 0;
  document.getElementById("cQuota").textContent = d.quota_exhausted_tokens ?? 0;
  document.getElementById("cReady").textContent = d.ready ? "yes" : "no";
  return d;
}

async function loadTokens() {
  const body = await api("/admin/api/tokens");
  const rows = body.data || [];
  const tbody = document.getElementById("tokenRows");
  tbody.innerHTML = "";

  for (const t of rows) {
    const tr = document.createElement("tr");
    tr.setAttribute("data-row-id", String(t.id));
    const checked = selectedTokenIds.has(Number(t.id)) ? "checked" : "";
    tr.innerHTML = `
      <td><input type="checkbox" data-act="select" data-id="${t.id}" ${checked}></td>
      <td class="cell-center">${numberCell(t.id)}</td>
      <td title="${cellValue(t.email)}">
        <div class="cell-stack">
          <div>${cellValue(t.email)}</div>
          <div class="mono muted" title="${cellValue(t.api_key)}">api: ${compactText(t.api_key, 10, 6)}</div>
          <div class="mono muted" title="${cellValue(t.id_token)}">id: ${compactText(t.id_token, 10, 6)}</div>
        </div>
      </td>
      <td class="cell-mono" title="${cellValue(t.warp_refresh_token)}">${compactText(t.warp_refresh_token, 14, 10)}</td>
      <td>${fmtQuotaCompact(t)}</td>
      <td class="col-status">${statusUnifiedChip(t)}</td>
      <td class="cell-center">${numberCell(t.use_count ?? 0)}</td>
      <td>
        <div class="cell-stack">
          <div>${t.healthy == null ? "-" : (t.healthy ? "healthy" : "unhealthy")}</div>
          <div class="muted">fail ${numberCell(t.health_consecutive_failures ?? 0)} · ${numberCell(t.health_latency_ms)} ms</div>
        </div>
      </td>
      <td>
        <div class="cell-stack">
          <div title="${fmt(t.last_check_at || t.health_last_checked_at)}">check: ${fmt(t.last_check_at || t.health_last_checked_at)}</div>
          <div class="muted" title="${fmt(t.last_success_at || t.health_last_success_at)}">success: ${fmt(t.last_success_at || t.health_last_success_at)}</div>
        </div>
      </td>
      <td title="${fmt(t.cooldown_until)}" class="cell-center">${fmt(t.cooldown_until)}</td>
      <td title="${cellValue(t.last_error_message) || cellValue(t.health_last_error)}">
        <div class="cell-stack">
          <div>${cellValue(t.last_error_code)}</div>
          <div class="muted">${shortText(t.last_error_message || t.health_last_error || "-", 56)}</div>
        </div>
      </td>
      <td class="action-col col-actions">
        <div class="row-actions">
          <button data-act="refresh" data-id="${t.id}">Refresh</button>
          <button class="secondary" data-act="toggle" data-id="${t.id}" data-status="${t.status || ""}">
            ${(t.status || "") === "disabled" ? "Enable" : "Disable"}
          </button>
          <button class="secondary" data-act="delete" data-id="${t.id}">Delete</button>
        </div>
      </td>
    `;
    applyRowSelectedState(tr, selectedTokenIds.has(Number(t.id)));
    tbody.appendChild(tr);
  }

  const chkAll = document.getElementById("chkAll");
  if (chkAll) chkAll.checked = rows.length > 0 && rows.every(r => selectedTokenIds.has(Number(r.id)));
  syncDeleteSelectedButton();

  tbody.querySelectorAll("input[data-act='select']").forEach(chk => {
    chk.addEventListener("change", () => {
      const id = Number(chk.getAttribute("data-id"));
      if (chk.checked) selectedTokenIds.add(id);
      else selectedTokenIds.delete(id);
      applyRowSelectedState(chk.closest("tr"), chk.checked);
      const all = document.getElementById("chkAll");
      if (all) all.checked = rows.length > 0 && rows.every(r => selectedTokenIds.has(Number(r.id)));
      syncDeleteSelectedButton();
    });
  });

  tbody.querySelectorAll("tr[data-row-id]").forEach(tr => {
    tr.addEventListener("click", (ev) => {
      const target = ev.target;
      if (!(target instanceof HTMLElement)) return;
      if (target.closest("button") || target.closest("a") || target.closest("input") || target.closest("textarea") || target.closest("select") || target.closest("label")) {
        return;
      }
      const chk = tr.querySelector("input[data-act='select']");
      if (!(chk instanceof HTMLInputElement)) return;
      chk.checked = !chk.checked;
      chk.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  tbody.querySelectorAll("button[data-act='refresh']").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      try {
        const resp = await api(`/admin/api/tokens/${id}/refresh`, { method: "POST" });
        log(`refresh token ${id} done`, resp.data);
        await refreshAll();
      } catch (e) {
        log(`refresh token ${id} failed: ${String(e)}`);
      }
    });
  });

  tbody.querySelectorAll("button[data-act='toggle']").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      const status = btn.getAttribute("data-status");
      const target = status === "disabled" ? "active" : "disabled";
      try {
        const resp = await api(`/admin/api/tokens/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: target }),
        });
        log(`token ${id} -> ${target}`, resp.data);
        await refreshAll();
      } catch (e) {
        log(`update token ${id} failed: ${String(e)}`);
      }
    });
  });

  tbody.querySelectorAll("button[data-act='delete']").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-id");
      if (!window.confirm(`Delete token #${id}?`)) return;
      try {
        const resp = await api(`/admin/api/tokens/${id}`, { method: "DELETE" });
        selectedTokenIds.delete(Number(id));
        syncDeleteSelectedButton();
        log(`delete token ${id} done`, resp.data);
        await refreshAll();
      } catch (e) {
        log(`delete token ${id} failed: ${String(e)}`);
      }
    });
  });
}

async function deleteSelected() {
  const ids = Array.from(selectedTokenIds.values()).filter(v => Number.isFinite(v));
  if (ids.length === 0) {
    log("error: no selected tokens");
    return;
  }
  if (!window.confirm(`Delete ${ids.length} selected token(s)?`)) return;
  const body = await api("/admin/api/tokens/batch-delete", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
  selectedTokenIds.clear();
  syncDeleteSelectedButton();
  log("batch delete", body.data || {});
  await refreshAll();
}

async function loadStats() {
  const body = await api("/admin/api/tokens/statistics");
  log("statistics", body.data || {});
}

async function loadHealth() {
  const body = await api("/admin/api/tokens/health");
  log("health", body.data || {});
}

async function importBatch() {
  const text = document.getElementById("batchTokens").value || "";
  const trimmed = text.trim();
  let payload;
  if ((trimmed.startsWith("[") && trimmed.endsWith("]")) || (trimmed.startsWith("{") && trimmed.endsWith("}"))) {
    const parsed = JSON.parse(trimmed);
    const accounts = Array.isArray(parsed) ? parsed : (Array.isArray(parsed.accounts) ? parsed.accounts : []);
    payload = { accounts };
  } else {
    const tokens = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
    payload = { tokens };
  }
  const body = await api("/admin/api/tokens/batch-import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  log("batch import", body.data || {});
  await refreshAll();
}

async function refreshAll() {
  await loadReadiness();
  await loadTokens();
}

document.getElementById("btnLoad").addEventListener("click", async () => {
  try { await refreshAll(); log("list refreshed"); } catch (e) { log(`error: ${String(e)}`); }
});

document.getElementById("btnStats").addEventListener("click", async () => {
  try { await loadReadiness(); await loadStats(); } catch (e) { log(`error: ${String(e)}`); }
});

document.getElementById("btnHealth").addEventListener("click", async () => {
  try { await loadReadiness(); await loadHealth(); } catch (e) { log(`error: ${String(e)}`); }
});

document.getElementById("btnImport").addEventListener("click", async () => {
  try { await importBatch(); } catch (e) { log(`error: ${String(e)}`); }
});

document.getElementById("btnRefreshAll").addEventListener("click", async () => {
  try {
    const body = await api("/admin/api/tokens/refresh-all", { method: "POST" });
    log("refresh all", body.data || {});
    await refreshAll();
  } catch (e) {
    log(`error: ${String(e)}`);
  }
});

document.getElementById("btnDeleteSelected").addEventListener("click", async () => {
  try {
    await deleteSelected();
  } catch (e) {
    log(`error: ${String(e)}`);
  }
});

document.getElementById("chkAll").addEventListener("change", (ev) => {
  const checked = Boolean(ev.target.checked);
  document.querySelectorAll("#tokenRows input[data-act='select']").forEach(chk => {
    chk.checked = checked;
    const id = Number(chk.getAttribute("data-id"));
    if (checked) selectedTokenIds.add(id);
    else selectedTokenIds.delete(id);
  });
  syncDeleteSelectedButton();
});

refreshAll().catch(e => log(`init error: ${String(e)}`));
