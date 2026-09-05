/* =============================================================================
   MediaManager 2026 — admin.js
   Dashboard, Logs, API, thème, version, mise à jour
   ============================================================================= */

const API = `http://${window.location.hostname}:8000`;

/* ── Onglets ──────────────────────────────────────────────────────────────── */
let activeTab  = 'dashboard';
let logTimer   = null;
let dashTimer  = null;
let versionTimer = null;

function switchTab(name, opts) {
  if (name === activeTab && !opts) return;
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-tab]').forEach(b => b.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.querySelector(`.nav-item[data-tab="${name}"]`)?.classList.add('active');
  clearTimeout(logTimer);
  clearTimeout(dashTimer);
  activeTab = name;
  if (name === 'dashboard') startDashboard();
  else if (name === 'stats') Stats.load();
  else if (name === 'logs')  startLogs();
  else if (name === 'config') Config.load();
  else if (name === 'perf')  Perf.load();
  else if (name === 'users')   Users.load();
  else if (name === 'library') {
    if (opts && opts.status) Library.loadWithStatus(opts.status);
    else Library.load();
  }
}

// Depuis le Dashboard : ouvre la Bibliothèque filtrée sur un statut disque (missing/duplicate)
function goToLibraryStatus(status) {
  switchTab('library', { status });
}

/* ── Thème ────────────────────────────────────────────────────────────────── */
function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('mm-theme', theme);
  document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`theme-btn-${theme}`)?.classList.add('active');
}

/* ── Dashboard ────────────────────────────────────────────────────────────── */
function startDashboard() {
  loadDashboard();
  checkVersion();
}

