/* =============================================================================
   MediaManager 2026 — config.js
   Gestion de la configuration — regroupée par domaine fonctionnel
   ============================================================================= */

const Config = (() => {

  let _data = [];

  // Regroupement thématique — l'ordre des clés dans chaque section est
  // volontaire (pas alphabétique). Toute clé absente d'ici atterrit dans
  // une section "Autres" en filet de sécurité (voir _render).
  const SECTIONS = [
    { title: 'Scan', icon: 'bi-search',
      keys: ['scan_interval_hours', 'video_extensions', 'scan_excluded_dirs', 'scan_trash_dirs'] },
    { title: 'Analyse', icon: 'bi-cpu',
      keys: ['analyze_auto', 'analyze_workers', 'analyze_session_size'] },
    { title: 'Catalogue & renommage', icon: 'bi-tags',
      keys: ['catalog_interval_hours', 'catalog_tech_tags', 'catalog_bonus_dirs'] },
    { title: 'Montages NAS', icon: 'bi-hdd-network',
      keys: ['mount_watchdog_interval', 'mount_status_refresh_interval'] },
    { title: 'Interface', icon: 'bi-display',
      keys: ['services_refresh_interval'] },
    { title: 'Logs', icon: 'bi-file-earmark-text',
      keys: ['log_retention_days'] },
  ];

  // Séparateur explicite pour les champs "liste" — évite de deviner depuis
  // le contenu (une valeur à un seul élément n'aurait pas de séparateur).
  const LIST_SEP = {
    catalog_tech_tags:  ';',
    scan_excluded_dirs: ',',
    scan_trash_dirs:    ',',
    catalog_bonus_dirs: ',',
  };

  // Réglages dont un changement ne s'applique qu'au prochain redémarrage
  // du service (lus une seule fois au bootstrap, pas relus en boucle).
  const RESTART_REQUIRED = new Set(['log_retention_days']);

  async function load() {
    try {
      const r = await fetch(`${API}/api/admin/config`);
      _data = await r.json();
      _render();
    } catch(e) {
      console.error('Config.load:', e);
    }
  }

  function _render() {
    const box = document.getElementById('config-list');
    if (!box) return;

    const byKey  = Object.fromEntries(_data.map(d => [d.key, d]));
    const placed = new Set();

    let html = SECTIONS.map(section => {
      const items = section.keys.map(k => byKey[k]).filter(Boolean);
      items.forEach(i => placed.add(i.key));
      return items.length ? _sectionHtml(section, items) : '';
    }).join('');

    // Filet de sécurité : une clé ajoutée en base sans être catégorisée
    // ici reste visible plutôt que de disparaître silencieusement.
    const orphans = _data.filter(d => !placed.has(d.key));
    if (orphans.length) {
      html += _sectionHtml({ title: 'Autres', icon: 'bi-three-dots' }, orphans);
    }

    box.innerHTML = html;
  }

  function _sectionHtml(section, items) {
    return `
      <div class="config-section">
        <div class="config-section-title"><i class="bi ${section.icon}"></i> ${escHtml(section.title)}</div>
        <div class="config-section-grid">
          ${items.map(_cardHtml).join('')}
        </div>
      </div>`;
  }

  function _cardHtml(item) {
    const wide = item.key === 'video_extensions' || !!LIST_SEP[item.key];
    const restartBadge = RESTART_REQUIRED.has(item.key)
      ? `<span class="config-restart-badge" title="Le changement ne prend effet qu'au prochain redémarrage du service">redémarrage requis</span>`
      : '';
    return `
      <div class="config-card${wide ? ' config-card-wide' : ''}" id="config-card-${escHtml(item.key)}">
        <div class="config-header">
          <div>
            <div class="config-key">${escHtml(item.key)} ${restartBadge}</div>
            <div class="config-desc">${escHtml(item.description ?? '')}</div>
          </div>
          <div id="config-status-${escHtml(item.key)}" class="config-status"></div>
        </div>
        <div class="config-body">
          ${_renderField(item)}
        </div>
      </div>`;
  }

  function _renderField(item) {
    switch(item.key) {

      case 'video_extensions':
        const exts = item.value.split(';').filter(Boolean);
        return `
          <div class="ext-tags" id="ext-tags">
            ${exts.map(e => `
              <span class="ext-tag">
                ${escHtml(e)}
                <button onclick="Config.removeExt('${escHtml(e)}')" title="Supprimer">×</button>
              </span>`).join('')}
          </div>
          <div class="flex-row mt-10">
            <input id="ext-new" type="text" placeholder=".ext" class="input-sm"
                   onkeydown="if(event.key==='Enter') Config.addExt()">
            <button class="btn btn-sm btn-success" onclick="Config.addExt()">
              <i class="bi bi-plus-lg"></i> Ajouter
            </button>
          </div>`;

      case 'analyze_auto':
        const checked = item.value === 'true';
        return `
          <div class="toggle-row">
            <span class="toggle-label">
              ${checked ? 'Activé — analyse lancée automatiquement après chaque scan'
                        : 'Désactivé — analyse manuelle uniquement'}
            </span>
            <label class="toggle">
              <input type="checkbox" id="cfg-analyze_auto" ${checked ? 'checked' : ''}
                     onchange="Config.saveToggle('analyze_auto', this.checked)">
              <span class="slider"></span>
            </label>
          </div>`;

      default:
        const sep = LIST_SEP[item.key];
        if (sep) return _renderTagField(item, sep);
        // Number() est strict (pas de préfixe partiel comme parseFloat("4K") → 4)
        const isNum = item.value.trim() !== '' && !isNaN(Number(item.value));
        return `
          <div class="flex-row">
            <input id="cfg-${escHtml(item.key)}"
                   type="${isNum ? 'number' : 'text'}"
                   value="${escHtml(item.value)}"
                   class="input-sm"
                   onkeydown="if(event.key==='Enter') Config.saveField('${escHtml(item.key)}')">
            <button class="btn btn-sm btn-primary"
                    onclick="Config.saveField('${escHtml(item.key)}')">
              <i class="bi bi-check2"></i> Enregistrer
            </button>
          </div>`;
    }
  }

  function _renderTagField(item, sep) {
    const tags = item.value.split(sep).filter(Boolean);
    const key  = escHtml(item.key);
    return `
      <div class="ext-tags" id="tags-${key}">
        ${tags.map(t => `
          <span class="ext-tag">
            ${escHtml(t)}
            <button onclick="Config.removeTag('${key}', '${escHtml(t)}', '${sep}')" title="Supprimer">×</button>
          </span>`).join('')}
      </div>
      <div class="flex-row mt-10">
        <input id="tag-new-${key}" type="text" placeholder="nouvel élément" class="input-md"
               onkeydown="if(event.key==='Enter') Config.addTag('${key}', '${sep}')">
        <button class="btn btn-sm btn-success" onclick="Config.addTag('${key}', '${sep}')">
          <i class="bi bi-plus-lg"></i> Ajouter
        </button>
      </div>`;
  }

  /* ── Extensions (video_extensions — cas particulier : préfixe '.') ──────── */
  function _getExts() {
    const item = _data.find(d => d.key === 'video_extensions');
    return item ? item.value.split(';').filter(Boolean) : [];
  }

  async function addExt() {
    const input = document.getElementById('ext-new');
    let val = (input?.value || '').trim().toLowerCase();
    if (!val) return;
    if (!val.startsWith('.')) val = '.' + val;

    const exts = _getExts();
    if (exts.includes(val)) {
      _setStatus('video_extensions', 'warn', 'Extension déjà présente');
      return;
    }
    exts.push(val);
    await _save('video_extensions', exts.join(';'));
    if (input) input.value = '';
  }

  async function removeExt(ext) {
    const exts = _getExts().filter(e => e !== ext);
    await _save('video_extensions', exts.join(';'));
  }

  /* ── Tags génériques (tout champ liste — séparateur explicite) ──────────── */
  function _getTags(key, sep) {
    const item = _data.find(d => d.key === key);
    return item ? item.value.split(sep).filter(Boolean) : [];
  }

  async function addTag(key, sep) {
    const input = document.getElementById(`tag-new-${key}`);
    const val   = (input?.value || '').trim();
    if (!val) return;
    const tags = _getTags(key, sep);
    if (tags.includes(val)) {
      _setStatus(key, 'warn', 'Élément déjà présent');
      return;
    }
    tags.push(val);
    await _save(key, tags.join(sep));
    if (input) input.value = '';
  }

  async function removeTag(key, tag, sep) {
    const tags = _getTags(key, sep).filter(t => t !== tag);
    await _save(key, tags.join(sep));
  }

  /* ── Toggle ───────────────────────────────────────────────────────────── */
  async function saveToggle(key, checked) {
    await _save(key, checked ? 'true' : 'false');
  }

  /* ── Champ texte/numérique ────────────────────────────────────────────── */
  async function saveField(key) {
    const input = document.getElementById(`cfg-${key}`);
    if (!input) return;
    await _save(key, input.value.trim());
  }

  /* ── Save générique ───────────────────────────────────────────────────── */
  async function _save(key, value) {
    try {
      const r = await fetch(`${API}/api/admin/config/${key}`, {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({value}),
      });
      const d = await r.json();
      if (d.success) {
        // Mettre à jour _data local
        const item = _data.find(x => x.key === key);
        if (item) item.value = value;
        // Re-rendre seulement la carte concernée
        const card = document.getElementById(`config-card-${key}`);
        if (card) {
          const item2 = _data.find(x => x.key === key);
          card.querySelector('.config-body').innerHTML = _renderField(item2);
        }
        _setStatus(key, 'ok', 'Enregistré');
        setTimeout(() => _setStatus(key, '', ''), 2000);
      } else {
        _setStatus(key, 'error', d.detail ?? 'Erreur');
      }
    } catch(e) {
      _setStatus(key, 'error', e.message);
    }
  }

  function _setStatus(key, type, msg) {
    const el = document.getElementById(`config-status-${key}`);
    if (!el) return;
    el.className = `config-status${type ? ' config-status-' + type : ''}`;
    el.textContent = msg;
  }

  return { load, addExt, removeExt, saveToggle, saveField, addTag, removeTag };

})();
