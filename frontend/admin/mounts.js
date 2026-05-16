/* =============================================================================
   MediaManager 2026 — mounts.js
   Onglet "Montages NAS" — browse réseau, options collapse, CRUD complet
   ============================================================================= */

const Mounts = (() => {

  /* ── État ─────────────────────────────────────────────────────────────── */
  let allMounts    = [];
  let categories   = [];
  let currentCat   = 'all';
  let editingId    = null;
  let deletingId   = null;
  let selectedType = null;

  /* ── Définition des types de montage ──────────────────────────────────── */
  const MOUNT_TYPES = {
    smb: {
      icon: '🖥️', name: 'SMB / CIFS', desc: 'NAS Synology, QNAP, Windows',
      fields: () => `
        <div class="section-sep">Partage réseau</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <div class="browse-row">
              <input id="f-server" type="text" placeholder="//192.168.1.10 ou //DS1821"
                     oninput="Mounts._clearBrowse()">
              <button type="button" class="btn btn-secondary"
                      onclick="Mounts._browse('smb')" title="Lister les partages">🔍 Parcourir</button>
            </div>
            <div class="browse-results" id="browse-results"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Partage <span class="req">*</span></label>
            <input id="f-share" type="text" placeholder="/series — ou cliquer Parcourir">
          </div>
        </div>
        <div class="section-sep">Authentification</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Utilisateur</label>
            <input id="f-user" type="text" placeholder="Vide = accès invité">
          </div>
          <div class="form-group">
            <label class="form-label">Mot de passe</label>
            <div class="browse-row">
              <input id="f-password" type="password" style="flex:1">
              <button type="button" class="btn btn-secondary" style="flex-shrink:0;padding:.46rem .6rem"
                onclick="Mounts._togglePassword()" id="btn-eye" title="Voir/masquer le mot de passe">👁</button>
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Domaine</label>
            <input id="f-domain" type="text" value="WORKGROUP">
            <span class="form-hint">WORKGROUP pour la plupart des NAS</span>
          </div>
          <div class="form-group">
            <label class="form-label">Version SMB</label>
            <select id="f-smb-version">
              <option value="3.0" selected>3.0 — recommandé</option>
              <option value="2.1">2.1</option>
              <option value="2.0">2.0</option>
              <option value="1.0">1.0 — vieux NAS uniquement</option>
            </select>
          </div>
        </div>
        <div class="collapsible-toggle" onclick="Mounts._toggleCollapse(this)">
          <div class="section-sep">Options avancées</div>
          <span class="collapse-arrow">▼</span>
        </div>
        <div class="collapsible-body">
          <div class="form-group" style="margin-top:.5rem">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text"
                   value="uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8">
            <span class="form-hint">Options CIFS passées à mount -t cifs -o ...</span>
          </div>
        </div>`
    },
    nfs: {
      icon: '🐧', name: 'NFS', desc: 'NAS Linux, Synology NFS',
      fields: () => `
        <div class="section-sep">Export NFS</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <div class="browse-row">
              <input id="f-server" type="text" placeholder="192.168.1.10 ou nas1"
                     oninput="Mounts._clearBrowse()">
              <button type="button" class="btn btn-secondary"
                      onclick="Mounts._browse('nfs')" title="Lister les exports NFS">🔍 Parcourir</button>
            </div>
            <span class="form-hint">Sans // — NFS utilise l'IP directe</span>
            <div class="browse-results" id="browse-results"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Export <span class="req">*</span></label>
            <input id="f-share" type="text" placeholder="/volume1/series — ou cliquer Parcourir">
          </div>
          <div class="form-group">
            <label class="form-label">Version NFS</label>
            <select id="f-nfs-version">
              <option value="4" selected>NFSv4 — recommandé</option>
              <option value="3">NFSv3</option>
            </select>
          </div>
        </div>
        <div class="collapsible-toggle" onclick="Mounts._toggleCollapse(this)">
          <div class="section-sep">Options avancées</div>
          <span class="collapse-arrow">▼</span>
        </div>
        <div class="collapsible-body">
          <div class="form-group" style="margin-top:.5rem">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text" value="rw,soft,timeo=30">
          </div>
        </div>`
    }
  };

  /* ── Init ─────────────────────────────────────────────────────────────── */
  async function init() {
    await Promise.all([loadMounts(), loadCategories()]);
  }

  /* ── Chargement ───────────────────────────────────────────────────────── */
  async function loadMounts() {
    try {
      const r = await fetch(`${API}/api/admin/mounts`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      allMounts = d.mounts ?? [];
      updateStats();
      renderTable();
    } catch (e) {
      showBanner('error', 'Chargement échoué', e.message);
    }
  }

  async function loadCategories() {
    try {
      const r = await fetch(`${API}/api/admin/categories`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      categories = d.categories ?? [];
    } catch (_) {
      // Fallback : déduire depuis les montages existants
      categories = [...new Set(allMounts.map(m => m.category_name).filter(Boolean))];
    }
    renderCategoryFilters();
    renderCategorySelect();
  }

  /* ── Stats ────────────────────────────────────────────────────────────── */
  function updateStats() {
    const mounted = allMounts.filter(m => m.is_mounted).length;
    setText('stat-total',   allMounts.length);
    setText('stat-mounted', mounted);
    setText('stat-missing', allMounts.length - mounted);
  }

  /* ── Filtres ──────────────────────────────────────────────────────────── */
  function renderCategoryFilters() {
    const container = document.getElementById('cat-filters');
    if (!container) return;
    container.innerHTML = ['all', ...categories].map(cat => {
      const label = cat === 'all' ? 'Tous' : cap(cat);
      return `<button class="cat-btn${cat === currentCat ? ' active' : ''}"
        onclick="Mounts._filterCat(this,'${esc(cat)}')">${label}</button>`;
    }).join('');
  }

  function renderCategorySelect() {
    const sel = document.getElementById('f-cat-select');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">— Choisir —</option>'
      + categories.map(c => `<option value="${esc(c)}">${cap(c)}</option>`).join('');
    if (cur) sel.value = cur;
  }

  function _filterCat(btn, cat) {
    document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentCat = cat;
    renderTable();
  }

  /* ── Table ────────────────────────────────────────────────────────────── */
  function renderTable() {
    const filtered = currentCat === 'all'
      ? allMounts
      : allMounts.filter(m => m.category_name === currentCat);

    const tbody = document.getElementById('mounts-tbody');
    if (!tbody) return;

    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">
        Aucun montage${currentCat !== 'all' ? ' pour cette catégorie' : ''}.
        Cliquez sur <strong>+ Ajouter</strong> pour commencer.
      </div></td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(m => {
      const label = `${m.id} - ${esc(m.category_name)}`;
      const source = m.mount_type === 'nfs'
        ? `${esc(m.server)}${esc(m.export_path)}`
        : `${esc(m.server)}${esc(m.share)}`;
      return `<tr data-id="${m.id}">
        <td><strong>${label}</strong></td>
        <td><span class="badge badge-blue">${esc(m.category_name)}</span></td>
        <td><span class="badge badge-muted">${(m.mount_type||'smb').toUpperCase()}</span></td>
        <td class="td-server">${source}</td>
        <td class="td-mono" title="${esc(m.local_path)}">${esc(m.local_path)}</td>
        <td>${mountedBadge(m.is_mounted)}</td>
        <td><div class="row-actions">
          <button class="icon-btn" onclick="Mounts._openEdit(${m.id})" title="Modifier">✏</button>
          <button class="icon-btn danger" onclick="Mounts._openDelete(${m.id})" title="Supprimer">🗑</button>
        </div></td>
      </tr>`;
    }).join('');
  }

  function mountedBadge(ok) {
    return ok
      ? '<span class="badge badge-green"><span class="badge-dot"></span>Monté</span>'
      : '<span class="badge badge-red"><span class="badge-dot"></span>Non monté</span>';
  }

  /* ── Popup Ajout ──────────────────────────────────────────────────────── */
  function _openAdd() {
    editingId    = null;
    selectedType = null;
    document.getElementById('modal-mount-title').textContent = 'Ajouter un montage';
    resetForm();
    renderCategorySelect();
    openOverlay('overlay-mount');
  }

  function _openEdit(id) {
    const m = allMounts.find(x => x.id === id);
    if (!m) return;
    editingId = id;
    document.getElementById('modal-mount-title').textContent = 'Modifier le montage';
    resetForm();
    selectType(m.mount_type || 'smb');
    fillForm(m);
    renderCategorySelect();
    // En édition : bloquer le changement de type
    // Le type est lié à la table BDD (mount_smb ou mount_nfs) et ne peut pas changer
    document.querySelectorAll('.type-card').forEach(c => {
      c.style.opacity  = c.dataset.type === m.mount_type ? '1' : '0.35';
      c.style.cursor   = c.dataset.type === m.mount_type ? 'default' : 'not-allowed';
      c.style.pointerEvents = 'none';  // désactive tous les clics
    });
    openOverlay('overlay-mount');
  }

  function resetForm() {
    selectedType = null;
    const active = document.getElementById('f-active');
    if (active) active.checked = true;
    setVal('f-cat-select', '');
    setVal('f-newcat', '');
    document.getElementById('type-fields').innerHTML = '';
    document.getElementById('type-fields').classList.remove('show');
    document.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected'));
  }

  function selectType(type) {
    selectedType = type;
    document.querySelectorAll('.type-card').forEach(c =>
      c.classList.toggle('selected', c.dataset.type === type)
    );
    const def = MOUNT_TYPES[type];
    if (!def) return;
    const section = document.getElementById('type-fields');
    section.innerHTML = def.fields();
    section.classList.add('show');
  }

  function fillForm(m) {
    setVal('f-server',      m.server          ?? '');
    setVal('f-share',       m.share           ?? m.export_path ?? '');
    setVal('f-user',        m.username        ?? '');
    setVal('f-domain',      m.domain          ?? 'WORKGROUP');
    setVal('f-smb-version', m.smb_version     ?? '3.0');
    setVal('f-nfs-version', String(m.nfs_version ?? 4));
    setVal('f-options',
      m.mount_type === 'nfs' ? (m.nfs_options ?? '') : (m.smb_options ?? ''));
    setVal('f-cat-select',  m.category_name   ?? '');
    const act = document.getElementById('f-active');
    if (act) act.checked = m.active !== false;
  }

  function _togglePassword() {
    const input = document.getElementById('f-password');
    const btn   = document.getElementById('btn-eye');
    if (!input) return;
    if (input.type === 'password') {
      input.type = 'text';
      btn.textContent = '🙈';
    } else {
      input.type = 'password';
      btn.textContent = '👁';
    }
  }

  /* ── Browse réseau ────────────────────────────────────────────────────── */
  async function _browse(type) {
    const server = (getVal('f-server') || '').trim();
    if (!server) { alert('Saisir d\'abord l\'adresse du serveur'); return; }

    const box = document.getElementById('browse-results');
    if (!box) return;
    box.className = 'browse-results show';
    box.innerHTML = '<div class="browse-empty"><span class="spinner"></span> Recherche…</div>';

    const user = getVal('f-user') || null;
    const pwd  = getVal('f-password') || null;
    let url = `${API}/api/admin/mounts/browse?type=${type}&server=${encodeURIComponent(server)}`;
    if (user) url += `&username=${encodeURIComponent(user)}`;
    if (pwd)  url += `&password=${encodeURIComponent(pwd)}`;

    try {
      const r = await fetch(url);
      const d = await r.json();
      if (d.error && !d.shares?.length) {
        box.innerHTML = `<div class="browse-error">⚠ ${esc(d.error)}</div>`;
        return;
      }
      if (!d.shares?.length) {
        box.innerHTML = '<div class="browse-empty">Aucun partage trouvé</div>';
        return;
      }
      box.innerHTML = d.shares.map(s =>
        `<div class="browse-item" onclick="Mounts._pickShare('${esc(s)}')">${esc(s)}</div>`
      ).join('');
    } catch (e) {
      box.innerHTML = `<div class="browse-error">Erreur : ${esc(e.message)}</div>`;
    }
  }

  function _pickShare(share) {
    setVal('f-share', share);
    _clearBrowse();
  }

  function _clearBrowse() {
    const box = document.getElementById('browse-results');
    if (box) { box.className = 'browse-results'; box.innerHTML = ''; }
  }

  /* ── Collapse options avancées ────────────────────────────────────────── */
  function _toggleCollapse(toggleEl) {
    toggleEl.classList.toggle('open');
    const body = toggleEl.nextElementSibling;
    if (body) body.classList.toggle('open');
  }

  /* ── Payload & save ───────────────────────────────────────────────────── */
  function buildPayload() {
    const catSelect = document.getElementById('f-cat-select')?.value || '';
    const newCat    = (document.getElementById('f-newcat')?.value || '').trim();
    const categoryName = newCat || catSelect;

    const server  = (getVal('f-server') || '').trim();
    const share   = (getVal('f-share')  || '').trim();
    const options = getVal('f-options');

    if (!selectedType)   { alert('Choisir un type de montage'); return null; }
    if (!server)         { alert('L\'adresse du serveur est requise'); return null; }
    if (!share)          { alert('Le partage / export est requis'); return null; }
    if (!categoryName)   { alert('Choisir ou créer une catégorie'); return null; }

    const base = {
      mount_type:    selectedType,
      category_name: categoryName,
      active: document.getElementById('f-active')?.checked ?? true,
    };

    if (selectedType === 'smb') {
      return { ...base, server, share,
        smb_options: options,
        username:    getVal('f-user')        || null,
        password:    getVal('f-password')    || null,
        domain:      getVal('f-domain')      || 'WORKGROUP',
        smb_version: getVal('f-smb-version') || '3.0' };
    }
    // nfs
    return { ...base, server,
      export_path: share,
      nfs_options: options,
      nfs_version: parseInt(getVal('f-nfs-version') || '4') };
  }

  async function saveMount() {
    const payload = buildPayload();
    if (!payload) return;

    const btn = document.getElementById('btn-save-mount');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Enregistrement…';

    try {
      const url    = editingId ? `${API}/api/admin/mounts/${editingId}` : `${API}/api/admin/mounts`;
      const method = editingId ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method,
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({detail: r.statusText}));
        throw new Error(JSON.stringify(err.detail ?? err));
      }
      closeOverlay('overlay-mount');
      await loadMounts();
      await loadCategories();
      // Rafraîchir aussi les stats du dashboard
      if (typeof loadDashboard === 'function') loadDashboard();
      showBanner('warn',
        '⚠ Modifications non appliquées',
        'Cliquer sur « Appliquer & Synchro » pour monter / démonter les partages.');
    } catch (e) {
      alert('Erreur : ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = 'Enregistrer';
    }
  }

  /* ── Suppression ──────────────────────────────────────────────────────── */
  function _openDelete(id) {
    const m = allMounts.find(x => x.id === id);
    if (!m) return;
    deletingId = id;
    document.getElementById('confirm-detail').textContent =
      `${m.id} - ${m.category_name}  (${m.server}${m.share || m.export_path || ''})`;
    openOverlay('overlay-confirm');
  }

  async function confirmDelete() {
    if (!deletingId) return;
    const btn = document.getElementById('btn-confirm-delete');
    btn.disabled = true;
    try {
      const r = await fetch(`${API}/api/admin/mounts/${deletingId}`, {method: 'DELETE'});
      if (!r.ok && r.status !== 204) throw new Error(await r.text());
      closeOverlay('overlay-confirm');
      deletingId = null;
      await loadMounts();
      showBanner('warn', '⚠ Suppression non appliquée',
        'Cliquer sur « Appliquer & Synchro » pour démonter le partage.');
    } catch (e) {
      alert('Erreur : ' + e.message);
    } finally {
      btn.disabled = false;
    }
  }

  /* ── Sync ─────────────────────────────────────────────────────────────── */
  async function sync() {
    const btn = document.getElementById('btn-sync');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Synchronisation…';
    try {
      const r = await fetch(`${API}/api/admin/mounts/sync`, {method: 'POST'});
      const d = await r.json();
      showBanner(d.success ? 'ok' : 'error',
        d.success ? '✓ Synchronisation réussie' : '⚠ Synchronisation avec erreurs',
        d.summary ?? '');
      await loadMounts();
      if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
      showBanner('error', '✗ Erreur sync', e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '⚡ Appliquer & Synchro';
    }
  }

  async function refresh() {
    try {
      const r = await fetch(`${API}/api/admin/mounts/status`);
      const d = await r.json();
      for (const s of d.mounts ?? []) {
        const cell = document.querySelector(`tr[data-id="${s.id}"] td:nth-child(6)`);
        if (cell) cell.innerHTML = mountedBadge(s.is_mounted);
      }
      updateStats();
    } catch (e) {
      showBanner('error', 'Actualisation échouée', e.message);
    }
  }

  /* ── Bannière ─────────────────────────────────────────────────────────── */
  function showBanner(type, title, detail) {
    const el = document.getElementById('sync-banner');
    if (!el) return;
    el.className = `sync-banner show ${type === 'ok' ? 'ok' : type === 'error' ? 'err' : 'warn'}`;
    el.innerHTML = `<div class="sync-banner-text">
      <strong>${title}</strong>${detail ? `<span>${esc(detail)}</span>` : ''}
    </div>`;
  }

  /* ── Overlays ─────────────────────────────────────────────────────────── */
  function openOverlay(id)  { document.getElementById(id)?.classList.add('show'); }
  function closeOverlay(id) { document.getElementById(id)?.classList.remove('show'); }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function setText(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }
  function getVal(id)     { return document.getElementById(id)?.value ?? ''; }
  function setVal(id, v)  { const el = document.getElementById(id); if (el) el.value = v; }
  function cap(s)         { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── API publique ─────────────────────────────────────────────────────── */
  return {
    init, sync, refresh,
    _filterCat, _openAdd, _openEdit, _openDelete,
    _browse, _clearBrowse, _pickShare,
    _toggleCollapse,_togglePassword,
    selectType: (t) => selectType(t),
    save:          saveMount,    
    confirmDelete,
    closeMount:    () => closeOverlay('overlay-mount'),
    closeConfirm:  () => closeOverlay('overlay-confirm'),
  };
})();