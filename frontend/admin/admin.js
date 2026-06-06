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

function switchTab(name) {
  if (name === activeTab) return;
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
        <span class="card-value" style="font-size:.82rem">${d.system?.start_time ?? '—'}</span></div>
      <div class="card-row"><span class="card-label">IP</span>
        <span class="card-value" style="color:var(--blue)">${d.system?.ip ?? '—'}</span></div>
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
      <div class="card-header"><i class="bi bi-database"></i> PostgreSQL</div>
      <div class="card-row"><span class="card-label">Statut</span>
        <span class="badge ${isConn ? 'badge-success' : 'badge-danger'}">
          <span class="dot"></span>${isConn ? 'Connected' : 'Disconnected'}
        </span></div>
      <div class="card-row"><span class="card-label">Type</span>
        <span class="card-value">${db.type ?? 'PostgreSQL'}</span></div>
      <div class="card-row"><span class="card-label">Base</span>
        <span class="card-value" style="color:var(--blue)">${db.database ?? '—'}</span></div>
    </div>
  `;
}

async function updateDashStats(d) {
  const m = d.services?.mounts ?? {};
  const total   = m.total   ?? 0;
  const healthy = m.healthy ?? 0;
  const failed  = m.failed  ?? 0;

  setText('stat-mounts-up',    healthy);
  setText('stat-mounts-down',  failed);
  setText('stat-mounts-total', total);
  setText('stat-mounts-up2',   healthy);
  setText('stat-mounts-down2', failed);
  setText('stat-mounts-label', `${total} montage${total > 1 ? 's' : ''} configuré${total > 1 ? 's' : ''}`);
  const mPct = total > 0 ? Math.round(healthy / total * 100) : 0;
  const mBar = document.getElementById('stat-mounts-bar');
  if (mBar) mBar.style.width = mPct + '%';

   // ── Fichiers — appel API dédié ──────────────────────────────────────────
  try {
    const r = await fetch(`${API}/api/admin/files/stats`);
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const f = await r.json();
    
    const fanalyzed  = f.analyzed   ?? 0;
    const fdiscovered= f.discovered ?? 0;
    const fanalyzing = f.analyzing  ?? 0;
    const ftotal     = f.total      ?? 0;

    // Barre de navigation (header)
    setText('stat-files-ok',    fanalyzed);
    setText('stat-files-wait',  fdiscovered + fanalyzing);
    setText('stat-files-total', ftotal);

    // Panneau détail
    const pct = ftotal > 0 ? Math.round(fanalyzed / ftotal * 100) : 0;
    setText('stat-files-pct',   ftotal > 0 ? `${pct}% ANALYSÉ` : '—');
    setText('stat-files-label', `${ftotal} Fichier${ftotal > 1 ? 's' : ''} indexé${ftotal > 1 ? 's' : ''}`);
    setText('stat-files-ok2',   fanalyzed);
    setText('stat-files-wait2', fdiscovered + fanalyzing);
    const bar = document.getElementById('stat-files-bar');
    if (bar) bar.style.width = (ftotal > 0 ? pct : 0) + '%';

    // Catégories dans le header
    const cats = f.by_category ?? [];
    const catsWithFiles = cats.filter(c => c.count > 0);
    const catEl = document.getElementById('stat-categories-list');
    if (catEl) {
      if (catsWithFiles.length === 0) {
        catEl.innerHTML = '<span style="color:var(--muted)">—</span>';
      } else {
        catEl.innerHTML = catsWithFiles
          .map(c => `<span style="color:var(--purple);font-weight:600">
            ${esc(c.name.charAt(0).toUpperCase() + c.name.slice(1))} (${c.count})
          </span>`)
          .join('<span class="slash"> / </span>');
      }
    }

  } catch (e) {
    console.warn('files/stats:', e.message);
  }

// ── Bibliothèque ──────────────────────────────────────────────────────────
      const lib = d.library ?? {};
      const tb  = lib.total_tb ?? 0;
      setText('stat-files-size',
        tb >= 1 ? `${tb} To` : `${Math.round(tb * 1024)} Go`);
      setText('stat-files-missing',   lib.missing_files   ?? 0);
      setText('stat-files-duplicate', lib.duplicate_files ?? 0);

      // Nb titres
      setText('stat-lib-titles', lib.nb_titles ?? '—');

      // Durée totale
      const h      = lib.total_hours ?? 0;
      const years  = Math.floor(h / 8760);
      const months = Math.floor((h % 8760) / 730);
      let hl = '';
      if (years  > 0) hl += `${years} an${years  > 1 ? 's' : ''} `;
      if (months > 0) hl += `${months} mois`;
      if (!hl)        hl  = `${Math.round(h).toLocaleString('fr-FR')} h`;
      setText('stat-lib-hours', hl.trim());

      // BDD
      setText('stat-db-size',    d.services?.database?.size ?? '—');
      setText('stat-db-missing', lib.missing_files ?? 0);

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
  el.innerHTML = `<span class="badge ${cls}" style="margin-top:8px">${esc(msg)}</span>`;
  setTimeout(() => { el.innerHTML = ''; }, 5000);
}

/* ── Stats panel toggle ───────────────────────────────────────────────────── */
function toggleStats() {
  const drawer  = document.getElementById('stats-drawer');
  const chevron = document.getElementById('stats-chevron');
  drawer.classList.toggle('open');
  chevron.classList.toggle('open');
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
  badge.style.opacity = '0.5';
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
    badge.style.opacity = '';
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
    if (isPrerelease) {
      badge.style.borderColor = 'var(--yellow)';
      badge.style.color       = 'var(--yellow)';
    } else {
      badge.style.borderColor = '';
      badge.style.color       = '';
    }
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

/* ── Logs ─────────────────────────────────────────────────────────────────── */
function startLogs() { loadLogs(); }

async function loadLogs() {
  if (activeTab !== 'logs') return;
  const lines = document.getElementById('log-lines')?.value ?? 50;
  try {
    const r = await fetch(`${API}/api/admin/logs?lines=${lines}`);
    const d = await r.json();
    const box = document.getElementById('log-box');
    if (d.logs?.length) {
      box.innerHTML = d.logs
        .filter(l => l.trim())
        .map(l => `<div class="log-line ${classifyLog(l)}">${esc(l)}</div>`)
        .join('');
      box.scrollTop = box.scrollHeight;
    } else {
      box.innerHTML = '<div class="log-line">Aucun log disponible</div>';
    }
  } catch (e) {
    document.getElementById('log-box').innerHTML =
      `<div class="log-line error">Erreur : ${esc(e.message)}</div>`;
  }
  logTimer = setTimeout(loadLogs, 5000);
}

function classifyLog(line) {
  const l = line.toLowerCase();
  if (l.includes('error') || l.includes('erreur') || l.includes('exception')) return 'error';
  if (l.includes('warn'))  return 'warn';
  if (l.includes('info'))  return 'info';
  if (l.includes('ok') || l.includes('success') || l.includes('réussi')) return 'ok';
  return '';
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
    el.innerHTML = `<span class="badge badge-danger"><span class="dot"></span>${esc(e.message)}</span>`;
  }
}

/* ── Utilitaires ──────────────────────────────────────────────────────────── */
function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }
function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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
      res.innerHTML = '<span style="color:var(--green)"><i class="bi bi-check-circle"></i> ' + esc(d.message) + '</span>';
      setTimeout(() => {
        closePurge();
        loadDashboard();
      }, 1500);
    } else {
      res.innerHTML = '<span style="color:var(--red)">Erreur : ' + esc(JSON.stringify(d)) + '</span>';
    }
  } catch (e) {
    res.innerHTML = '<span style="color:var(--red)"><i class="bi bi-x-circle"></i> ' + esc(e.message) + '</span>';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-trash3"></i> Confirmer la purge';
  }
}

/* ── Init ─────────────────────────────────────────────────────────────────── */
window.addEventListener('load', () => {
  // Thème sauvegardé
  const savedTheme = localStorage.getItem('mm-theme') || 'dark';
  setTheme(savedTheme);
  // Base URL
  setText('base-url', API);
  // Démarrer
  startDashboard();
  // Init mounts
  if (typeof Mounts !== 'undefined') Mounts.init();

});