const initialStatus = JSON.parse(document.getElementById('initial-status').textContent);
let latestStatus = initialStatus;
let refreshTimer = null;

// ── Utilities ─────────────────────────────────────────────────────────────────

function qs(selector) { return document.querySelector(selector); }
function qsa(selector) { return Array.from(document.querySelectorAll(selector)); }

function setPanel(panel) {
  qsa('.nav-link').forEach(b => b.classList.toggle('active', b.dataset.panel === panel));
  qsa('.panel').forEach(s => s.classList.toggle('active', s.id === `panel-${panel}`));
}

function showStatus(el, message, type) {
  if (!el) return;
  el.textContent = message;
  el.className = `inline-status inline-status--${type || 'info'}`;
  el.style.display = 'block';
}

function hideStatus(el) {
  if (!el) return;
  el.style.display = 'none';
  el.textContent = '';
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body || {}),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

// ── Status rendering ──────────────────────────────────────────────────────────

function safeGet(obj, ...keys) {
  return keys.reduce((acc, k) => (acc != null && typeof acc === 'object' ? acc[k] : undefined), obj);
}

function renderBadge(el, running, healthy) {
  if (!el) return;
  if (!running) {
    el.textContent = 'Stopped';
    el.className = 'badge badge-danger';
  } else if (healthy) {
    el.textContent = 'Running';
    el.className = 'badge badge-success';
  } else {
    el.textContent = 'Starting…';
    el.className = 'badge badge-warning';
  }
}

function renderChannelChips(channels) {
  const el = qs('#channel-chips');
  if (!el || !Array.isArray(channels)) return;
  const active = channels.filter(c => c.enabled);
  if (!active.length) {
    el.innerHTML = '<span class="chip chip-empty">No channels configured — go to Channels to add one</span>';
    return;
  }
  el.innerHTML = active.map(c =>
    `<span class="chip chip-active">${c.label}</span>`
  ).join('');
}

function renderProviderOverview(model) {
  const label = qs('#overview-provider-label');
  const detail = qs('#overview-provider-detail');
  if (!label || !detail) return;
  if (model && model.provider && model.default) {
    label.textContent = `${model.provider} / ${model.default}`;
    detail.textContent = 'Provider is configured. Set channel credentials to start messaging.';
  } else {
    label.textContent = 'Not configured';
    detail.textContent = 'Go to Providers to set an API key and model.';
  }
}

function renderProviderCurrentState(model) {
  const stateEl = qs('#provider-current-state');
  const badgeEl = qs('#provider-current-badge');
  if (!stateEl || !badgeEl) return;
  if (model && model.provider && model.default) {
    badgeEl.textContent = `${model.provider} · ${model.default}`;
    stateEl.style.display = 'flex';
  } else {
    stateEl.style.display = 'none';
  }
}

function renderStatus(status) {
  if (!status) return;
  latestStatus = status;

  const webui = status.webui || {};
  const dashboard = status.dashboard || {};
  const gateway = status.gateway || {};
  const model = status.model || {};
  const paths = status.paths || {};

  // Metric cards
  const wLine = qs('#webui-status-line');
  if (wLine) {
    wLine.textContent = webui.healthy
      ? `Healthy on ${webui.internal_base_url || '127.0.0.1:8788'}`
      : webui.running ? 'Starting up…' : 'Not running';
  }

  const gLine = qs('#gateway-status-line');
  if (gLine) {
    gLine.textContent = gateway.running
      ? gateway.healthy ? `Running · healthy (uptime ${gateway.uptime_seconds || 0}s)` : 'Starting…'
      : `Stopped · autostart ${status.autostart ? 'eligible' : 'not ready (needs provider + channel)'}`;
  }

  const dLine = qs('#dashboard-status-line');
  if (dLine) {
    dLine.textContent = dashboard.healthy
      ? `Healthy on ${dashboard.internal_base_url || '127.0.0.1:9119'}`
      : dashboard.running ? 'Starting up…' : 'Not running';
  }

  const pLine = qs('#paths-line');
  if (pLine) {
    pLine.textContent = [paths.hermes_home, paths.workspace_dir].filter(Boolean).join(' · ') || '—';
  }

  renderBadge(qs('#gateway-badge'), gateway.running, gateway.healthy);
  renderChannelChips(status.channels);
  renderProviderOverview(model);
  renderProviderCurrentState(model);

  // Logs
  const gLog = qs('#gateway-log-box');
  if (gLog) gLog.textContent = (gateway.log_tail || []).join('\n') || 'No gateway logs yet.';
  const wLog = qs('#webui-log-box');
  if (wLog) wLog.textContent = (webui.log_tail || []).join('\n') || 'No WebUI logs yet.';
}

