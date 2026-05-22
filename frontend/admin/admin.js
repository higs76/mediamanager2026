/* =============================================================================
   MediaManager 2026 — admin.js
   Gestion : onglets, dashboard, logs, API, infos système, version/update
   ============================================================================= */

const API = `http://${window.location.hostname}:8000`;

/* ── Onglets ──────────────────────────────────────────────────────────────── */
let activeTab  = 'dashboard';
let logTimer   = null;
let dashTimer  = null;

function switchTab(name) {
  if (name === activeTab) return;

  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(b => b.classList.remove('active'));

  document.getElementById('panel-' + name).classList.add('active');
  document.querySelector(`.nav-tab[data-tab="${name}"]`).classList.add('active');

  // Arrêter les timers des anciens onglets
  clearTimeout(logTimer);
  clearTimeout(dashTimer);

  activeTab = name;

  if (name === 'dashboard') startDashboard();
  else if (name === 'logs')  startLogs();
  else if (name === 'mounts') Mounts.init();
}

/* ── Dashboard ────────────────────────────────────────────────────────────── */
let versionCheckTimer = null;

function startDashboard() {
  loadDashboard();
  // Vérification de version : au démarrage puis toutes les 30 minutes
  // Séparée du refresh dashboard (5s) pour ne pas spammer GitHub API
  checkVersion();
}

async function checkVersion() {
  try {
    const r = await fetch(`${API}/api/admin/dashboard`);
    const d = await r.json();
    setVersion(d.version, d.latest_version);
  } catch (_) {}
  clearTimeout(versionCheckTimer);
  versionCheckTimer = setTimeout(checkVersion, 30 * 60 * 1000); // 30 minutes
}

async function loadDashboard() {
  if (activeTab !== 'dashboard') return;
  try {
    const r = await fetch(`${API}/api/admin/dashboard`);
    const d = await r.json();

    // Header système (sans vérif version — gérée par checkVersion)
    setText('sys-host', d.system?.host ?? '—');
    setText('sys-ip',   d.system?.ip   ?? '—');
    setText('sys-time', new Date().toLocaleTimeString('fr-FR'));

    // Header système
    //setSystemInfo(d);

    // Grille de cartes
    const grid = document.getElementById('dash-grid');
    const watcher = d.services?.watcher ?? {};
    const db      = d.services?.database ?? {};
    const mounts  = d.services?.mounts  ?? {};

    grid.innerHTML = `
      ${serviceCard('⚙️', watcher.name || 'Watcher', watcher, true)}
      ${serviceCard('🗄️', db.name      || 'Database', db,  false)}
      ${mountCard(mounts)}
    `;
  } catch (e) {
    showDashMsg('error', `Connexion impossible : ${e.message}`);
  }
  dashTimer = setTimeout(loadDashboard, 5000);
}

function serviceCard(icon, name, svc, withActions) {
  const st = (svc.status || 'unknown').toLowerCase();
  const cls = st === 'running' ? 'badge-green' : st === 'stopped' ? 'badge-red' : 'badge-muted';
  let rows = `
    <div class="service-row">
      <span class="service-label">Status</span>
      <span class="badge ${cls}"><span class="badge-dot"></span>${(svc.status || '—').toUpperCase()}</span>
    </div>`;
  if (svc.pid)      rows += row('PID', svc.pid);
  if (svc.type)     rows += row('Type', svc.type);
  if (svc.database) rows += row('Base', svc.database);

  const actions = withActions ? `
    <div class="card-actions">
      <button class="btn btn-secondary" onclick="svcAction('watcher','restart')">↺ Restart</button>
      <button class="btn btn-danger"    onclick="svcAction('watcher','stop')">▪ Stop</button>
    </div>` : '';

  return `<div class="card"><div class="card-title">${icon} ${name}</div>${rows}${actions}</div>`;
}

function mountCard(m) {
  return `
    <div class="card">
      <div class="card-title">📁 ${m.name || 'Montages'}</div>
      ${row('Total',      m.total   ?? '—')}
      ${row('Montés',     m.healthy ?? '—')}
      ${row('En erreur',  m.failed  ?? '—')}
      <div class="card-actions">
        <button class="btn btn-secondary" onclick="switchTab('mounts')">→ Gérer les montages</button>
      </div>
    </div>`;
}

function row(label, val) {
  return `<div class="service-row"><span class="service-label">${label}</span><span class="service-val">${val}</span></div>`;
}

async function svcAction(svc, action) {
  if (!confirm(`${action === 'restart' ? 'Redémarrer' : 'Arrêter'} le service ${svc} ?`)) return;
  try {
    const r = await fetch(`${API}/api/admin/services/${svc}/${action}`, { method: 'POST' });
    const d = await r.json();
    showDashMsg(d.status === 'success' ? 'ok' : 'error', d.message || d.error);
    setTimeout(loadDashboard, 1500);
  } catch (e) {
    showDashMsg('error', e.message);
  }
}

