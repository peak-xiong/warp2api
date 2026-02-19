function log(msg, obj) {
  const el = document.getElementById("console");
  const line = obj ? `${msg}\n${JSON.stringify(obj, null, 2)}` : msg;
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
  return `<span class="chip ${s}">${s || "-"}</span>`;
}

function fmt(ts) {
  if (!ts) return "-";
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
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
    tr.innerHTML = `
      <td>${t.id}</td>
      <td>${t.label || ""}</td>
      <td>${t.token_preview || ""}</td>
      <td>${statusChip(t.status)}</td>
      <td>${t.last_error_code || "-"}</td>
      <td>${fmt(t.cooldown_until)}</td>
      <td>${fmt(t.last_success_at)}</td>
      <td>
        <div class="row-actions">
          <button data-act="refresh" data-id="${t.id}">Refresh</button>
          <button class="secondary" data-act="toggle" data-id="${t.id}" data-status="${t.status || ""}">
            ${(t.status || "") === "disabled" ? "Enable" : "Disable"}
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(tr);
  }

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
  const tokens = text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
  const body = await api("/admin/api/tokens/batch-import", {
    method: "POST",
    body: JSON.stringify({ tokens }),
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

refreshAll().catch(e => log(`init error: ${String(e)}`));
