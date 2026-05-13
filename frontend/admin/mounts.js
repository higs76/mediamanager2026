/* =============================================================================
   MediaManager 2026 — mounts.js
   Gestion de l'onglet "Montages NAS"
   ============================================================================= */

const Mounts = (() => {

  /* ── État ─────────────────────────────────────────────────────────────── */
  let allMounts   = [];   // liste complète depuis l'API
  let categories  = [];   // catégories depuis la BDD
  let currentCat  = 'all';
  let editingId   = null;
  let deletingId  = null;
  let selectedType = null;

  /* ── Types de montage disponibles ─────────────────────────────────────── */
  // On propose les 3 types pertinents pour un usage NAS/media.
  // D'autres existent sous Linux (WebDAV, FTP via curlftpfs, bind mount...)
  // mais ils sont rares dans ce contexte.
  const MOUNT_TYPES = {
    smb: {
      icon: '🖥️',
      name: 'SMB / CIFS',
      desc: 'NAS Synology, QNAP, Windows',
      fields: `
        <div class="section-sep">Partage réseau</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <input id="f-server" type="text" placeholder="//192.168.1.10 ou //nas1">
          </div>
          <div class="form-group">
            <label class="form-label">Partage <span class="req">*</span></label>
            <input id="f-share" type="text" placeholder="/series ou /video">
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
            <input id="f-password" type="password">
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
        <div class="section-sep">Options avancées</div>
        <div class="form-group">
          <label class="form-label">Options de montage</label>
          <input id="f-options" type="text"
            value="uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8">
          <span class="form-hint">Options CIFS supplémentaires passées à mount -t cifs -o ...</span>
        </div>`
    },
    nfs: {
      icon: '🐧',
      name: 'NFS',
      desc: 'NAS Linux, Synology NFS',
      fields: `
        <div class="section-sep">Export NFS</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <input id="f-server" type="text" placeholder="192.168.1.10 ou nas1">
            <span class="form-hint">Sans les // — NFS utilise IP directe</span>
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
          <div class="form-group">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text" value="rw,soft,timeo=30">
          </div>
        </div>`
    },
    sshfs: {
      icon: '🔐',
      name: 'SSHFS',
      desc: 'Serveur Linux distant via SSH',
      fields: `
        <div class="section-sep">Connexion SSH</div>
        <div class="form-grid">
          <div class="form-group">
            <label class="form-label">Utilisateur SSH <span class="req">*</span></label>
            <input id="f-user" type="text" placeholder="admin">
          </div>
          <div class="form-group">
            <label class="form-label">Serveur <span class="req">*</span></label>
            <input id="f-server" type="text" placeholder="192.168.1.10 ou mon-serveur">
          </div>
          <div class="form-group">
            <label class="form-label">Port SSH</label>
            <input id="f-ssh-port" type="number" value="22">
          </div>
          <div class="form-group">
            <label class="form-label">Chemin distant <span class="req">*</span></label>
            <input id="f-share" type="text" placeholder="/home/media/series">
          </div>
          <div class="form-group form-full">
            <label class="form-label">Clé privée SSH</label>
            <input id="f-ssh-key" type="text" placeholder="/home/mediamanager/.ssh/id_rsa">
            <span class="form-hint">Laisser vide pour utiliser la clé par défaut (~/.ssh/id_rsa)</span>
          </div>
          <div class="form-group form-full">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text" value="reconnect,ServerAliveInterval=15,uid=1000,gid=1000">
          </div>
        </div>`
    }
  };

  /* ── Init ─────────────────────────────────────────────────────────────── */
  async function init() {
    await Promise.all([loadMounts(), loadCategories()]);
  }

  /* ── Chargement données ───────────────────────────────────────────────── */
  async function loadMounts() {
    try {
      const r = await fetch(`${API}/api/admin/mounts`);
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
      const d = await r.json();
      categories = d.categories ?? [];
    } catch (_) {
      // Fallback si l'endpoint n'existe pas encore
      categories = [...new Set(allMounts.map(m => m.category).filter(Boolean))];
    }
    renderCategoryFilters();
  }

  /* ── Stats ────────────────────────────────────────────────────────────── */
  function updateStats() {
    const mounted = allMounts.filter(m => m.is_mounted).length;
    setText2('stat-total',   allMounts.length);
    setText2('stat-mounted', mounted);
    setText2('stat-missing', allMounts.length - mounted);
  }

  /* ── Filtres catégories ───────────────────────────────────────────────── */
  function renderCategoryFilters() {
    const container = document.getElementById('cat-filters');
    const cats = ['all', ...categories];
    container.innerHTML = cats.map(cat => {
      const label = cat === 'all' ? 'Tous' : cat.charAt(0).toUpperCase() + cat.slice(1);
      return `<button class="cat-btn${cat === currentCat ? ' active' : ''}"
        onclick="Mounts._filterCat(this,'${cat}')">${label}</button>`;
    }).join('');
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
      : allMounts.filter(m => m.category === currentCat);

    const tbody = document.getElementById('mounts-tbody');
    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="7"><div class="empty-state">
        Aucun montage${currentCat !== 'all' ? ' pour cette catégorie' : ''}.
        Cliquez sur <strong>+ Ajouter</strong> pour commencer.
      </div></td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(m => `
      <tr data-id="${m.id}">
        <td>${esc2(m.name)}</td>
        <td><span class="badge badge-blue">${esc2(m.category)}</span></td>
        <td><span class="badge badge-muted">${esc2(m.mount_type || 'smb').toUpperCase()}</span></td>
        <td class="td-server">${esc2(m.server)}${esc2(m.share)}</td>
        <td class="td-mono" title="${esc2(m.local_path)}">${esc2(m.local_path)}</td>
        <td>${mountedBadge(m.is_mounted)}</td>
        <td>
          <div class="row-actions">
            <button class="icon-btn" onclick="Mounts._openEdit(${m.id})" title="Modifier">✏</button>
            <button class="icon-btn danger" onclick="Mounts._openDelete(${m.id})" title="Supprimer">🗑</button>
          </div>
        </td>
      </tr>`).join('');
  }

  function mountedBadge(ok) {
    return ok
      ? '<span class="badge badge-green"><span class="badge-dot"></span>Monté</span>'
      : '<span class="badge badge-red"><span class="badge-dot"></span>Non monté</span>';
  }

  /* ── Popup Ajout / Édition ────────────────────────────────────────────── */
  function _openAdd() {
    editingId    = null;
    selectedType = null;
    document.getElementById('modal-mount-title').textContent = 'Ajouter un montage';
    resetForm();
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
    openOverlay('overlay-mount');
  }

  function resetForm() {
    selectedType = null;
    document.getElementById('f-active').checked = true;
    document.getElementById('f-category').value = '';
    document.getElementById('f-newcat').value   = '';
    document.getElementById('type-fields').innerHTML = '';
    document.getElementById('type-fields').classList.remove('show');
    document.querySelectorAll('.type-card').forEach(c => c.classList.remove('selected'));
  }

  function selectType(type) {
    selectedType = type;
    document.querySelectorAll('.type-card').forEach(c => {
      c.classList.toggle('selected', c.dataset.type === type);
    });
    const def = MOUNT_TYPES[type];
    if (!def) return;
    const section = document.getElementById('type-fields');
    section.innerHTML = def.fields;
    section.classList.add('show');
  }

  function fillForm(m) {
    setVal('f-server',      m.server      ?? '');
    setVal('f-share',       m.share       ?? '');
    setVal('f-user',        m.smb_user    ?? '');
    setVal('f-domain',      m.smb_domain  ?? 'WORKGROUP');
    setVal('f-options',     m.mount_options ?? '');
    setVal('f-smb-version', m.smb_version ?? '3.0');
    setVal('f-nfs-version', m.nfs_version ?? '4');
    setVal('f-category',    m.category    ?? '');
    const act = document.getElementById('f-active');
    if (act) act.checked = m.active !== false;
  }

  function buildPayload() {
    const cat    = document.getElementById('f-cat-select')?.value;
    const newCat = document.getElementById('f-newcat')?.value.trim();
    const category = newCat || cat;

    const base = {
      mount_type: selectedType,
      category,
      active: document.getElementById('f-active')?.checked ?? true,
    };

    // Champs communs
    const server  = getVal('f-server');
    const share   = getVal('f-share');
    const options = getVal('f-options');

    if (!selectedType || !server || !share || !category) {
      alert('Remplir les champs obligatoires (*)');
      return null;
    }

    if (selectedType === 'smb') {
      return { ...base, server, share, mount_options: options,
        smb_user:     getVal('f-user'),
        smb_password: getVal('f-password'),
        smb_domain:   getVal('f-domain') || 'WORKGROUP',
        smb_version:  getVal('f-smb-version') || '3.0' };
    }
    if (selectedType === 'nfs') {
      return { ...base, server, share, mount_options: options,
        nfs_version: getVal('f-nfs-version') || '4' };
    }
    if (selectedType === 'sshfs') {
      return { ...base, server, share, mount_options: options,
        smb_user:    getVal('f-user'),
        ssh_port:    getVal('f-ssh-port') || '22',
        ssh_key:     getVal('f-ssh-key') };
    }
    return base;
  }

  async function saveMount() {
    const payload = buildPayload();
    if (!payload) return;

    // Ajouter la nouvelle catégorie en BDD si saisie
    const newCat = document.getElementById('f-newcat')?.value.trim();
    if (newCat && !categories.includes(newCat)) {
      try {
        await fetch(`${API}/api/admin/categories`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: newCat })
        });
      } catch (_) {}
    }

    const btn = document.getElementById('btn-save-mount');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Enregistrement…';

    try {
      const url    = editingId ? `${API}/api/admin/mounts/${editingId}` : `${API}/api/admin/mounts`;
      const method = editingId ? 'PUT' : 'POST';
      const r = await fetch(url, {
        method, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!r.ok) throw new Error(await r.text());

      closeOverlay('overlay-mount');
      await loadMounts();
      await loadCategories();
      showBanner('warn',
        '⚠ Modifications non appliquées',
        'Cliquez sur « Appliquer & Synchro » pour monter/démonter les partages.');
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
    document.getElementById('confirm-detail').textContent = `${m.name} — ${m.server}${m.share}`;
    openOverlay('overlay-confirm');
  }

  async function confirmDelete() {
    if (!deletingId) return;
    const btn = document.getElementById('btn-confirm-delete');
    btn.disabled = true;
    try {
      const r = await fetch(`${API}/api/admin/mounts/${deletingId}`, { method: 'DELETE' });
      if (!r.ok && r.status !== 204) throw new Error(await r.text());
      closeOverlay('overlay-confirm');
      await loadMounts();
      showBanner('warn',
        '⚠ Suppression non appliquée',
        'Cliquez sur « Appliquer & Synchro » pour démonter le partage.');
    } catch (e) {
      alert('Erreur : ' + e.message);
    } finally {
      btn.disabled = false;
      deletingId = null;
    }
  }

  /* ── Sync ─────────────────────────────────────────────────────────────── */
  async function syncMounts() {
    const btn = document.getElementById('btn-sync');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Synchronisation…';
    try {
      const r = await fetch(`${API}/api/admin/mounts/sync`, { method: 'POST' });
      const d = await r.json();
      showBanner(
        d.success ? 'ok' : 'error',
        d.success ? '✓ Synchronisation réussie' : '⚠ Synchronisation avec erreurs',
        d.summary ?? ''
      );
      await loadMounts();
    } catch (e) {
      showBanner('error', '✗ Erreur', e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '⚡ Appliquer & Synchro';
    }
  }

  async function refreshStatus() {
    try {
      const r = await fetch(`${API}/api/admin/mounts/status`);
      const d = await r.json();
      // Mettre à jour le badge is_mounted de chaque ligne sans tout recharger
      for (const s of d.mounts ?? []) {
        const cell = document.querySelector(`tr[data-id="${s.id}"] td:nth-child(6)`);
        if (cell) cell.innerHTML = mountedBadge(s.is_mounted);
      }
      updateStats();
    } catch (e) {
      showBanner('error', 'Actualisation échouée', e.message);
    }
  }

  /* ── Bannière sync ────────────────────────────────────────────────────── */
  function showBanner(type, title, detail) {
    const el = document.getElementById('sync-banner');
    el.className = `sync-banner show ${type === 'ok' ? 'ok' : type === 'error' ? 'err' : 'warn'}`;
    el.innerHTML = `
      <div class="sync-banner-text">
        <strong>${title}</strong>
        ${detail ? `<span>${detail}</span>` : ''}
      </div>`;
  }

  /* ── Overlays ─────────────────────────────────────────────────────────── */
  function openOverlay(id)  { document.getElementById(id).classList.add('show'); }
  function closeOverlay(id) { document.getElementById(id).classList.remove('show'); }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function setText2(id, v) { const el = document.getElementById(id); if (el) el.textContent = v; }
  function getVal(id)  { return document.getElementById(id)?.value ?? ''; }
  function setVal(id, v) { const el = document.getElementById(id); if (el) el.value = v; }
  function esc2(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ── API publique ─────────────────────────────────────────────────────── */
  return {
    init,
    // exposé pour les onclick HTML
    _filterCat,
    _openAdd,
    _openEdit,
    _openDelete,
    selectType: (t) => selectType(t),
    save:       saveMount,
    confirmDelete,
    sync:        syncMounts,
    refresh:     refreshStatus,
    closeMount:  () => closeOverlay('overlay-mount'),
    closeConfirm:() => closeOverlay('overlay-confirm'),
    MOUNT_TYPES,
  };
})();