async function loadDashboard() {
  if (activeTab !== 'dashboard') return;
  try {
    const r = await fetch(`${API}/api/admin/dashboard`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();

    // Header système
    setText('sys-host', d.system?.host ?? '—');
    setText('sys-ip',   d.system?.ip   ?? '—');
 
    // Cartes statut
    renderDashCards(d);

    // Stats
    updateDashStats(d);

  } catch (e) {
    showDashMsg('error', e.message);
  }
  dashTimer = setTimeout(loadDashboard, 5000);
}

// Retourne un badge coloré selon des seuils.
// thresholds = [{v, c}] ordonnés du meilleur au pire.
// lowerIsBetter : compare val < t.v (sinon val >= t.v).
function _pgStat(val, suffix, thresholds, lowerIsBetter = false) {
  if (val == null) return '<span class="card-value text-muted">—</span>';
  let cls = thresholds[thresholds.length - 1].c;
  for (const t of thresholds.slice(0, -1)) {
    if (lowerIsBetter ? val < t.v : val >= t.v) { cls = t.c; break; }
  }
  return `<span class="badge ${cls}">${val}${suffix}</span>`;
}

function renderDashCards(d) {
  const watcher = d.services?.watcher   ?? {};
  const db      = d.services?.database  ?? {};
  const mounts  = d.services?.mounts    ?? {};

  const isRunning = (watcher.status || '').toLowerCase() === 'running';
  const isConn    = (db.status || '').toLowerCase() === 'connected';

  document.getElementById('dash-grid').innerHTML = `
    <!-- Système -->
    <div class="card">
      <div class="card-header"><i class="bi bi-pc-display-horizontal"></i> Système hôte</div>
      <div class="card-row"><span class="card-label">Démarré le</span>
        <span class="card-value text-sm">${d.system?.start_time ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">IP</span>
        <span class="card-value text-blue">${d.system?.ip ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">Host</span>
        <span class="card-value">${d.system?.host ?? '—'}</span></div>
    </div>
 
    <!-- Watcher -->
    <div class="card">
      <div class="card-header"><i class="bi bi-cpu"></i> Watcher Service</div>
      <div class="card-row"><span class="card-label">Statut</span>
        <span class="badge ${isRunning ? 'badge-success' : 'badge-danger'}">
          <span class="dot"></span>${isRunning ? 'Running' : 'Stopped'}
        </span></div>
      <div class="card-row"><span class="card-label">Uptime</span>
        <span class="badge badge-info"><span class="dot"></span>${watcher.uptime ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">PID</span>
        <span class="card-value">${watcher.pid ?? '—'}</span></div>
      <div class="card-actions">
        <button class="btn btn-sm" onclick="svcAction('watcher','restart')">
          <i class="bi bi-arrow-clockwise"></i> Restart
        </button>
        <button class="btn btn-sm btn-danger" onclick="svcAction('watcher','stop')">
          <i class="bi bi-stop-fill"></i> Stop
        </button>
      </div>
    </div>
 
    <!-- PostgreSQL -->
    <div class="card">
      <div class="card-header"><i class="bi bi-database"></i> ${db.type ?? 'PostgreSQL'}</div>
      <div class="card-row"><span class="card-label">Statut</span>
        <span class="badge ${isConn ? 'badge-success' : 'badge-danger'}">
          <span class="dot"></span>${isConn ? 'Connected' : 'Disconnected'}
        </span></div>
      <div class="card-row"><span class="card-label">Base</span>
        <span class="card-value text-blue">${db.database ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">Taille</span>
        <span class="card-value">${db.size ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">Connexions</span>
        <span class="card-value">${db.connections ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">Cache hit</span>
        ${_pgStat(db.cache_hit, '%', [{v:95,c:'badge-success'},{v:80,c:'badge-warn'},{v:0,c:'badge-danger'}])}</div>
      <div class="card-row"><span class="card-label">Deadlocks</span>
        ${_pgStat(db.deadlocks, '', [{v:1,c:'badge-success'},{v:0,c:'badge-danger'}], true)}</div>
      <div class="card-row"><span class="card-label">Bloat</span>
        ${_pgStat(db.bloat_pct, '%', [{v:5,c:'badge-success'},{v:10,c:'badge-warn'},{v:Infinity,c:'badge-danger'}], true)}</div>
    </div>
  `;
}

async function updateDashStats(d) {
  // ── Fichiers — appel API dédié ──────────────────────────────────────────
  try {
    const r = await fetch(`${API}/api/admin/files/stats`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const f = await r.json();

    const fanalyzed   = f.analyzed   ?? 0;
    const fdiscovered = f.discovered ?? 0;
    const fanalyzing  = f.analyzing  ?? 0;
    const ferror      = f.error      ?? 0;
    const ftotal      = f.total      ?? 0;
    const fpending    = fdiscovered + fanalyzing;

    const pct = ftotal > 0 ? Math.round(fanalyzed / ftotal * 100) : 0;
    setText('lib-label',    `${ftotal.toLocaleString('fr-FR')} fichier${ftotal > 1 ? 's' : ''} indexé${ftotal > 1 ? 's' : ''}`);
    setText('lib-pct',      ftotal > 0 ? `${pct}%` : '—');
    setText('lib-analyzed', fanalyzed.toLocaleString('fr-FR'));
    setText('lib-pending',  fpending.toLocaleString('fr-FR'));
    setText('lib-error',    ferror.toLocaleString('fr-FR'));

    const bar  = document.getElementById('lib-bar');
    if (bar) {
      bar.style.width = (ftotal > 0 ? pct : 0) + '%';
      bar.style.background = pct === 100 ? 'var(--green)' : fpending > 0 ? 'var(--blue)' : 'var(--green)';
    }

    const catCounts = {};
    for (const c of (f.by_category ?? [])) catCounts[c.name] = c.count;
    if (typeof Mounts !== 'undefined') Mounts.updateCategoryCounts(catCounts);
  } catch (e) {
    console.warn('files/stats:', e.message);
  }

  // ── Bibliothèque — taille + manquants/doublons (depuis dashboard) ─────────
  const lib = d.library ?? {};
  const tb  = lib.total_tb ?? 0;
  setText('lib-size', tb >= 1 ? `${tb} To` : `${Math.round(tb * 1024)} Go`);

  const trashBytes = lib.trash_bytes ?? 0;
  const trashBadge = document.getElementById('lib-trash-badge');
  if (trashBadge) {
    trashBadge.classList.toggle('lib-alert-hidden', trashBytes <= 0);
    setText('lib-trash-size', fmtBytes(trashBytes));
  }

  const missing   = lib.missing_files   ?? 0;
  const duplicate = lib.duplicate_files ?? 0;
  setText('lib-missing',   missing.toLocaleString('fr-FR'));
  setText('lib-duplicate', duplicate.toLocaleString('fr-FR'));
  const missBlock = document.getElementById('lib-missing-block');
  const dupBlock  = document.getElementById('lib-duplicate-block');
  if (missBlock) missBlock.classList.toggle('lib-alert-hidden', missing === 0);
  if (dupBlock)  dupBlock.classList.toggle('lib-alert-hidden',  duplicate === 0);

  loadPipeline();
}

async function svcAction(svc, action) {
  if (!confirm(`${action === 'restart' ? 'Redémarrer' : 'Arrêter'} le service ${svc} ?`)) return;
  try {
    const r = await fetch(`${API}/api/admin/services/${svc}/${action}`, { method: 'POST' });
    const d = await r.json();
    showDashMsg(d.status === 'success' ? 'ok' : 'error', d.message || d.error);
    setTimeout(loadDashboard, 2000);
  } catch (e) {
    showDashMsg('error', e.message);
  }
}

function showDashMsg(type, msg) {
  const el = document.getElementById('dash-msg');
  const cls = type === 'ok' ? 'badge-success' : 'badge-danger';
  el.innerHTML = `<span class="badge ${cls} mt-8">${escHtml(msg)}</span>`;
  setTimeout(() => { el.innerHTML = ''; }, 5000);
}


/* ── Système header ───────────────────────────────────────────────────────── */
async function refreshHeader() {
  try {
    const r = await fetch(`${API}/api/admin/dashboard`);
    const d = await r.json();
    setText('sys-host', d.system?.host ?? '—');
        
    setVersion(d.version, d.latest_version, d.build, d.update_available?.prerelease);
  } catch (_) {}
}

/* ── Version ──────────────────────────────────────────────────────────────── */
async function checkVersion() {
  try {
    const r = await fetch(`${API}/api/admin/dashboard`);
    const d = await r.json();
    setVersion(d.version, d.latest_version, d.build, d.update_available?.prerelease);
  } catch (_) {}
  clearTimeout(versionTimer);
  versionTimer = setTimeout(checkVersion, 30 * 60 * 1000);
}

async function forceVersionCheck() {
  const badge = document.getElementById('app-version');
  const orig  = badge.textContent;
  badge.textContent = '…';
  badge.classList.add('opacity-50');
  try {
    // 1. Vider le cache serveur
    await fetch(`${API}/api/admin/version/check`);
    // 2. Relire le dashboard avec la version fraiche
    const r = await fetch(`${API}/api/admin/dashboard`);
    const d = await r.json();
    setVersion(d.version, d.latest_version, d.build, d.update_available?.prerelease);
    // 3. Réarmer le timer 30min depuis maintenant
    clearTimeout(versionTimer);
    versionTimer = setTimeout(checkVersion, 30 * 60 * 1000);
  } catch (_) {
    badge.textContent = orig;
  } finally {
    badge.classList.remove('opacity-50');
  }
}

function setVersion(current, latest, build, isPrerelease) {
  // Afficher version + hash court : "0.3.2-dev (a1b2c3)"
  const display = build && build !== 'unknown'
    ? `${current ?? '—'} (${build})`
    : (current ?? '—');
  setText('app-version', display);

  const badge = document.getElementById('update-badge');
  if (latest && latest !== current) {
    const label = isPrerelease ? `${latest} (dev)` : latest;
    setText('update-label', label);
    badge.title = isPrerelease
      ? `Pre-release : ${latest} — version de développement`
      : `Nouvelle version stable : ${latest}`;
    badge.classList.toggle('badge-prerelease', !!isPrerelease);
    badge.classList.add('visible');
  } else {
    badge.classList.remove('visible');
  }
}

/* ── Mise à jour ──────────────────────────────────────────────────────────── */
function triggerUpdate() {
  document.getElementById('overlay-update').classList.add('active');
}

async function startUpdate() {
  const log = document.getElementById('update-log');
  const btn = document.getElementById('btn-start-update');
  btn.disabled = true;
  log.innerHTML = '';

  function addLine(text, cls = '') {
    const d = document.createElement('div');
    d.className = 'log-line' + (cls ? ' ' + cls : '');
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  addLine('→ Récupération des dernières modifications (git pull)…');
  try {
    const r = await fetch(`${API}/api/admin/update`, { method: 'POST' });
    const d = await r.json();
    if (d.results?.git_pull?.output) {
      addLine(d.results.git_pull.output, d.results.git_pull.success ? 'ok' : 'error');
    }
    if (!d.success) {
      addLine('✗ Mise à jour échouée.', 'error');
      btn.disabled = false;
      return;
    }
    if (d.new_version) {
      addLine(`✓ Nouvelle version : ${d.new_version}`, 'ok');
      setText('app-version', d.new_version);
      document.getElementById('update-badge')?.classList.remove('visible');
    }
    addLine('✓ Code mis à jour.', 'ok');
    addLine('→ Redémarrage du service…');

    let attempts = 0;
    const poll = setInterval(async () => {
      attempts++;
      try {
        const h = await fetch(`${API}/health`, { cache: 'no-store' });
        if (h.ok) {
          clearInterval(poll);
          addLine('✓ Service redémarré !', 'ok');
          addLine('→ Rechargement de l\'interface…');
          setTimeout(() => {
            document.getElementById('overlay-update').classList.remove('active');
            window.location.reload();
          }, 1500);
        }
      } catch (_) {
        if (attempts >= 20) {
          clearInterval(poll);
          addLine('⚠ Timeout — recharger la page manuellement.', 'warn');
        }
      }
    }, 1500);
  } catch (e) {
    addLine(`✗ Erreur : ${e.message}`, 'error');
    btn.disabled = false;
  }
}

/* ── Services & Logs ──────────────────────────────────────────────────────── */
let _logConfigLoaded = false;
let _servicesInterval = 15;

function startLogs() {
  if (!_logConfigLoaded) {
    _initLogsConfig().then(() => loadLogs());
  } else {
    loadLogs();
  }
}

async function _initLogsConfig() {
  try {
    const r = await fetch(`${API}/api/admin/config`);
    const d = await r.json();
    const entry = (d ?? []).find(c => c.key === 'services_refresh_interval');
    _servicesInterval = entry ? Math.max(5, parseInt(entry.value, 10)) : 15;
    setText('log-refresh-label', `Auto-refresh ${_servicesInterval}s`);
  } catch {}
  _logConfigLoaded = true;
}

async function loadPipeline() {
  if (activeTab !== 'dashboard') return;
  try {
    const r = await fetch(`${API}/api/admin/jobs/status`);
    const d = await r.json();
    _renderPipeline(d);
  } catch (e) {
    const el = document.getElementById('pipeline-list');
    if (el) el.innerHTML =
      `<div class="service-row"><span class="text-muted">Erreur : ${escHtml(e.message)}</span></div>`;
  }
}

function _renderPipeline(jobs) {
  const sc = jobs.scanner   ?? {};
  const az = jobs.analyzer  ?? {};
  const ct = jobs.cataloger ?? {};

  function badge(cls, label) {
    return `<span class="badge badge-${cls}"><span class="dot"></span>${label}</span>`;
  }

  const scanBadge = sc.last_status === 'running' ? badge('info', 'En cours')
                  : sc.last_status === 'done'    ? badge('success', 'Idle')
                  : sc.last_status === 'error'   ? badge('danger', 'Erreur')
                  : badge('muted', '—');
  const scanDetail = [
    sc.last_mount    ? `/${sc.last_mount}` : '',
    sc.files_found != null ? `${sc.files_found} fichiers` : '',
    sc.files_new    ? `+${sc.files_new} nouveaux` : '',
    sc.last_finished ? sc.last_finished.slice(11, 16) : '',
  ].filter(Boolean).join(' · ');

  const azBadge = az.running
    ? badge('info', `En cours ${az.current_done}/${az.current_total}`)
    : badge('success', 'Idle');
  const azDetail = az.running
    ? escHtml(az.current_folder ?? '')
    : [
        az.sessions_done != null ? `${az.sessions_done} sessions` : '',
        az.sessions_pending      ? `${az.sessions_pending} en attente` : '',
        az.last_finished         ? az.last_finished.slice(11, 16) : '',
      ].filter(Boolean).join(' · ');

  const ctDetail = [
    ct.titles_ok != null   ? `${ct.titles_ok} OK` : '',
    ct.titles_to_rename    ? `${ct.titles_to_rename} à renommer` : '',
    ct.proposals_pending   ? `${ct.proposals_pending} propositions` : '',
  ].filter(Boolean).join(' · ') || '—';

  const el = document.getElementById('pipeline-list');
  if (!el) return;
  el.innerHTML = `
    <div class="service-row">
      <span class="service-icon"><i class="bi bi-search"></i></span>
      <span class="service-name">Scanner</span>
      <span class="service-badge">${scanBadge}</span>
      <span class="service-detail">${scanDetail || '—'}</span>
    </div>
    <div class="service-row">
      <span class="service-icon"><i class="bi bi-cpu"></i></span>
      <span class="service-name">Analyzer</span>
      <span class="service-badge">${azBadge}</span>
      <span class="service-detail">${azDetail || '—'}</span>
    </div>
    <div class="service-row">
      <span class="service-icon"><i class="bi bi-journals"></i></span>
      <span class="service-name">Cataloger</span>
      <span class="service-badge">${badge('success', 'Idle')}</span>
      <span class="service-detail">${ctDetail}</span>
    </div>`;
}

async function loadLogs() {
  if (activeTab !== 'logs') return;
  const lines  = document.getElementById('log-lines')?.value  ?? 100;
  const level  = document.getElementById('log-level')?.value  ?? '';
  const module = document.getElementById('log-module')?.value ?? '';
  try {
    const params = new URLSearchParams({ lines });
    if (level)  params.set('level',  level);
    if (module) params.set('module', module);
    const r = await fetch(`${API}/api/admin/logs?${params}`);
    const d = await r.json();

    if (d.modules?.length) _updateModuleSelect(d.modules, module);

    const box = document.getElementById('log-box');
    const atBottom = box.scrollHeight - box.scrollTop <= box.clientHeight + 8;
    const savedScroll = box.scrollTop;
    if (d.logs?.length) {
      box.innerHTML = d.logs.map(e => {
        const cls = _levelClass(e.level);
        return `<div class="log-line ${cls}">` +
          `<span class="log-ts">${escHtml(e.ts)}</span>` +
          `<span class="log-lvl">${escHtml(e.level)}</span>` +
          `<span class="log-mod">${escHtml(e.module)}</span>` +
          `<span class="log-msg">${escHtml(e.message)}</span>` +
          `</div>`;
      }).join('');
      box.scrollTop = atBottom ? box.scrollHeight : savedScroll;
    } else {
      box.innerHTML = '<div class="log-line log-full">Aucun log disponible</div>';
    }
  } catch (e) {
    document.getElementById('log-box').innerHTML =
      `<div class="log-line log-full error">Erreur : ${escHtml(e.message)}</div>`;
  }
  logTimer = setTimeout(startLogs, _servicesInterval * 1000);
}

function _levelClass(level) {
  if (level === 'ERROR' || level === 'CRITICAL') return 'error';
  if (level === 'WARNING') return 'warn';
  if (level === 'INFO')    return 'info';
  return '';
}

function _updateModuleSelect(modules, current) {
  const sel = document.getElementById('log-module');
  if (!sel) return;
  const opts = ['<option value="">Tous</option>'];
  for (const m of modules) {
    opts.push(`<option value="${escHtml(m)}"${m === current ? ' selected' : ''}>${escHtml(m)}</option>`);
  }
  sel.innerHTML = opts.join('');
}

/* ── API tab ──────────────────────────────────────────────────────────────── */
async function testAPIConn() {
  const el = document.getElementById('api-test-result');
  el.innerHTML = '<span class="spinner"></span>';
  try {
    const r = await fetch(`${API}/health`);
    const d = await r.json();
    el.innerHTML = `<span class="badge badge-success"><span class="dot"></span>${d.status ?? 'ok'}</span>`;
  } catch (e) {
    el.innerHTML = `<span class="badge badge-danger"><span class="dot"></span>${escHtml(e.message)}</span>`;
  }
}

/* ── Purge (dev) ──────────────────────────────────────────────────────────── */
function confirmPurge() {
  document.getElementById('purge-result').innerHTML = '';
  document.getElementById('btn-confirm-purge').disabled = false;
  document.getElementById('overlay-purge').classList.add('active');
}

function closePurge() {
  document.getElementById('overlay-purge').classList.remove('active');
}

async function executePurge() {
  const btn = document.getElementById('btn-confirm-purge');
  const res = document.getElementById('purge-result');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Purge…';
  try {
    const r = await fetch(`${API}/api/admin/purge`, { method: 'DELETE' });
    const d = await r.json();
    if (d.success) {
      res.innerHTML = '<span class="text-success"><i class="bi bi-check-circle"></i> ' + escHtml(d.message) + '</span>';
      setTimeout(() => {
        closePurge();
        loadDashboard();
      }, 1500);
    } else {
      res.innerHTML = '<span class="text-danger">Erreur : ' + escHtml(JSON.stringify(d)) + '</span>';
    }
  } catch (e) {
    res.innerHTML = '<span class="text-danger"><i class="bi bi-x-circle"></i> ' + escHtml(e.message) + '</span>';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-trash3"></i> Confirmer la purge';
  }
}

/* ── Auth ─────────────────────────────────────────────────────────────────── */
async function authInit() {
  try {
    const r = await fetch(`${API}/api/auth/me`);
    if (r.status === 401) { location.href = '/login'; return; }
    const d = await r.json();
    setText('nav-username', d.username ?? '—');
    const roleEl = document.getElementById('nav-role');
    if (roleEl) {
      roleEl.textContent = d.role === 'admin' ? 'Admin' : 'Viewer';
      roleEl.className = 'nav-role ' + (d.role === 'admin' ? 'role-admin' : 'role-viewer');
    }
  } catch { /* ignore réseau */ }
}

async function authLogout() {
  await fetch(`${API}/api/auth/logout`, { method: 'POST' });
  location.href = '/login';
}

/* ── Utilisateurs ─────────────────────────────────────────────────────────── */
const Users = (() => {
  let _editingUid = null;
  let _editingName = '';

  async function load() {
    try {
      const r = await fetch(`${API}/api/admin/users`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _render(d.users ?? []);
    } catch (e) {
      document.getElementById('users-tbody').innerHTML =
        `<tr><td colspan="4" class="text-danger">${escHtml(e.message)}</td></tr>`;
    }
  }

  function _render(users) {
    const tbody = document.getElementById('users-tbody');
    if (!users.length) {
      tbody.innerHTML = '<tr><td colspan="4"><div class="empty-state">Aucun utilisateur</div></td></tr>';
      return;
    }
    tbody.innerHTML = users.map(u => `
      <tr>
        <td><strong>${escHtml(u.username)}</strong></td>
        <td><span class="badge ${u.role === 'admin' ? 'badge-info' : 'badge-muted'}">${escHtml(u.role)}</span></td>
        <td class="text-muted">${escHtml(u.created_at)}</td>
        <td class="td-actions">
          <button class="btn btn-sm" onclick="Users.openPwd(${u.id},'${escHtml(u.username)}')" title="Changer le mot de passe">
            <i class="bi bi-key"></i>
          </button>
          <button class="btn btn-sm btn-danger" onclick="Users.del(${u.id},'${escHtml(u.username)}')" title="Supprimer">
            <i class="bi bi-trash3"></i>
          </button>
        </td>
      </tr>`).join('');
  }

  function openAdd() {
    document.getElementById('add-username').value = '';
    document.getElementById('add-password').value = '';
    document.getElementById('add-role').value = 'viewer';
    document.getElementById('add-user-error').textContent = '';
    document.getElementById('overlay-user-add').classList.add('active');
  }
  function closeAdd() {
    document.getElementById('overlay-user-add').classList.remove('active');
  }

  async function submitAdd() {
    const username = document.getElementById('add-username').value.trim();
    const password = document.getElementById('add-password').value;
    const role     = document.getElementById('add-role').value;
    const errEl    = document.getElementById('add-user-error');
    errEl.textContent = '';
    if (!username || !password) { errEl.textContent = 'Champs requis manquants.'; return; }
    try {
      const r = await fetch(`${API}/api/admin/users`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, role })
      });
      const d = await r.json();
      if (!r.ok) { errEl.textContent = d.detail || 'Erreur'; return; }
      closeAdd();
      load();
    } catch (e) { errEl.textContent = e.message; }
  }

  function openPwd(uid, username) {
    _editingUid  = uid;
    _editingName = username;
    document.getElementById('pwd-username').textContent = username;
    document.getElementById('pwd-new').value = '';
    document.getElementById('pwd-error').textContent = '';
    document.getElementById('overlay-user-pwd').classList.add('active');
  }
  function closePwd() {
    document.getElementById('overlay-user-pwd').classList.remove('active');
  }

  async function submitPwd() {
    const password = document.getElementById('pwd-new').value;
    const errEl    = document.getElementById('pwd-error');
    errEl.textContent = '';
    if (!password) { errEl.textContent = 'Mot de passe requis.'; return; }
    try {
      const r = await fetch(`${API}/api/admin/users/${_editingUid}/password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password })
      });
      const d = await r.json();
      if (!r.ok) { errEl.textContent = d.detail || 'Erreur'; return; }
      closePwd();
    } catch (e) { errEl.textContent = e.message; }
  }

  async function del(uid, username) {
    if (!confirm(`Supprimer l'utilisateur « ${username} » ?`)) return;
    try {
      const r = await fetch(`${API}/api/admin/users/${uid}`, { method: 'DELETE' });
      const d = await r.json();
      if (!r.ok) { alert(d.detail || 'Erreur'); return; }
      load();
    } catch (e) { alert(e.message); }
  }

  return { load, openAdd, closeAdd, submitAdd, openPwd, closePwd, submitPwd, del };
})();

/* ── Init ─────────────────────────────────────────────────────────────────── */
window.addEventListener('load', () => {
  // Thème sauvegardé
  const savedTheme = localStorage.getItem('mm-theme') || 'dark';
  setTheme(savedTheme);
  // Base URL
  setText('base-url', API);
  // Auth : vérifie session et affiche l'utilisateur
  authInit();
  // Démarrer
  startDashboard();
  // Init mounts
  if (typeof Mounts !== 'undefined') Mounts.init();
});