// ── Channel form population ───────────────────────────────────────────────────

async function loadChannelFormValues() {
  try {
    const res = await fetch('/admin/api/channels', { headers: { Accept: 'application/json' } });
    if (!res.ok) return;
    const payload = await res.json();
    const values = payload.values || {};
    for (const [key, value] of Object.entries(values)) {
      const input = qs(`#input-${key}`);
      if (!input) continue;
      if (input.type === 'checkbox') {
        input.checked = (value || '').toLowerCase() === 'true';
      } else if (input.type === 'password') {
        const hint = qs(`#hint-${key}`);
        if (hint && !hint.dataset.static) {
          hint.textContent = value ? `Saved (${value})` : '';
        }
      } else {
        input.value = value || '';
      }
    }
  } catch (_) { /* non-fatal */ }
}

// ── Provider form wiring ──────────────────────────────────────────────────────

const PROVIDER_DEFAULTS = {};
try {
  qsa('#provider-select option').forEach(opt => {
    PROVIDER_DEFAULTS[opt.value] = opt.dataset.defaultModel || '';
  });
} catch (_) {}

function wireProviderSelect() {
  const select = qs('#provider-select');
  const modelInput = qs('#provider-model');
  const baseUrlField = qs('#base-url-field');
  if (!select) return;

  const catalog = (latestStatus.provider_catalog || []);

  function updateForProvider(id) {
    const meta = catalog.find(p => p.id === id);
    if (!meta) return;
    if (modelInput && !modelInput.value) modelInput.placeholder = meta.default_model || '';
    if (baseUrlField) baseUrlField.style.display = meta.requires_base_url ? '' : 'none';
  }

  select.addEventListener('change', () => updateForProvider(select.value));
  updateForProvider(select.value);
}

function wireProviderForm() {
  const form = qs('#provider-form');
  const statusEl = qs('#provider-form-status');
  const btn = qs('#provider-save-btn');
  if (!form) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    if (!data.api_key) {
      showStatus(statusEl, 'API key is required.', 'error');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Saving…';
    showStatus(statusEl, 'Saving provider…', 'info');
    try {
      const payload = await postJson('/admin/api/provider/setup', data);
      const r = payload.result || {};
      showStatus(statusEl, `Saved — ${r.provider} · ${r.model}`, 'success');
      form.querySelector('[name="api_key"]').value = '';
      await refreshStatus();
    } catch (err) {
      showStatus(statusEl, err.message, 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Save provider';
    }
  });
}

// ── Channel form wiring ───────────────────────────────────────────────────────

function wireChannelForms() {
  const channelForms = [
    { id: 'telegram-form', statusId: 'telegram-form-status' },
    { id: 'discord-form', statusId: 'discord-form-status' },
    { id: 'slack-form', statusId: 'slack-form-status' },
    { id: 'email-form', statusId: 'email-form-status' },
  ];

  channelForms.forEach(({ id, statusId }) => {
    const form = qs(`#${id}`);
    const statusEl = qs(`#${statusId}`);
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const raw = Object.fromEntries(new FormData(form).entries());
      // Drop blank password fields so they don't overwrite saved tokens
      const data = Object.fromEntries(
        Object.entries(raw).filter(([key, val]) => {
          const input = qs(`#input-${key}`);
          if (input && input.type === 'password' && !val) return false;
          return true;
        })
      );

      const btn = form.querySelector('[type="submit"]');
      const origText = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
      showStatus(statusEl, 'Saving…', 'info');

      try {
        const payload = await postJson('/admin/api/channels/save', data);
        const msg = payload.restarted ? 'Saved — gateway restarting.' : 'Saved.';
        showStatus(statusEl, msg, 'success');
        await loadChannelFormValues();
        await refreshStatus();
      } catch (err) {
        showStatus(statusEl, err.message, 'error');
      } finally {
        if (btn) { btn.disabled = false; btn.textContent = origText; }
      }
    });
  });
}