function showDashMsg(type, msg) {
  const el = document.getElementById('dash-msg');
  const cls = type === 'ok' ? 'badge-green' : 'badge-red';
  el.innerHTML = `<div class="badge ${cls}" style="margin-top:.75rem">${msg}</div>`;
  setTimeout(() => { el.innerHTML = ''; }, 4000);
}

/* ── Infos système (header) ───────────────────────────────────────────────── */
function setSystemInfo(d) {
  setText('sys-host', d.system?.host ?? '—');
  setText('sys-ip',   d.system?.ip   ?? '—');
  setText('sys-time', new Date().toLocaleTimeString('fr-FR'));
  setVersion(d.version, d.latest_version);
}

function setVersion(current, latest, build, branch) {
  // Afficher version + hash court : "0.3.1-dev (a1b2c3d)"
  const display = build && build !== 'unknown'
    ? `${current ?? '—'} (${build})`
    : (current ?? '—');
  setText('app-version', display);
 
  const badge = document.getElementById('update-badge');
  if (latest && latest !== current) {
    // Adapter le message selon le mode
    const isDev = branch === 'dev';
    badge.textContent = isDev ? `↑ commit ${latest}` : `↑ ${latest}`;
    badge.title = isDev
      ? `Nouveau commit disponible sur la branche dev : ${latest}`
      : `Nouvelle version disponible : ${latest}. Cliquer pour mettre à jour.`;
    badge.classList.add('visible');
  } else {
    badge.classList.remove('visible');
  }
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

async function refreshHeader() {
  const btn = document.querySelector('.refresh-btn');
  if (btn) btn.textContent = '…';
  try {
    const r = await fetch(`${API}/api/admin/dashboard`);
    const d = await r.json();
    setSystemInfo(d);
  } catch (_) {}
  if (btn) btn.textContent = '↻';
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
      `<div class="log-line error">Erreur : ${e.message}</div>`;
  }
  logTimer = setTimeout(loadLogs, 5000);
}

function classifyLog(line) {
  const l = line.toLowerCase();
  if (l.includes('error') || l.includes('erreur') || l.includes('exception')) return 'error';
  if (l.includes('warn')  || l.includes('warning'))  return 'warn';
  if (l.includes('info'))  return 'info';
  if (l.includes('ok') || l.includes('success') || l.includes('démarr')) return 'ok';
  return '';
}

/* ── API tab ──────────────────────────────────────────────────────────────── */
async function testAPIConn() {
  const el = document.getElementById('api-test-result');
  el.innerHTML = '<span class="spinner"></span>';
  try {
    const r = await fetch(`${API}/health`);
    const d = await r.json();
    el.innerHTML = `<span class="badge badge-green">✓ ${d.status ?? 'ok'}</span>`;
  } catch (e) {
    el.innerHTML = `<span class="badge badge-red">✗ ${e.message}</span>`;
  }
}

/* ── Update ───────────────────────────────────────────────────────────────── */
async function triggerUpdate() {
  // Afficher la popup de mise à jour
  document.getElementById('overlay-update').classList.add('show');
}

async function startUpdate() {
  const log = document.getElementById('update-log');
  const btn  = document.getElementById('btn-start-update');
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
 
    // Afficher la nouvelle version et mettre à jour le header
    if (d.new_version) {
      addLine(`✓ Nouvelle version : ${d.new_version}`, 'ok');
      setText('app-version', d.new_version);
      document.getElementById('update-badge')?.classList.remove('visible');
    }
    addLine('✓ Code mis à jour.', 'ok');
    addLine('→ Redémarrage du service…');
 
    // Attendre que le service redémarre puis recharger la page
    let attempts = 0;
    const maxAttempts = 20;
 
    const poll = setInterval(async () => {
      attempts++;
      try {
        const health = await fetch(`${API}/health`, { cache: 'no-store' });
        if (health.ok) {
          clearInterval(poll);
          addLine('✓ Service redémarré !', 'ok');
          addLine('→ Rechargement de l\'interface…');
          setTimeout(() => {
            document.getElementById('overlay-update').classList.remove('show');
            window.location.reload();
          }, 1500);
        }
      } catch (_) {
        // Service en cours de redémarrage — normal
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          addLine('⚠ Timeout — rechargez la page manuellement.', 'warn');
        }
      }
    }, 1500);
 
  } catch (e) {
    addLine(`✗ Erreur : ${e.message}`, 'error');
    btn.disabled = false;
  }
}


/* ── Utilitaires ──────────────────────────────────────────────────────────── */
function esc(s) {
  return String(s ?? '')
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/* ── Init ─────────────────────────────────────────────────────────────────── */
window.addEventListener('load', () => {
  document.getElementById('base-url').textContent = API;
  startDashboard();
});