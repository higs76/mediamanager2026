/* =============================================================================
   MediaManager 2026 — rename.js
   Interface de validation des propositions de renommage
   ============================================================================= */

const Rename = (() => {

  let _proposals   = [];
  let _currentTitle = null;
  let _catFilter   = null;

  /* ── Entrée publique ──────────────────────────────────────────────────── */
  async function init() {
    await _loadProposals();
  }

  async function loadBadge() {
    try {
      const r = await fetch(`${API}/api/admin/jobs/status`);
      const d = await r.json();
      const count = d.cataloger?.proposals_pending ?? 0;
      const badge = document.getElementById('rename-badge');
      if (badge) {
        badge.textContent = count.toLocaleString('fr-FR');
        badge.classList.toggle('hidden', count === 0);
      }
    } catch(e) { console.warn('loadBadge:', e); }
  }

  /* ── Liste des titres avec propositions ───────────────────────────────── */
  async function _loadProposals() {
    const el = document.getElementById('rename-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const url = _catFilter
        ? `${API}/api/admin/library/proposals?category_id=${_catFilter}`
        : `${API}/api/admin/library/proposals`;
      const r = await fetch(url);
      _proposals = await r.json();
      _renderProposalList();
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _renderProposalList() {
    const el = document.getElementById('rename-content');

    if (!_proposals.length) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-check-circle text-green"></i>
        Aucune proposition en attente — tout est à jour !
      </div>`;
      return;
    }

    const byCat = {};
    _proposals.forEach(p => {
      if (!byCat[p.category]) byCat[p.category] = [];
      byCat[p.category].push(p);
    });

    const cats = Object.keys(byCat).sort();
    const tabsHtml = [
      `<button class="cat-tab${!_catFilter ? ' active' : ''}"
         onclick="Rename.filterCat(null)">
         Toutes <span class="badge-count">${_proposals.length}</span>
       </button>`,
      ...cats.map(cat => {
        return `<button class="cat-tab${_catFilter === cat ? ' active' : ''}"
           onclick="Rename.filterCat('${esc(cat)}')">
           ${esc(cap(cat))}
           <span class="badge-count">${byCat[cat].length}</span>
         </button>`;
      })
    ].join('');

    const listHtml = _buildCatListHtml(byCat);

    el.innerHTML = `
      <div class="breadcrumb">
        <i class="bi bi-pencil-square"></i> Renommage
      </div>
      <div class="cat-tabs">${tabsHtml}</div>
      <div id="proposal-list">${listHtml}</div>`;
  }

  function _buildCatListHtml(byCat) {
    return Object.entries(byCat).map(([cat, items]) => `
      <div class="rename-cat-section">
        <div class="section-label">
          <i class="bi bi-${items[0].has_seasons ? 'tv' : 'film'}"></i>
          ${esc(cap(cat))}
        </div>
        <div class="card card-flush">
          ${items.map(p => `
            <div class="title-row" onclick="Rename.openTitle(${p.title_id})">
              <div>
                <div class="title-name">${esc(p.display_name)}</div>
                <div class="title-meta">
                  ${p.folder_status === 'to_rename'
                    ? '<i class="bi bi-folder"></i> Dossier à renommer · '
                    : ''}
                  ${p.proposal_count} proposition${p.proposal_count > 1 ? 's' : ''}
                </div>
              </div>
              <div class="title-right">
                <span class="badge badge-warn">${p.proposal_count}</span>
                <i class="bi bi-chevron-right nav-chevron"></i>
              </div>
            </div>`).join('')}
        </div>
      </div>`).join('');
  }

  function filterCat(cat) {
    _catFilter = cat;
    const el = document.getElementById('proposal-list');
    if (!el) return;
    const filtered = cat
      ? _proposals.filter(p => p.category === cat)
      : _proposals;

    const byCat = {};
    filtered.forEach(p => {
      if (!byCat[p.category]) byCat[p.category] = [];
      byCat[p.category].push(p);
    });

    el.innerHTML = _buildCatListHtml(byCat);

    document.querySelectorAll('.cat-tab').forEach(btn => {
      btn.classList.toggle('active',
        (cat === null && btn.textContent.includes('Toutes')) ||
        btn.textContent.trim().startsWith(cap(cat ?? ''))
      );
    });
  }

  /* ── Détail titre — blocs de validation ───────────────────────────────── */
  async function openTitle(titleId) {
    const el = document.getElementById('rename-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const r = await fetch(`${API}/api/admin/library/proposals/${titleId}`);
      _currentTitle = await r.json();
      _renderTitleProposals();
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _renderTitleProposals() {
    const t  = _currentTitle;
    const el = document.getElementById('rename-content');

    const totalProps = Object.values(t.seasons).flat().length
      + (t.title_proposal ? 1 : 0);

    el.innerHTML = `
      <div class="breadcrumb">
        <a onclick="Rename.init()">
          <i class="bi bi-pencil-square"></i> Renommage
        </a>
        <i class="bi bi-chevron-right"></i>
        <span>${esc(t.display_name)}</span>
      </div>

      <div class="card card-mb">
        <div class="prop-title-head">
          <div>
            <div class="prop-title-name">${esc(t.display_name)}</div>
            <div class="prop-title-sub">
              ${totalProps} proposition${totalProps > 1 ? 's' : ''} en attente
            </div>
          </div>
        </div>
      </div>

      ${t.title_proposal ? _renderFolderProposal(t) : ''}

      <div id="seasons-proposals">
        ${_renderSeasonsProposals(t)}
      </div>`;
  }

  /* ── Proposition dossier titre ────────────────────────────────────────── */
  function _renderFolderProposal(t) {
    const p = t.title_proposal;
    return `
      <div class="card card-warn">
        <div class="folder-prop-label">
          <i class="bi bi-folder"></i> Dossier série à renommer
        </div>
        <div class="folder-prop-current">Actuel : ${esc(p.current_name)}/</div>
        ${_blocksHtml({
          propId:    p.prop_id,
          type:      'folder',
          serie:     p.proposed_name,
          origSerie: p.proposed_name,
        })}
      </div>`;
  }

  function _blocksHtml({ propId, serie, origSerie }) {
    const uid = `p${propId}`;
    return `
      <div class="prop-blocs-row">
        ${_blocCell(uid, 'serie', 'Dossier', serie, origSerie, 'text', 'bloc-cell-solo')}
      </div>
      <div class="prop-actions-row">
        <div id="${uid}-preview" class="rename-preview">${esc(serie)}/</div>
        <button onclick="Rename.acceptItem('${uid}', ${propId})"
                class="btn btn-sm btn-success btn-compact">
          <i class="bi bi-check2"></i>
        </button>
        <button onclick="Rename.rejectItem(${propId}, this)"
                class="btn btn-sm btn-danger btn-compact">
          <i class="bi bi-x"></i>
        </button>
      </div>`;
  }

  /* ── Propositions par saison ──────────────────────────────────────────── */
  function _renderSeasonsProposals(t) {
    const entries = Object.entries(t.seasons);
    if (!entries.length) return '';

    return entries.map(([season, items]) => {
      const sNum   = season === 'null' ? null : parseInt(season);
      const sLabel = sNum === null ? 'Sans saison'
                   : sNum === 0   ? 'Spéciaux'
                   : `Saison ${String(sNum).padStart(2,'0')}`;

      return `<div class="tree-item tree-item-mb">
        <div class="tree-header" onclick="toggleTree(this.parentElement.querySelector('.tree-body'), this.querySelector('.rename-chevron'))">
          <div class="rename-tree-head">
            <i class="bi bi-chevron-right rename-chevron"></i>
            <span class="rename-season-label">${esc(sLabel)}</span>
            <span class="rename-season-count">
              ${items.length} proposition${items.length > 1 ? 's' : ''}
            </span>
          </div>
        </div>
        <div class="tree-body">
          ${items.map(item => _renderItemProposal(item, t)).join('')}
        </div>
      </div>`;
    }).join('');
  }

  /* ── Proposition fichier ──────────────────────────────────────────────── */
  function _renderItemProposal(item, t) {
    const tpl    = t.template;
    const sep1   = tpl.sep1   || ' - ';
    const sep2   = tpl.sep2   || ' - ';
    const sepSE  = tpl.sep_se || 'x';
    const prefS  = tpl.prefix_season  || '';
    const prefE  = tpl.prefix_episode || '';
    const digS   = tpl.digits_season  || 2;
    const digE   = tpl.digits_episode || 2;

    const origSerie  = t.display_name;
    const origSaison = item.season  !== null ? item.season  : '';
    const origEp     = item.episode !== null ? item.episode : '';
    const origTitre  = item.episode_title || '';

    const res = item.height
      ? (item.height >= 2160 ? '4K' : item.height >= 1080 ? '1080p'
         : item.height >= 720 ? '720p' : 'SD') : '';
    const uid = `p${item.prop_id}`;

    return `
      <div class="prop-item">

        <div class="prop-file-row">
          <div class="prop-filename" title="${esc(item.current_name)}">
            ${esc(item.current_name)}
          </div>
          ${res ? `<span class="badge badge-muted flex-shrink-0">${res}</span>` : ''}
          ${item.hdr && item.hdr !== 'SDR'
            ? `<span class="badge hdr-badge-rename flex-shrink-0">${esc(item.hdr)}</span>`
            : ''}
        </div>

        <div class="prop-blocs-row">

          ${_blocCell(uid,'serie','Série', origSerie, origSerie,'text', 'bloc-cell-first')}

          <div class="sep-cell">${esc(sep1)}</div>

          ${_blocCell(uid,'saison','Saison',
              String(origSaison).padStart(digS,'0'), String(origSaison),
              'number', 'bloc-cell-mid')}

          <div class="sep-cell">${esc(sepSE)}</div>

          ${_blocCell(uid,'episode','Épisode',
              String(origEp).padStart(digE,'0'), String(origEp),
              'number', 'bloc-cell-mid')}

          <div class="sep-cell">${esc(sep2)}</div>

          ${_blocCell(uid,'titre',
              'Titre <span style="opacity:.5;font-size:9px">(opt.)</span>',
              origTitre || 'vide', origTitre, 'text',
              'bloc-cell-last', !origTitre)}

        </div>

        <div class="prop-actions-row">
          <div id="${uid}-preview" class="rename-preview prop-preview">
            ${esc(item.proposed_name)}
          </div>
          <button id="${uid}-mkv" onclick="Rename.toggleMkv('${uid}')"
                  class="btn btn-sm btn-compact" title="Mettre à jour le tag title MKV">
            <i class="bi bi-file-earmark-check"></i> MKV
          </button>
          <button onclick="Rename.acceptItem('${uid}', ${item.prop_id})"
                  class="btn btn-sm btn-success btn-compact">
            <i class="bi bi-check2"></i>
          </button>
          <button onclick="Rename.rejectItem(${item.prop_id}, this)"
                  class="btn btn-sm btn-danger btn-compact">
            <i class="bi bi-x"></i>
          </button>
        </div>

      </div>`;
  }

  function _blocCell(uid, field, label, displayVal, origVal, type, cellClass, isEmpty) {
    const id = `${uid}-${field}`;
    const wrapClass = type === 'number' ? 'bloc-val-wrap-num' : 'bloc-val-wrap';
    return `
      <div class="bloc-cell ${cellClass}">
        <div class="bloc-cell-label">${label}</div>
        <div class="bloc-cell-body">
          <div class="${wrapClass}">
            <div id="${id}-disp"
                 class="bloc-disp${isEmpty ? ' empty' : ''}"
                 onclick="Rename.startEdit('${id}','${type}')"
                 title="Cliquer pour modifier"
                 data-orig="${esc(origVal)}">
              ${esc(displayVal) || 'vide'}
            </div>
            <input id="${id}-inp" type="${type}"
                   class="bloc-inp"
                   value="${esc(origVal)}"
                   onblur="Rename.endEdit('${id}','${uid}')"
                   onkeydown="if(event.key==='Enter'||event.key==='Tab'){
                     event.preventDefault();Rename.endEdit('${id}','${uid}')}">
          </div>
          <button onclick="Rename.resetBloc('${id}','${esc(origVal)}')"
                  class="bloc-circle-btn bloc-reset-btn"
                  title="Remettre la valeur proposée">
            <i class="bi bi-arrow-counterclockwise"></i>
          </button>
          <button id="${id}-vbtn"
                  onclick="Rename.toggleValidate('${id}')"
                  class="bloc-circle-btn bloc-ok-btn"
                  title="Valider ce bloc">
            <i class="bi bi-check2"></i>
          </button>
        </div>
      </div>`;
  }

  /* ── Bloc input cliquable (ancien format, conservé) ───────────────────── */
  function _blocInput(uid, field, label, displayVal, origVal, type, style, isEmpty) {
    const id = `${uid}-${field}`;
    return `
      <div class="rename-bloc" style="${style}">
        <div class="rename-bloc-label">${label}</div>
        <div style="display:flex;align-items:center;gap:3px">
          <div id="${id}-disp"
               class="rename-bloc-val${isEmpty ? ' empty' : ''}"
               onclick="Rename.startEdit('${id}', '${type}')"
               title="Cliquer pour modifier"
               data-orig="${esc(origVal)}">
            ${esc(displayVal) || 'vide'}
          </div>
          <button onclick="Rename.resetBloc('${id}', '${esc(origVal)}')"
                  class="btn btn-sm" style="padding:3px 5px;font-size:11px"
                  title="Remettre la valeur proposée">
            <i class="bi bi-arrow-counterclockwise"></i>
          </button>
          <button id="${id}-vbtn"
                  onclick="Rename.toggleValidate('${id}')"
                  class="btn btn-sm btn-success" style="padding:3px 5px;font-size:11px"
                  title="Valider ce bloc">
            <i class="bi bi-check2"></i>
          </button>
        </div>
        <input id="${id}-inp" type="${type}"
               style="display:none;font-family:monospace;font-size:12px;margin-top:3px;width:100%"
               value="${esc(origVal)}"
               onblur="Rename.endEdit('${id}', '${uid}')"
               onkeydown="if(event.key==='Enter'||event.key==='Tab'){event.preventDefault();Rename.endEdit('${id}','${uid}')}">
      </div>`;
  }

  /* ── Interactions blocs ───────────────────────────────────────────────── */
  function startEdit(id, type) {
    const disp = document.getElementById(`${id}-disp`);
    const inp  = document.getElementById(`${id}-inp`);
    if (!disp || !inp) return;
    disp.style.display = 'none';
    inp.style.display  = 'block';
    const bloc = inp.closest('.bloc-cell');
    if (bloc) bloc.classList.add('editing');
    inp.focus();
    if (type === 'text') inp.select();
  }

  function endEdit(id, uid) {
    const disp = document.getElementById(`${id}-disp`);
    const inp  = document.getElementById(`${id}-inp`);
    if (!disp || !inp) return;
    const val = inp.value.trim();
    disp.textContent   = val || 'vide';
    disp.classList.toggle('empty', !val);
    disp.style.display = '';
    inp.style.display  = 'none';
    const bloc = inp.closest('.bloc-cell');
    if (bloc) bloc.classList.remove('editing');
    _updatePreview(uid);
  }

  function resetBloc(id, origVal) {
    const disp = document.getElementById(`${id}-disp`);
    const inp  = document.getElementById(`${id}-inp`);
    const vbtn = document.getElementById(`${id}-vbtn`);
    if (!disp || !inp) return;
    inp.value          = origVal;
    disp.textContent   = origVal || 'vide';
    disp.classList.toggle('empty', !origVal);
    disp.classList.remove('validated');
    disp.style.display = '';
    inp.style.display  = 'none';
    if (vbtn) {
      vbtn.className = 'bloc-circle-btn bloc-ok-btn';
      vbtn.innerHTML = '<i class="bi bi-check2"></i>';
      vbtn.title     = 'Valider ce bloc';
    }
    const uid = id.split('-').slice(0,-1).join('-');
    _updatePreview(uid);
  }

  function toggleValidate(id) {
    const disp = document.getElementById(`${id}-disp`);
    const vbtn = document.getElementById(`${id}-vbtn`);
    if (!disp || !vbtn) return;
    const isVal = disp.classList.toggle('validated');
    if (isVal) {
      vbtn.className = 'bloc-circle-btn bloc-ok-btn validated';
      vbtn.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i>';
      vbtn.title     = 'Annuler la validation';
    } else {
      vbtn.className = 'bloc-circle-btn bloc-ok-btn';
      vbtn.innerHTML = '<i class="bi bi-check2"></i>';
      vbtn.title     = 'Valider ce bloc';
    }
  }

  /* ── Mise à jour aperçu ───────────────────────────────────────────────── */
  function _updatePreview(uid) {
    const prev = document.getElementById(`${uid}-preview`);
    if (!prev) return;
    const t   = _currentTitle;
    const tpl = t?.template ?? {};

    const get = field => {
      const inp = document.getElementById(`${uid}-${field}-inp`);
      if (inp && inp.style.display !== 'none') return inp.value.trim();
      const disp = document.getElementById(`${uid}-${field}-disp`);
      return (disp?.textContent || '').replace('vide','').trim();
    };

    const serie   = get('serie');
    const titre   = get('titre');

    const saisonEl = document.getElementById(`${uid}-saison-inp`);
    if (saisonEl) {
      const saison  = get('saison');
      const episode = get('episode');
      const sep1  = tpl.sep1   || ' - ';
      const sep2  = tpl.sep2   || ' - ';
      const sepSE = tpl.sep_se || 'x';
      const prefS = tpl.prefix_season  || '';
      const prefE = tpl.prefix_episode || '';
      const digS  = tpl.digits_season  || 2;
      const digE  = tpl.digits_episode || 2;
      const s = String(parseInt(saison)||0).padStart(digS,'0');
      const e = String(parseInt(episode)||0).padStart(digE,'0');
      const num = `${prefS}${s}${sepSE}${prefE}${e}`;
      prev.textContent = titre
        ? `${serie}${sep1}${num}${sep2}${titre}.mkv`
        : `${serie}${sep1}${num}.mkv`;
    } else {
      prev.textContent = serie + '/';
    }
  }

  /* ── MKV toggle ───────────────────────────────────────────────────────── */
  function toggleMkv(uid) {
    const btn = document.getElementById(`${uid}-mkv`);
    if (!btn) return;
    const active = btn.classList.toggle('btn-info');
    btn.title = active
      ? 'Tag MKV sera mis à jour'
      : 'Mettre à jour le tag title MKV';
  }

  /* ── Accepter / Rejeter ───────────────────────────────────────────────── */
  async function acceptItem(uid, propId) {
    const prev      = document.getElementById(`${uid}-preview`);
    const mkvBtn    = document.getElementById(`${uid}-mkv`);
    const finalName = prev?.textContent?.trim();
    const updateMkv = mkvBtn?.classList.contains('btn-info') ?? false;

    if (!finalName) return;

    try {
      const r = await fetch(`${API}/api/admin/library/proposals/${propId}/accept`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ final_name: finalName, update_mkv: updateMkv }),
      });
      if (!r.ok) throw new Error((await r.json()).detail);

      const row = prev?.closest('.prop-item');
      if (row) row.classList.add('prop-accepted');
      if (prev) prev.classList.add('rename-preview-ok');
      loadBadge();
    } catch(e) {
      alert('Erreur : ' + e.message);
    }
  }

  async function rejectItem(propId, btn) {
    try {
      const r = await fetch(`${API}/api/admin/library/proposals/${propId}/reject`, {
        method: 'POST',
      });
      if (!r.ok) throw new Error((await r.json()).detail);

      const row = btn?.closest('.prop-item');
      if (row) row.classList.add('prop-accepted');
      loadBadge();
    } catch(e) {
      alert('Erreur : ' + e.message);
    }
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  return {
    init, loadBadge, filterCat, openTitle,
    startEdit, endEdit, resetBloc, toggleValidate,
    toggleMkv, acceptItem, rejectItem,
  };

})();
