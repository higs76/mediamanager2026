/* =============================================================================
   MediaManager 2026 — config.js
   Gestion de la configuration
   ============================================================================= */

const Config = (() => {

  let _data = [];

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

    box.innerHTML = _data.map(item => `
      <div class="config-card" id="config-card-${_esc(item.key)}">
        <div class="config-header">
          <div>
            <div class="config-key">${_esc(item.key)}</div>
            <div class="config-desc">${_esc(item.description ?? '')}</div>
          </div>
          <div id="config-status-${_esc(item.key)}" class="config-status"></div>
        </div>
        <div class="config-body">
          ${_renderField(item)}
        </div>
      </div>
    `).join('');
  }

  function _renderField(item) {
    switch(item.key) {

      case 'video_extensions':
        const exts = item.value.split(';').filter(Boolean);
        return `
          <div class="ext-tags" id="ext-tags">
            ${exts.map(e => `
              <span class="ext-tag">
                ${_esc(e)}
                <button onclick="Config.removeExt('${_esc(e)}')" title="Supprimer">×</button>
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
        // Valeur semicolon-délimitée → liste de tags (comme video_extensions)
        if (item.value.includes(';')) {
          return _renderTagField(item);
        }
        // Number() est strict (pas de préfixe partiel comme parseFloat("4K") → 4)
        const isNum = item.value.trim() !== '' && !isNaN(Number(item.value));
        return `
          <div class="flex-row">
            <input id="cfg-${_esc(item.key)}"
                   type="${isNum ? 'number' : 'text'}"
                   value="${_esc(item.value)}"
                   class="input-sm"
                   onkeydown="if(event.key==='Enter') Config.saveField('${_esc(item.key)}')">
            <button class="btn btn-sm btn-primary"
                    onclick="Config.saveField('${_esc(item.key)}')">
              <i class="bi bi-check2"></i> Enregistrer
            </button>
          </div>`;
    }
  }

  function _renderTagField(item) {
    const tags = item.value.split(';').filter(Boolean);
    const key  = _esc(item.key);
    return `
      <div class="ext-tags" id="tags-${key}">
        ${tags.map(t => `
          <span class="ext-tag">
            ${_esc(t)}
            <button onclick="Config.removeTag('${key}', '${_esc(t)}')" title="Supprimer">×</button>
          </span>`).join('')}
      </div>
      <div class="flex-row mt-10">
        <input id="tag-new-${key}" type="text" placeholder="nouveau tag" class="input-md"
               onkeydown="if(event.key==='Enter') Config.addTag('${key}')">
        <button class="btn btn-sm btn-success" onclick="Config.addTag('${key}')">
          <i class="bi bi-plus-lg"></i> Ajouter
        </button>
      </div>`;
  }

  /* ── Extensions ───────────────────────────────────────────────────────── */
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

  /* ── Tags génériques (catalog_tech_tags et toute clé semicolon) ────────── */
  function _getTags(key) {
    const item = _data.find(d => d.key === key);
    return item ? item.value.split(';').filter(Boolean) : [];
  }

  async function addTag(key) {
    const input = document.getElementById(`tag-new-${key}`);
    const val   = (input?.value || '').trim();
    if (!val) return;
    const tags = _getTags(key);
    if (tags.includes(val)) {
      _setStatus(key, 'warn', 'Tag déjà présent');
      return;
    }
    tags.push(val);
    await _save(key, tags.join(';'));
    if (input) input.value = '';
  }

  async function removeTag(key, tag) {
    const tags = _getTags(key).filter(t => t !== tag);
    await _save(key, tags.join(';'));
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

  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  return { load, addExt, removeExt, saveToggle, saveField, addTag, removeTag };

})();