// ── Gateway access form ──────────────────────────────────────────────────────

function wireGatewayAccessForm() {
  const form = qs('#gateway-access-form');
  const statusEl = qs('#gateway-access-form-status');
  const checkbox = qs('#input-GATEWAY_ALLOW_ALL_USERS');
  if (!form || !checkbox) return;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = { GATEWAY_ALLOW_ALL_USERS: checkbox.checked ? 'true' : 'false' };
    const btn = form.querySelector('[type="submit"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    showStatus(statusEl, 'Saving…', 'info');
    try {
      const payload = await postJson('/admin/api/channels/save', data);
      const msg = payload.restarted ? 'Saved — gateway restarting.' : 'Saved.';
      showStatus(statusEl, msg, 'success');
      await refreshStatus();
    } catch (err) {
      showStatus(statusEl, err.message, 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Save access settings'; }
    }
  });
}

// ── Gateway controls ──────────────────────────────────────────────────────────

function wireRuntimeControls() {
  qsa('[data-gateway-action]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const orig = btn.textContent;
      btn.disabled = true;
      btn.textContent = '…';
      try {
        const payload = await postJson(`/admin/api/gateway/${btn.dataset.gatewayAction}`, {});
        if (payload.status) renderStatus(payload.status);
        else await refreshStatus();
      } catch (err) {
        alert(err.message);
      } finally {
        btn.disabled = false;
        btn.textContent = orig;
      }
    });
  });

  const restartWebuiBtn = qs('#restart-webui');
  if (restartWebuiBtn) {
    restartWebuiBtn.addEventListener('click', async () => {
      restartWebuiBtn.disabled = true;
      restartWebuiBtn.textContent = 'Restarting…';
      try {
        const payload = await postJson('/admin/api/webui/restart', {});
        if (payload.status) renderStatus(payload.status);
        else await refreshStatus();
      } catch (err) {
        alert(err.message);
      } finally {
        restartWebuiBtn.disabled = false;
        restartWebuiBtn.textContent = 'Restart WebUI';
      }
    });
  }

  const restartDashboardBtn = qs('#restart-dashboard');
  if (restartDashboardBtn) {
    restartDashboardBtn.addEventListener('click', async () => {
      restartDashboardBtn.disabled = true;
      restartDashboardBtn.textContent = 'Restarting…';
      try {
        const payload = await postJson('/admin/api/dashboard/restart', {});
        if (payload.status) renderStatus(payload.status);
        else await refreshStatus();
      } catch (err) {
        alert(err.message);
      } finally {
        restartDashboardBtn.disabled = false;
        restartDashboardBtn.textContent = 'Restart Dashboard';
      }
    });
  }

  const refreshBtn = qs('#refresh-status');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      refreshBtn.disabled = true;
      try { await refreshStatus(); } catch (_) {}
      finally { refreshBtn.disabled = false; }
    });
  }
}

// ── Navigation ────────────────────────────────────────────────────────────────

function wireNavigation() {
  qsa('.nav-link').forEach(btn => {
    btn.addEventListener('click', () => setPanel(btn.dataset.panel));
  });
  qsa('[data-panel-link]').forEach(btn => {
    btn.addEventListener('click', () => setPanel(btn.dataset.panelLink));
  });
}

// ── Polling ───────────────────────────────────────────────────────────────────

async function refreshStatus() {
  const res = await fetch('/admin/api/status', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`Status refresh failed (${res.status})`);
  const payload = await res.json();
  renderStatus(payload);
}

