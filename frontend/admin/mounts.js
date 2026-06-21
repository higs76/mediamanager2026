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

  // État du wizard
  let _wizardStep      = 1;
  let _wizardType      = 'smb';
  let _wizardShares    = [];   // partages découverts
  let _wizardSelected  = [];   // [{share, category_name}]
  let _wizardKnownServers = [];

  /* ── Définition des types de montage (pour édition) ──────────────────── */
  const TYPES = {
    smb: {
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
            <input id="f-share" type="text" placeholder="/series">
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
          <div class="form-group mt-8">
            <label class="form-label">Options de montage</label>
            <input id="f-options" type="text"
                   value="uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8">
          </div>
        </div>`
    },
    nfs: {
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
          <div class="form-group mt-8">
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

  async function _loadKnownServers() {
    try {
      const r = await fetch(`${API}/api/admin/mounts/known-servers`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      _wizardKnownServers = await r.json();
    } catch (_) {
      _wizardKnownServers = [];
    }
    _renderKnownServersSelect();
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
    // Select du modal édition
    const sel = document.getElementById('f-cat-select');
    if (sel) {
      const cur = sel.value;
      sel.innerHTML = '<option value="">— Choisir —</option>'
        + _categories.map(c => `<option value="${_esc(c)}">${_cap(c)}</option>`).join('');
      if (cur) sel.value = cur;
    }
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
        <i class="bi bi-hdd-x empty-state-icon"></i>
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
        <td class="td-path">${source}</td>
        <td class="td-mono" title="${_esc(m.local_path)}">
          …/${_esc(m.local_path.split('/MediaManagerMnt/').pop() ?? m.local_path)}
        </td>
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

  /* ══════════════════════════════════════════════════════════════════════════
     WIZARD — Ajout multi-montages
  ══════════════════════════════════════════════════════════════════════════ */

  function _openAdd() {
    _wizardStep     = 1;
    _wizardType     = 'smb';
    _wizardShares   = [];
    _wizardSelected = [];
    _wizardGoToStep(1);
    _loadKnownServers();
    _openOverlay('overlay-mount');
  }

  function _renderKnownServersSelect() {
    const sel = document.getElementById('w-known-server');
    if (!sel) return;
    sel.innerHTML = '<option value="">— Nouveau serveur —</option>'
      + _wizardKnownServers.map(s =>
          `<option value="${s.id}">${_esc(s.server)} (${s.mount_type.toUpperCase()})</option>`
        ).join('');
  }

  function wizardLoadKnown() {
    const sel = document.getElementById('w-known-server');
    const id  = parseInt(sel?.value);
    if (!id) return;
    const s = _wizardKnownServers.find(x => x.id === id);
    if (!s) return;
    // Pré-remplir les champs
    wizardSelectType(s.mount_type);
    _setVal('w-server',      s.server      ?? '');
    _setVal('w-username',    s.username     ?? '');
    _setVal('w-domain',      s.domain       ?? 'WORKGROUP');
    _setVal('w-smb-version', s.smb_version  ?? '3.0');
    _setVal('w-nfs-server',  s.server       ?? '');
    _setVal('w-nfs-version', String(s.nfs_version ?? 4));
    // Note : le password n'est pas pré-rempli pour la sécurité
    // mais on indique qu'il est mémorisé
    const pwdField = document.getElementById('w-password');
    if (pwdField) pwdField.placeholder = '(mémorisé — laisser vide pour garder)';
  }

  function wizardSelectType(type) {
    _wizardType = type;
    document.getElementById('wtype-smb')?.classList.toggle('active', type === 'smb');
    document.getElementById('wtype-nfs')?.classList.toggle('active', type === 'nfs');
    document.getElementById('wfields-smb').classList.toggle('hidden', type !== 'smb');
    document.getElementById('wfields-nfs').classList.toggle('hidden', type !== 'nfs');
  }

  function _wizardGoToStep(step) {
    _wizardStep = step;
    // Panels
    for (let i = 1; i <= 3; i++) {
      document.getElementById(`wizard-step-${i}`)?.classList.toggle('active', i === step);
    }
    // Indicateurs
    document.querySelectorAll('.wizard-step').forEach(el => {
      const s = parseInt(el.dataset.step);
      el.classList.toggle('active', s === step);
      el.classList.toggle('done',   s < step);
    });
    // Boutons footer
    const btnPrev = document.getElementById('btn-wizard-prev');
    const btnNext = document.getElementById('btn-wizard-next');
    if (btnPrev) btnPrev.classList.toggle('hidden', step <= 1);
    if (btnNext) {
      if (step === 3) {
        btnNext.innerHTML = '<i class="bi bi-check2"></i> Ajouter les montages';
        btnNext.className = 'btn btn-success';
      } else {
        btnNext.innerHTML = 'Suivant <i class="bi bi-arrow-right"></i>';
        btnNext.className = 'btn btn-primary';
      }
    }
    // Cacher erreur générale
    const errEl = document.getElementById('modal-mount-error');
    if (errEl) { errEl.classList.add('hidden'); errEl.textContent = ''; }
  }

  function _wizardShowError(step, msg) {
    const el = document.getElementById(`wizard-step${step}-error`);
    if (el) { el.textContent = msg; el.classList.remove('hidden'); }
  }

  function _wizardClearError(step) {
    const el = document.getElementById(`wizard-step${step}-error`);
    if (el) { el.classList.add('hidden'); el.textContent = ''; }
  }

  async function wizardNext() {
    _wizardClearError(_wizardStep);

    if (_wizardStep === 1) {
      // Valider étape 1
      const server = _wizardType === 'smb'
        ? (_getVal('w-server') || '').trim()
        : (_getVal('w-nfs-server') || '').trim();
      if (!server) {
        _wizardShowError(1, 'L\'adresse du serveur est obligatoire');
        return;
      }
      _wizardGoToStep(2);
      // Lancer le browse automatiquement
      await wizardBrowse();

    } else if (_wizardStep === 2) {
      // Valider étape 2 : au moins un partage sélectionné avec une catégorie
      _wizardCollectSelected();
      if (_wizardSelected.length === 0) {
        _wizardShowError(2, 'Sélectionner au moins un partage');
        return;
      }
      const missing = _wizardSelected.find(s => !s.category_name);
      if (missing) {
        _wizardShowError(2, `Choisir une catégorie pour : ${missing.share}`);
        return;
      }
      _wizardGoToStep(3);
      _wizardRenderSummary();

    } else if (_wizardStep === 3) {
      await _wizardSubmit();
    }
  }

  function wizardPrev() {
    if (_wizardStep > 1) _wizardGoToStep(_wizardStep - 1);
  }

  async function wizardBrowse() {
    const btn = document.getElementById('btn-browse');
    const grid = document.getElementById('wizard-shares-grid');
    if (!grid) return;

    const server = _wizardType === 'smb'
      ? (_getVal('w-server') || '').trim()
      : (_getVal('w-nfs-server') || '').trim();

    if (!server) {
      _wizardShowError(1, 'Saisir l\'adresse du serveur d\'abord');
      _wizardGoToStep(1);
      return;
    }

    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Scan…'; }
    grid.innerHTML = '<div class="wizard-shares-msg"><span class="spinner"></span> Recherche des partages…</div>';

    const user = _getVal('w-username') || null;
    const pwd  = _getVal('w-password') || null;
    let url = `${API}/api/admin/mounts/browse?type=${_wizardType}&server=${encodeURIComponent(server)}`;
    if (user) url += `&username=${encodeURIComponent(user)}`;
    if (pwd)  url += `&password=${encodeURIComponent(pwd)}`;

    try {
      const r = await fetch(url);
      const d = await r.json();

      if (d.error && !d.shares?.length) {
        grid.innerHTML = `<div class="wizard-shares-msg error">
          <i class="bi bi-exclamation-triangle"></i> ${_esc(d.error)}</div>`;
        return;
      }
      if (!d.shares?.length) {
        grid.innerHTML = '<div class="wizard-shares-msg ok">Aucun partage trouvé</div>';
        return;
      }

      _wizardShares = d.shares;
      _wizardRenderSharesGrid();

    } catch (e) {
      grid.innerHTML = `<div class="wizard-shares-msg error">
        <i class="bi bi-wifi-off"></i> ${_esc(e.message)}</div>`;
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-search"></i> Scanner les partages'; }
    }
  }

  function _wizardRenderSharesGrid() {
    const grid = document.getElementById('wizard-shares-grid');
    if (!grid) return;

    // Partages déjà configurés (pour les griser)
    const existingSources = new Set(
      _allMounts.map(m => `${(m.server||'').toLowerCase()}${(m.share||m.export_path||'').toLowerCase()}`)
    );

    const server = _wizardType === 'smb'
      ? (_getVal('w-server') || '').trim().toLowerCase()
      : (_getVal('w-nfs-server') || '').trim().toLowerCase();

    const catOptions = '<option value="">— Choisir —</option>'
      + _categories.map(c => `<option value="${_esc(c)}">${_cap(c)}</option>`).join('');

    grid.innerHTML = `
      <div class="shares-grid-row shares-grid-header">
        <span></span>
        <span>Partage</span>
        <span>Catégorie</span>
      </div>
      ${_wizardShares.map((share, i) => {
        const key      = `${server}${share.toLowerCase()}`;
        const disabled = existingSources.has(key);
        return `<div class="shares-grid-row${disabled ? ' disabled' : ''}" id="share-row-${i}">
          <input type="checkbox" id="share-cb-${i}"
                 ${disabled ? 'disabled checked' : ''}
                 onchange="Mounts._wizardToggleShare(${i})">
          <label for="share-cb-${i}" class="share-label">
            ${_esc(share)}
            ${disabled ? '<span class="share-already">déjà configuré</span>' : ''}
          </label>
          <select id="share-cat-${i}" ${disabled ? 'disabled' : ''}
                  class="share-select"
                  onchange="Mounts._wizardCatChange(${i})">
            ${catOptions}
          </select>
        </div>`;
      }).join('')}`;
  }

  function _wizardToggleShare(i) {
    // Rien de spécial — on lit l'état au moment de valider
  }

  function _wizardCatChange(i) {
    // Coche automatiquement la case si on choisit une catégorie
    const cb = document.getElementById(`share-cb-${i}`);
    const sel = document.getElementById(`share-cat-${i}`);
    if (cb && sel?.value) cb.checked = true;
  }

  function _wizardCollectSelected() {
    _wizardSelected = [];
    _wizardShares.forEach((share, i) => {
      const cb  = document.getElementById(`share-cb-${i}`);
      const sel = document.getElementById(`share-cat-${i}`);
      if (cb?.checked && !cb.disabled) {
        _wizardSelected.push({
          share,
          category_name: sel?.value || '',
        });
      }
    });
  }

  function _wizardRenderSummary() {
    const div = document.getElementById('wizard-summary');
    if (!div) return;

    const server = _wizardType === 'smb'
      ? (_getVal('w-server') || '').trim()
      : (_getVal('w-nfs-server') || '').trim();

    div.innerHTML = _wizardSelected.map(s => `
      <div class="summary-row">
        <i class="bi bi-folder2 text-blue"></i>
        <span class="summary-share">${_esc(server)}${_esc(s.share)}</span>
        <span class="summary-arrow">→</span>
        <span class="summary-cat"><i class="bi bi-collection"></i> ${_cap(_esc(s.category_name))}</span>
      </div>
    `).join('');
  }

  async function _wizardSubmit() {
    const btnNext = document.getElementById('btn-wizard-next');
    if (btnNext) { btnNext.disabled = true; btnNext.innerHTML = '<span class="spinner"></span> Enregistrement…'; }

    const server = _wizardType === 'smb'
      ? (_getVal('w-server') || '').trim()
      : (_getVal('w-nfs-server') || '').trim();

    const serverInfo = {
      server,
      mount_type:  _wizardType,
      username:    _getVal('w-username')    || null,
      password:    _getVal('w-password')    || null,
      domain:      _getVal('w-domain')      || 'WORKGROUP',
      smb_version: _getVal('w-smb-version') || '3.0',
      nfs_version: parseInt(_getVal('w-nfs-version') || '4'),
    };

    const payload = {
      server_info: serverInfo,
      mounts: _wizardSelected.map(s => ({
        share:         s.share,
        category_name: s.category_name,
      })),
    };

    try {
      const r = await fetch(`${API}/api/admin/mounts/batch`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const d = await r.json();

      if (!r.ok) {
        const errEl = document.getElementById('modal-mount-error');
        if (errEl) {
          errEl.textContent = d.detail ?? JSON.stringify(d);
          errEl.classList.add('visible');
        }
        return;
      }

      _closeOverlay('overlay-mount');
      await Promise.all([_loadMounts(), _loadCategories()]);

      const nb = d.created?.length ?? 0;
      const errs = d.errors?.length ?? 0;
      let msg = `${nb} montage${nb > 1 ? 's' : ''} ajouté${nb > 1 ? 's' : ''}`;
      if (errs) msg += ` — ${errs} erreur${errs > 1 ? 's' : ''} (voir console)`;
      if (errs) console.warn('Erreurs batch:', d.errors);

      _showBanner('warn',
        '<i class="bi bi-exclamation-triangle"></i> ' + msg,
        'Cliquer sur « Appliquer & Synchro » pour monter les partages.');

    } catch (e) {
      const errEl = document.getElementById('modal-mount-error');
      if (errEl) { errEl.textContent = e.message; errEl.classList.add('visible'); }
    } finally {
      if (btnNext) { btnNext.disabled = false; btnNext.innerHTML = '<i class="bi bi-check2"></i> Ajouter les montages'; }
    }
  }

  async function wizardAddCategory() {
    openCategoryModal(() => {
      _wizardRefreshCatSelects();
    });
  }

  function _wizardRefreshCatSelects() {
    // Mettre à jour tous les selects de la grille sans la re-rendre entièrement
    const catOptions = '<option value="">— Choisir —</option>'
      + _categories.map(c => `<option value="${_esc(c)}">${_cap(c)}</option>`).join('');
    _wizardShares.forEach((_, i) => {
      const sel = document.getElementById(`share-cat-${i}`);
      if (sel && !sel.disabled) {
        const cur = sel.value;
        sel.innerHTML = catOptions;
        if (cur) sel.value = cur;
      }
    });
  }

  /* ══════════════════════════════════════════════════════════════════════════
     ÉDITION — modal simple (overlay-edit-mount)
  ══════════════════════════════════════════════════════════════════════════ */

  function _openEdit(id) {
    const m = _allMounts.find(x => x.id === id);
    if (!m) return;
    _editingId = id;
    _selType   = m.mount_type || 'smb';
    _resetEditForm();
    selectType(_selType);
    _fillForm(m);
    _renderCategorySelect();
    // Bloquer le changement de type en édition
    document.querySelectorAll('#overlay-edit-mount .type-card').forEach(c => {
      c.classList.add('type-locked');
      c.classList.toggle('type-dim', c.dataset.type !== _selType);
    });
    _openOverlay('overlay-edit-mount');
  }

  function _resetEditForm() {
    const errEl = document.getElementById('modal-edit-error');
    if (errEl) { errEl.classList.remove('visible'); errEl.textContent = ''; }
    const active = document.getElementById('f-active');
    if (active) active.checked = true;
    _setVal('f-cat-select', '');
    _setVal('f-newcat', '');
    const tf = document.getElementById('type-fields');
    if (tf) { tf.innerHTML = ''; tf.classList.remove('show'); }
    document.querySelectorAll('#overlay-edit-mount .type-card').forEach(c => {
      c.classList.remove('selected', 'type-locked', 'type-dim');
    });
  }

  function selectType(type) {
    _selType = type;
    document.querySelectorAll('#overlay-edit-mount .type-card').forEach(c =>
      c.classList.toggle('selected', c.dataset.type === type)
    );
    const def = TYPES[type];
    if (!def) return;
    const section = document.getElementById('type-fields');
    if (section) { section.innerHTML = def.fields(); section.classList.add('show'); }
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

  function _buildPayload() {
    const catSelect    = document.getElementById('f-cat-select')?.value || '';
    const newCat       = (document.getElementById('f-newcat')?.value || '').trim();
    const categoryName = newCat || catSelect;
    const server       = (_getVal('f-server') || '').trim();
    const share        = (_getVal('f-share')  || '').trim();
    const options      = _getVal('f-options');

    if (!_selType)     { alert('Choisir un type de montage');        return null; }
    if (!server)       { alert('L\'adresse du serveur est requise'); return null; }
    if (!share)        { alert('Le partage / export est requis');    return null; }
    if (!categoryName) { alert('Choisir ou créer une catégorie');    return null; }

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

  async function saveEdit() {
    const payload = _buildPayload();
    if (!payload) return;

    const btn = document.getElementById('btn-save-edit');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Enregistrement…'; }

    try {
      const r = await fetch(`${API}/api/admin/mounts/${_editingId}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({detail: r.statusText}));
        throw new Error(JSON.stringify(err.detail ?? err));
      }
      _closeOverlay('overlay-edit-mount');
      await Promise.all([_loadMounts(), _loadCategories()]);
      _showBanner('warn',
        '<i class="bi bi-exclamation-triangle"></i> Modifications non appliquées',
        'Cliquer sur « Appliquer & Synchro » pour appliquer les changements.');
    } catch (e) {
      const errEl = document.getElementById('modal-edit-error');
      if (errEl) {
        let msg = e.message;
        try { msg = JSON.parse(e.message); } catch (_) {}
        errEl.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg);
        errEl.classList.add('visible');
      } else {
        alert('Erreur : ' + e.message);
      }
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-check2"></i> Enregistrer'; }
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

  /* ── Password toggle (édition) ────────────────────────────────────────── */
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

  /* ── Browse réseau (édition) ──────────────────────────────────────────── */
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

  function _pickShare(share) { _setVal('f-share', share); _clearBrowse(); }
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

  /* ── Bannière ─────────────────────────────────────────────────────────── */
  function _showBanner(type, title, detail) {
    const el = document.getElementById('sync-banner');
    if (!el) return;
    const cls = type === 'ok' ? '' : type === 'error' ? 'error' : 'warn';
    el.className = `alert ${cls}`;
    el.classList.remove('hidden');
    el.innerHTML = `<div><strong>${title}</strong>${detail
      ? `<br><span class="banner-detail">${_esc(detail)}</span>`
      : ''}</div>`;
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

  /* ══════════════════════════════════════════════════════════════════════════
     MODAL — Création de catégorie
  ══════════════════════════════════════════════════════════════════════════ */

  let _newcatType      = 'seasonal';
  let _newcatTemplates = [];

  async function openCategoryModal() {
    _newcatType = 'seasonal';
    _setVal('newcat-name', '');
    const errEl = document.getElementById('newcat-error');
    if (errEl) { errEl.classList.add('hidden'); errEl.textContent = ''; }
    document.getElementById('newcat-tpl-form').classList.add('hidden');
    document.getElementById('newcat-tpl-readonly').classList.remove('hidden');

    try {
      const r = await fetch(`${API}/api/admin/naming-templates`);
      _newcatTemplates = await r.json();
    } catch(e) { _newcatTemplates = []; }

    newcatSelectType('seasonal');
    _openOverlay('overlay-new-category');
    setTimeout(() => document.getElementById('newcat-name')?.focus(), 100);
  }

  function closeCategoryModal() {
    _closeOverlay('overlay-new-category');
  }

  function newcatSelectType(type) {
    _newcatType = type;
    document.getElementById('newcat-type-seasonal')
      ?.classList.toggle('active', type === 'seasonal');
    document.getElementById('newcat-type-noseasonal')
      ?.classList.toggle('active', type === 'noseasonal');
    document.getElementById('newcat-fields-seasonal').classList.toggle('hidden', type !== 'seasonal');
    document.getElementById('newcat-fields-noseasonal').classList.toggle('hidden', type !== 'noseasonal');
    document.getElementById('newcat-prev-special-row').classList.toggle('hidden', type !== 'seasonal');
    document.getElementById('newcat-prev-bonus-row').classList.toggle('hidden', type !== 'noseasonal');
    _newcatRebuildSelect();
  }

  function _newcatRebuildSelect() {
    const sel = document.getElementById('newcat-template');
    if (!sel) return;
    const filtered = _newcatTemplates.filter(t => t.type === _newcatType);
    const defGroup = filtered.filter(t => t.is_default);
    const usrGroup = filtered.filter(t => !t.is_default);
    let html = '<optgroup label="Par défaut (lecture seule)">'
      + defGroup.map(t => `<option value="${t.id}">🔒 ${_esc(t.preview)}</option>`).join('')
      + '</optgroup>';
    if (usrGroup.length) {
      html += '<optgroup label="Mes templates">'
        + usrGroup.map(t => `<option value="${t.id}">✏️ ${_esc(t.preview)}</option>`).join('')
        + '</optgroup>';
    }
    sel.innerHTML = html;
    newcatSelTpl();
  }

  function newcatSelTpl() {
    const sel = document.getElementById('newcat-template');
    if (!sel) return;
    const tpl = _newcatTemplates.find(t => t.id === parseInt(sel.value));
    const isDefault = tpl?.is_default ?? true;
    document.getElementById('newcat-tpl-readonly').classList.toggle('hidden', !isDefault);
    if (isDefault) document.getElementById('newcat-tpl-form').classList.add('hidden');
    // Mettre à jour l'aperçu depuis le template sélectionné
    if (tpl) _newcatPreviewFromTpl(tpl);
  }

  function newcatToggleForm() {
    const form = document.getElementById('newcat-tpl-form');
    const ro   = document.getElementById('newcat-tpl-readonly');
    const showing = !form.classList.contains('hidden');
    form.classList.toggle('hidden', showing);
    ro.classList.toggle('hidden', !showing);
    if (!showing) newcatUpdPrev();
  }

  function _pad(n, d) { return String(n).padStart(parseInt(d), '0'); }

  function _newcatPreviewFromTpl(tpl) {
    if (tpl.type === 'seasonal') {
      const sep1  = tpl.sep1 || ' - ';
      const sep2  = tpl.sep2 || ' - ';
      const prefS = tpl.prefix_season || '';
      const digS  = tpl.digits_season || 2;
      const sepSE = tpl.sep_se || 'x';
      const prefE = tpl.prefix_episode || '';
      const digE  = tpl.digits_episode || 2;
      const spec  = tpl.special_folder || 'S0';
      const s1 = _pad(1, digS); const e1 = _pad(1, digE);
      const s0 = _pad(0, digS); const e161 = _pad(161, digE);
      const num  = `${prefS}${s1}${sepSE}${prefE}${e1}`;
      const num0 = `${prefS}${s0}${sepSE}${prefE}${e161}`;
      _set('newcat-prev-normal',  `Scorpion${sep1}${num}${sep2}Pilot.mkv`);
      _set('newcat-prev-special', `${spec}/Scorpion${sep1}${num0}${sep2}Le pouvoir du docteur.mkv`);
    } else {
      const sep   = tpl.sep_year || ' ';
      const fmt   = tpl.year_format || 'paren';
      const bonus = tpl.bonus_folder || 'Bonus';
      const year  = fmt === 'paren' ? '(2010)' : fmt === 'plain' ? '2010' : '';
      _set('newcat-prev-normal', year ? `Inception${sep}${year}.mkv` : 'Inception.mkv');
      _set('newcat-prev-bonus',  `${bonus}/`);
    }
  }

  function newcatUpdPrev() {
    if (_newcatType === 'seasonal') {
      const sep1  = _getVal('nt-sep1')    || ' - ';
      const sep2  = _getVal('nt-sep2')    || ' - ';
      const prefS = _getVal('nt-pref-s')  || '';
      const digS  = _getVal('nt-dig-s')   || '2';
      const sepSE = _getVal('nt-sep-se')  || 'x';
      const prefE = _getVal('nt-pref-e')  || '';
      const digE  = _getVal('nt-dig-e')   || '2';
      const fPref = _getVal('nt-folder-pref') || 'S';
      const fDig  = _getVal('nt-folder-dig')  || '2';
      const spec  = _getVal('nt-special') || 'S0';
      const s1 = _pad(1, digS); const e1 = _pad(1, digE);
      const s0 = _pad(0, digS); const e161 = _pad(161, digE);
      const num  = `${prefS}${s1}${sepSE}${prefE}${e1}`;
      const num0 = `${prefS}${s0}${sepSE}${prefE}${e161}`;
      _set('newcat-prev-normal',  `Scorpion${sep1}${num}${sep2}Pilot.mkv`);
      _set('newcat-prev-special', `${spec}/Scorpion${sep1}${num0}${sep2}Le pouvoir du docteur.mkv`);
    } else {
      const sep   = _getVal('nt-sep-year')  || ' ';
      const fmt   = _getVal('nt-fmt-year')  || 'paren';
      const bonus = _getVal('nt-bonus')     || 'Bonus';
      const year  = fmt === 'paren' ? '(2010)' : fmt === 'plain' ? '2010' : '';
      _set('newcat-prev-normal', year ? `Inception${sep}${year}.mkv` : 'Inception.mkv');
      _set('newcat-prev-bonus',  `${bonus}/`);
    }
  }

  async function newcatSaveTpl() {
    const payload = _newcatType === 'seasonal' ? {
      type:           'seasonal',
      sep1:           _getVal('nt-sep1'),
      sep2:           _getVal('nt-sep2'),
      prefix_season:  _getVal('nt-pref-s'),
      digits_season:  parseInt(_getVal('nt-dig-s')),
      sep_se:         _getVal('nt-sep-se'),
      prefix_episode: _getVal('nt-pref-e'),
      digits_episode: parseInt(_getVal('nt-dig-e')),
      folder_prefix:  _getVal('nt-folder-pref'),
      folder_digits:  parseInt(_getVal('nt-folder-dig')),
      special_folder: _getVal('nt-special'),
    } : {
      type:        'noseasonal',
      sep_year:    _getVal('nt-sep-year'),
      year_format: _getVal('nt-fmt-year'),
      bonus_folder:_getVal('nt-bonus'),
    };

    try {
      const r = await fetch(`${API}/api/admin/naming-templates`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail ?? JSON.stringify(d));

      // Recharger les templates et sélectionner le nouveau
      const r2 = await fetch(`${API}/api/admin/naming-templates`);
      _newcatTemplates = await r2.json();
      _newcatRebuildSelect();
      // Sélectionner le nouveau template
      document.getElementById('newcat-template').value = d.id;
      newcatSelTpl();
      document.getElementById('newcat-tpl-form').classList.add('hidden');

    } catch(e) {
      const errEl = document.getElementById('newcat-error');
      if (errEl) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
    }
  }

  async function saveNewCategory() {
    const name  = (_getVal('newcat-name') || '').trim().toLowerCase();
    const errEl = document.getElementById('newcat-error');
    if (errEl) { errEl.classList.add('hidden'); errEl.textContent = ''; }

    if (!name) {
      if (errEl) { errEl.textContent = 'Le nom est obligatoire'; errEl.classList.remove('hidden'); }
      return;
    }

    const templateId = parseInt(document.getElementById('newcat-template')?.value) || null;

    try {
      const r = await fetch(`${API}/api/admin/categories`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          name,
          has_seasons: _newcatType === 'seasonal',
          template_id: templateId,
        }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail ?? JSON.stringify(d));

      if (!_categories.includes(name)) {
        _categories.push(name);
        _categories.sort();
      }
      _renderCategorySelect();
      _wizardRefreshCatSelects();
      closeCategoryModal();

    } catch(e) {
      if (errEl) { errEl.textContent = e.message; errEl.classList.remove('hidden'); }
    }
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  /* ── API publique ─────────────────────────────────────────────────────── */
  return {
    init, sync, refresh, confirmDelete,
    selectType,
    saveEdit,
    _filterCat, _openAdd, _openEdit, _openDelete,
    _browse, _clearBrowse, _pickShare,
    _toggleCollapse, _togglePwd,
    // Wizard
    wizardNext, wizardPrev, wizardBrowse,
    wizardLoadKnown, wizardSelectType, wizardAddCategory,
    _wizardToggleShare, _wizardCatChange,
    // Fermetures
    closeMount:     () => _closeOverlay('overlay-mount'),
    closeEditMount: () => _closeOverlay('overlay-edit-mount'),
    closeConfirm:   () => _closeOverlay('overlay-confirm'),
    // Catégorie modal
    openCategoryModal, closeCategoryModal,
    newcatSelectType, newcatSelTpl, newcatToggleForm,
    newcatUpdPrev, newcatSaveTpl, saveNewCategory,
  };
})();