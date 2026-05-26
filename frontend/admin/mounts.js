/* =============================================================================
   MediaManager 2026 — mounts.js
   Gestion des montages NAS — intégré dans le Dashboard
   ============================================================================= */

const Mounts = (() => {

  /* ── État ─────────────────────────────────────────────────────────────── */
  let _allMounts  = [];
  let _categories = [];
  let _currentCat = 'all';
  let _editingId  = null;
  let _deletingId = null;
  let _selType    = null;

  /* ── Définition des types de montage ──────────────────────────────────── */
  const TYPES = {
    smb: {
      icon: 'bi-server',
      name: 'SMB / CIFS',
      desc: 'NAS Synology, QNAP, Windows',
      fields: () => `
        <div class="section-sep">Partage réseau</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <div class="browse-row">
              <input id="f-server" type="text" placeholder="//192.168.1.4 ou //DS1821"
                     oninput="Mounts._clearBrowse()">
              <button type="button" class="btn btn-sm" onclick="Mounts._browse('smb')">
                <i class="bi bi-search"></i> Parcourir
              </button>
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
            <div class="pass-row">
              <input id="f-password" type="password">
              <button type="button" class="btn btn-sm" onclick="Mounts._togglePwd()" id="btn-eye">
                <i class="bi bi-eye" id="eye-icon"></i>
              </button>
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
              <option value="1.0">1.0 — vieux NAS</option>
            </select>
          </div>
        </div>
        <div class="collapsible-toggle" onclick="Mounts._toggleCollapse(this)">
          <div class="section-sep">Options avancées</div>
          <i class="bi bi-chevron-down collapse-icon"></i>
        </div>
        <div class="collapsible-body">
          <div class="form-group" style="margin-top:8px">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text"
                   value="uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8">
            <span class="form-hint">Options CIFS passées à mount -t cifs -o ...</span>
          </div>
        </div>`
    },
    nfs: {
      icon: 'bi-diagram-3',
      name: 'NFS',
      desc: 'NAS Linux, Synology NFS',
      fields: () => `
        <div class="section-sep">Export NFS</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <div class="browse-row">
              <input id="f-server" type="text" placeholder="192.168.1.4 ou nas1"
                     oninput="Mounts._clearBrowse()">
              <button type="button" class="btn btn-sm" onclick="Mounts._browse('nfs')">
                <i class="bi bi-search"></i> Parcourir
              </button>
            </div>
            <span class="form-hint">Sans // — NFS utilise l'IP directe</span>
            <div class="browse-results" id="browse-results"></div>
          </div>
          <div class="form-group">
            <label class="form-label">Export <span class="req">*</span></label>
            <input id="f-share" type="text" placeholder="/volume1/series">
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
          <i class="bi bi-chevron-down collapse-icon"></i>
        </div>
        <div class="collapsible-body">
          <div class="form-group" style="margin-top:8px">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text" value="rw,soft,timeo=30">
          </div>
        </div>`
    }
  };

  /* ── Init ─────────────────────────────────────────────────────────────── */
  async function init() {
    await Promise.all([_loadMounts(), _loadCategories()]);
  }

  /* ── Chargement ───────────────────────────────────────────────────────── */
  async function _loadMounts() {
    try {
      const r = await fetch(`${API}/api/admin/mounts`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _allMounts = d.mounts ?? [];
      _renderTable();
      _renderCategoryFilters();
      _syncDashStats();
    } catch (e) {
      _showBanner('error', e.message);
    }
  }

  async function _loadCategories() {
    try {
      const r = await fetch(`${API}/api/admin/categories`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _categories = d.categories ?? [];
    } catch (_) {
      _categories = [...new Set(_allMounts.map(m => m.category_name).filter(Boolean))];
    }
    _renderCategoryFilters();
    _renderCategorySelect();
  }

  /* ── Sync stats dashboard ─────────────────────────────────────────────── */
  function _syncDashStats() {
    const mounted = _allMounts.filter(m => m.is_mounted).length;
    const total   = _allMounts.length;
    const failed  = total - mounted;
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    setText('stat-mounts-up',    mounted);
    setText('stat-mounts-down',  failed);
    setText('stat-mounts-total', total);
    setText('stat-mounts-up2',   mounted);
    setText('stat-mounts-down2', failed);
    setText('stat-mounts-label', `${total} montage${total > 1 ? 's' : ''} configuré${total > 1 ? 's' : ''}`);
    const pct = total > 0 ? Math.round(mounted / total * 100) : 0;
    const bar = document.getElementById('stat-mounts-bar');
    if (bar) bar.style.width = pct + '%';
    // Catégories
    const cats = _categories.length ? _categories.join(', ') : '—';
    const catEl = document.getElementById('stat-categories-list');
    if (catEl) catEl.textContent = cats;
  }

  /* ── Filtres catégories ───────────────────────────────────────────────── */
  function _renderCategoryFilters() {
    const container = document.getElementById('cat-filters');
    if (!container) return;
    const cats = ['all', ..._categories];
    container.innerHTML = cats.map(cat => {
      const label = cat === 'all' ? 'Tous' : _cap(cat);
      return `<button class="tab-btn${cat === _currentCat ? ' active' : ''}"
        onclick="Mounts._filterCat(this,'${_esc(cat)}')">${label}</button>`;
    }).join('');
  }

  function _renderCategorySelect() {
    const sel = document.getElementById('f-cat-select');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">— Choisir —</option>'
      + _categories.map(c => `<option value="${_esc(c)}">${_cap(c)}</option>`).join('');
    if (cur) sel.value = cur;
  }

  function _filterCat(btn, cat) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    _currentCat = cat;
    _renderTable();
  }

  /* ── Table ────────────────────────────────────────────────────────────── */
  function _renderTable() {
    const filtered = _currentCat === 'all'
      ? _allMounts
      : _allMounts.filter(m => m.category_name === _currentCat);

    const tbody = document.getElementById('mounts-tbody');
    if (!tbody) return;

    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">
        <i class="bi bi-hdd-x" style="font-size:1.5rem;display:block;margin-bottom:8px"></i>
        Aucun montage${_currentCat !== 'all' ? ' pour cette catégorie' : ''}.
        Cliquer sur <strong>+ Ajouter</strong> pour commencer.
      </div></td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(m => {
      const source = m.mount_type === 'nfs'
        ? `${_esc(m.server ?? '')}${_esc(m.export_path ?? '')}`
        : `${_esc(m.server ?? '')}${_esc(m.share ?? '')}`;
      return `<tr data-id="${m.id}">
        <td class="td-name">${m.id} - ${_esc(m.category_name)}</td>
        <td><span class="badge badge-blue">${_esc(m.category_name)}</span></td>
        <td><span class="badge badge-muted">${(m.mount_type || 'smb').toUpperCase()}</span></td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:.82rem">${source}</td>
        <td class="td-mono" title="${_esc(m.local_path)}">${_esc(m.local_path)}</td>
        <td>${m.is_mounted
          ? '<span class="badge badge-success"><span class="dot"></span>Monté</span>'
          : '<span class="badge badge-danger"><span class="dot"></span>Non monté</span>'}</td>
        <td class="td-actions">
          <button class="btn-icon" onclick="Mounts._openEdit(${m.id})" title="Modifier">
            <i class="bi bi-pencil"></i>
          </button>
          <button class="btn-icon danger" onclick="Mounts._openDelete(${m.id})" title="Supprimer">
            <i class="bi bi-trash3"></i>
          </button>
        </td>
      </tr>`;
    }).join('');
  }

  /* ── Popup Ajout / Édition ────────────────────────────────────────────── */
  function _openAdd() {
    _editingId = null;
    _selType   = null;
    document.getElementById('modal-mount-title').textContent = 'Ajouter un montage';
    _resetForm();
    _renderCategorySelect();
    _openOverlay('overlay-mount');
  }

  function _openEdit(id) {
    const m = _allMounts.find(x => x.id === id);
    if (!m) return;
    _editingId = id;
    document.getElementById('modal-mount-title').textContent = 'Modifier le montage';
    _resetForm();
    selectType(m.mount_type || 'smb');
    _fillForm(m);
    _renderCategorySelect();
    // Bloquer le changement de type en édition
    document.querySelectorAll('.type-card').forEach(c => {
      const isSelected = c.dataset.type === m.mount_type;
      c.style.opacity       = isSelected ? '1' : '0.3';
      c.style.pointerEvents = 'none';
    });
    _openOverlay('overlay-mount');
  }

  function _resetForm() {
    _selType = null;
    const active = document.getElementById('f-active');
    if (active) active.checked = true;
    _setVal('f-cat-select', '');
    _setVal('f-newcat', '');
    document.getElementById('type-fields').innerHTML = '';
    document.getElementById('type-fields').classList.remove('show');
    document.querySelectorAll('.type-card').forEach(c => {
      c.classList.remove('selected');
      c.style.opacity = '1';
      c.style.pointerEvents = '';
    });
  }

  function selectType(type) {
    _selType = type;
    document.querySelectorAll('.type-card').forEach(c =>
      c.classList.toggle('selected', c.dataset.type === type)
    );
    const def = TYPES[type];
    if (!def) return;
    const section = document.getElementById('type-fields');
    section.innerHTML = def.fields();
    section.classList.add('show');
  }

  function _fillForm(m) {
    _setVal('f-server',      m.server         ?? '');
    _setVal('f-share',       m.share          ?? m.export_path ?? '');
    _setVal('f-user',        m.username       ?? '');
    _setVal('f-domain',      m.domain         ?? 'WORKGROUP');
    _setVal('f-smb-version', m.smb_version    ?? '3.0');
    _setVal('f-nfs-version', String(m.nfs_version ?? 4));
    _setVal('f-options',
      m.mount_type === 'nfs' ? (m.nfs_options ?? '') : (m.smb_options ?? ''));
    _setVal('f-cat-select', m.category_name ?? '');
    const act = document.getElementById('f-active');
    if (act) act.checked = m.active !== false;
  }

  /* ── Password toggle ──────────────────────────────────────────────────── */
  function _togglePwd() {
    const inp  = document.getElementById('f-password');
    const icon = document.getElementById('eye-icon');
    if (!inp) return;
    if (inp.type === 'password') {
      inp.type = 'text';
      icon?.classList.replace('bi-eye', 'bi-eye-slash');
    } else {
      inp.type = 'password';
      icon?.classList.replace('bi-eye-slash', 'bi-eye');
    }
  }

  /* ── Browse réseau ────────────────────────────────────────────────────── */
  async function _browse(type) {
    const server = (_getVal('f-server') || '').trim();
    if (!server) { alert('Saisir d\'abord l\'adresse du serveur'); return; }

    const box = document.getElementById('browse-results');
    if (!box) return;
    box.className = 'browse-results show';
    box.innerHTML = '<div class="browse-msg"><span class="spinner"></span> Recherche…</div>';

    const user = _getVal('f-user')     || null;
    const pwd  = _getVal('f-password') || null;
    let url = `${API}/api/admin/mounts/browse?type=${type}&server=${encodeURIComponent(server)}`;
    if (user) url += `&username=${encodeURIComponent(user)}`;
    if (pwd)  url += `&password=${encodeURIComponent(pwd)}`;

    try {
      const r = await fetch(url);
      const d = await r.json();
      if (d.error && !d.shares?.length) {
        box.innerHTML = `<div class="browse-msg browse-error"><i class="bi bi-exclamation-triangle"></i> ${_esc(d.error)}</div>`;
        return;
      }
      if (!d.shares?.length) {
        box.innerHTML = '<div class="browse-msg">Aucun partage trouvé</div>';
        return;
      }
      box.innerHTML = d.shares.map(s =>
        `<div class="browse-item" onclick="Mounts._pickShare('${_esc(s)}')">
          <i class="bi bi-folder2"></i>${_esc(s)}
        </div>`
      ).join('');
    } catch (e) {
      box.innerHTML = `<div class="browse-msg browse-error"><i class="bi bi-wifi-off"></i> ${_esc(e.message)}</div>`;
    }
  }

  function _pickShare(share) {
    _setVal('f-share', share);
    _clearBrowse();
  }

  function _clearBrowse() {
    const box = document.getElementById('browse-results');
    if (box) { box.className = 'browse-results'; box.innerHTML = ''; }
  }

  /* ── Collapse ─────────────────────────────────────────────────────────── */
  function _toggleCollapse(toggleEl) {
    toggleEl.classList.toggle('open');
    const body = toggleEl.nextElementSibling;
    if (body) body.classList.toggle('open');
  }

  /* ── Payload & Save ───────────────────────────────────────────────────── */
  function _buildPayload() {
    const catSelect  = document.getElementById('f-cat-select')?.value || '';
    const newCat     = (document.getElementById('f-newcat')?.value || '').trim();
    const categoryName = newCat || catSelect;
    const server  = (_getVal('f-server') || '').trim();
    const share   = (_getVal('f-share')  || '').trim();
    const options = _getVal('f-options');

    if (!_selType)     { alert('Choisir un type de montage');          return null; }
    if (!server)       { alert('L\'adresse du serveur est requise');   return null; }
    if (!share)        { alert('Le partage / export est requis');      return null; }
    if (!categoryName) { alert('Choisir ou créer une catégorie');      return null; }

    const base = {
      mount_type:    _selType,
      category_name: categoryName,
      active: document.getElementById('f-active')?.checked ?? true,
    };

    if (_selType === 'smb') {
      return { ...base, server, share,
        smb_options:  options,
        username:     _getVal('f-user')        || null,
        password:     _getVal('f-password')    || null,
        domain:       _getVal('f-domain')      || 'WORKGROUP',
        smb_version:  _getVal('f-smb-version') || '3.0' };
    }
    return { ...base, server,
      export_path: share,
      nfs_options: options,
      nfs_version: parseInt(_getVal('f-nfs-version') || '4') };
  }

  async function save() {
    const payload = _buildPayload();
    if (!payload) return;

    const btn = document.getElementById('btn-save-mount');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Enregistrement…';

    try {
      const url    = _editingId ? `${API}/api/admin/mounts/${_editingId}` : `${API}/api/admin/mounts`;
      const method = _editingId ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method, headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({detail: r.statusText}));
        throw new Error(JSON.stringify(err.detail ?? err));
      }
      _closeOverlay('overlay-mount');
      await Promise.all([_loadMounts(), _loadCategories()]);
      _showBanner('warn',
        '<i class="bi bi-exclamation-triangle"></i> Modifications non appliquées',
        'Cliquer sur « Appliquer & Synchro » pour monter / démonter les partages.');
    } catch (e) {
      alert('Erreur : ' + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-check2"></i> Enregistrer';
    }
  }

  /* ── Suppression ──────────────────────────────────────────────────────── */
  function _openDelete(id) {
    const m = _allMounts.find(x => x.id === id);
    if (!m) return;
    _deletingId = id;
    document.getElementById('confirm-detail').textContent =
      `${m.id} - ${m.category_name}  (${m.server}${m.share || m.export_path || ''})`;
    _openOverlay('overlay-confirm');
  }

  async function confirmDelete() {
    if (!_deletingId) return;
    const btn = document.getElementById('btn-confirm-delete');
    btn.disabled = true;
    try {
      const r = await fetch(`${API}/api/admin/mounts/${_deletingId}`, {method: 'DELETE'});
      if (!r.ok && r.status !== 204) throw new Error(await r.text());
      _closeOverlay('overlay-confirm');
      _deletingId = null;
      await _loadMounts();
      _showBanner('warn',
        '<i class="bi bi-exclamation-triangle"></i> Suppression non appliquée',
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
      _showBanner(
        d.success ? 'ok' : 'error',
        d.success
          ? '<i class="bi bi-check-circle"></i> Synchronisation réussie'
          : '<i class="bi bi-x-circle"></i> Synchronisation avec erreurs',
        d.summary ?? ''
      );
      await _loadMounts();
      if (typeof loadDashboard === 'function') loadDashboard();
    } catch (e) {
      _showBanner('error', '<i class="bi bi-x-circle"></i> Erreur sync', e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-lightning-charge"></i> Appliquer &amp; Synchro';
    }
  }

  async function refresh() {
    try {
      const r = await fetch(`${API}/api/admin/mounts/status`);
      const d = await r.json();
      for (const s of d.mounts ?? []) {
        const cell = document.querySelector(`tr[data-id="${s.id}"] td:nth-child(6)`);
        if (cell) cell.innerHTML = s.is_mounted
          ? '<span class="badge badge-success"><span class="dot"></span>Monté</span>'
          : '<span class="badge badge-danger"><span class="dot"></span>Non monté</span>';
      }
      _syncDashStats();
    } catch (e) {
      _showBanner('error', e.message);
    }
  }

  /* ── Bannière ─────────────────────────────────────────────────────────── */
  function _showBanner(type, title, detail) {
    const el = document.getElementById('sync-banner');
    if (!el) return;
    const cls = type === 'ok' ? '' : type === 'error' ? 'error' : 'warn';
    el.className = `alert ${cls}`;
    el.style.display = 'flex';
    el.innerHTML = `<div><strong>${title}</strong>${detail ? `<br><span style="font-size:.82rem;opacity:.8">${_esc(detail)}</span>` : ''}</div>`;
  }

  /* ── Overlays ─────────────────────────────────────────────────────────── */
  function _openOverlay(id)  { document.getElementById(id)?.classList.add('active'); }
  function _closeOverlay(id) { document.getElementById(id)?.classList.remove('active'); }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function _getVal(id)   { return document.getElementById(id)?.value ?? ''; }
  function _setVal(id,v) { const el = document.getElementById(id); if (el) el.value = v; }
  function _cap(s)       { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── API publique ─────────────────────────────────────────────────────── */
  return {
    init, sync, refresh, save, confirmDelete,
    selectType: (t) => selectType(t),
    _allMounts,
    _filterCat, _openAdd, _openEdit, _openDelete,
    _browse, _clearBrowse, _pickShare,
    _toggleCollapse, _togglePwd,
    closeMount:   () => _closeOverlay('overlay-mount'),
    closeConfirm: () => _closeOverlay('overlay-confirm'),
  };
})();