function startPolling() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => refreshStatus().catch(() => {}), 5000);
}

// ── Pairing / Users ──────────────────────────────────────────────────────────

function formatDate(ts) {
  if (!ts) return '—';
  return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

async function loadPairing() {
  try {
    const [pendingRes, approvedRes] = await Promise.all([
      fetch('/admin/api/pairing/pending', { headers: { Accept: 'application/json' } }),
      fetch('/admin/api/pairing/approved', { headers: { Accept: 'application/json' } }),
    ]);
    if (pendingRes.ok) renderPending((await pendingRes.json()).pending || []);
    if (approvedRes.ok) renderApproved((await approvedRes.json()).approved || []);
  } catch (_) { /* non-fatal */ }
}

function renderPending(items) {
  const empty = qs('#pending-empty');
  const table = qs('#pending-table');
  const tbody = qs('#pending-tbody');
  const badge = qs('#pending-count');
  if (!tbody) return;

  if (badge) {
    if (items.length > 0) {
      badge.textContent = items.length;
      badge.style.display = '';
    } else {
      badge.style.display = 'none';
    }
  }

  if (items.length === 0) {
    if (empty) empty.style.display = '';
    if (table) table.style.display = 'none';
    return;
  }
  if (empty) empty.style.display = 'none';
  if (table) table.style.display = '';

  tbody.innerHTML = items.map(req => `
    <tr>
      <td class="platform">${esc(req.platform)}</td>
      <td>${esc(req.user_name || '—')}</td>
      <td class="mono">${esc(req.user_id)}</td>
      <td>${req.age_minutes}m ago</td>
      <td>
        <div class="action-row">
          <button class="btn-approve" onclick="approveUser('${esc(req.platform)}', '${esc(req.code)}')">Approve</button>
          <button class="btn-deny" onclick="denyUser('${esc(req.platform)}', '${esc(req.code)}')">Deny</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function renderApproved(items) {
  const empty = qs('#approved-empty');
  const table = qs('#approved-table');
  const tbody = qs('#approved-tbody');
  if (!tbody) return;

  if (items.length === 0) {
    if (empty) empty.style.display = '';
    if (table) table.style.display = 'none';
    return;
  }
  if (empty) empty.style.display = 'none';
  if (table) table.style.display = '';

  tbody.innerHTML = items.map(user => `
    <tr>
      <td class="platform">${esc(user.platform)}</td>
      <td>${esc(user.user_name || '—')}</td>
      <td class="mono">${esc(user.user_id)}</td>
      <td>${formatDate(user.approved_at)}</td>
      <td>
        <div class="action-row">
          <button class="btn-revoke" onclick="revokeUser('${esc(user.platform)}', '${esc(user.user_id)}')">Revoke</button>
        </div>
      </td>
    </tr>
  `).join('');
}

function esc(str) {
  const d = document.createElement('div');
  d.textContent = str || '';
  return d.innerHTML;
}

async function approveUser(platform, code) {
  try {
    await postJson('/admin/api/pairing/approve', { platform, code });
    await loadPairing();
  } catch (err) { alert(err.message); }
}

async function denyUser(platform, code) {
  try {
    await postJson('/admin/api/pairing/deny', { platform, code });
    await loadPairing();
  } catch (err) { alert(err.message); }
}

async function revokeUser(platform, userId) {
  if (!confirm('Revoke access for this user?')) return;
  try {
    await postJson('/admin/api/pairing/revoke', { platform, user_id: userId });
    await loadPairing();
  } catch (err) { alert(err.message); }
}

function wirePairing() {
  const refreshBtn = qs('#refresh-pairing');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => loadPairing());
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

wireNavigation();
wireRuntimeControls();
wireProviderSelect();
wireProviderForm();
wireChannelForms();
wireGatewayAccessForm();
wirePairing();
renderStatus(initialStatus);
loadChannelFormValues();
startPolling();
loadPairing();
setInterval(() => loadPairing(), 5000);
