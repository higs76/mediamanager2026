/* =============================================================================
   MediaManager 2026 — library.js
   Navigation bibliothèque : catégories → titres → détail
   ============================================================================= */

const Library = (() => {

  let _categories  = [];
  let _currentCat  = null;
  let _currentTitle = null;

  /* ── Entrée publique ──────────────────────────────────────────────────── */
  async function init() {
    await _loadCategories();
  }

  /* ── Catégories ───────────────────────────────────────────────────────── */
  async function _loadCategories() {
    const el = document.getElementById('library-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const r = await fetch(`${API}/api/admin/library/categories`);
      _categories = await r.json();
      _renderCategories();
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _renderCategories() {
    const el = document.getElementById('library-content');
    if (!_categories.length) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-collection"></i> Aucune catégorie</div>`;
      return;
    }

    el.innerHTML = `
      <div class="breadcrumb">
        <i class="bi bi-house"></i> Bibliothèque
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px">
        ${_categories.map(c => `
          <div class="card" onclick="Library.openCategory(${c.id})"
               style="cursor:pointer;transition:border-color .15s"
               onmouseover="this.style.borderColor='var(--blue)'"
               onmouseout="this.style.borderColor='var(--border)'">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px">
              <div style="display:flex;align-items:center;gap:8px">
                <i class="bi bi-${c.has_seasons ? 'tv' : 'film'}"
                   style="font-size:18px;color:var(--blue)"></i>
                <span style="font-weight:600;font-size:14px">${esc(cap(c.name))}</span>
              </div>
              <span class="badge badge-info">${c.has_seasons ? 'Saisonnable' : 'Film'}</span>
            </div>
            <div style="display:flex;gap:16px;font-size:12px;color:var(--muted)">
              <span><strong style="color:var(--text)">${c.title_count.toLocaleString('fr-FR')}</strong> titres</span>
              <span><strong style="color:var(--text)">${c.file_count.toLocaleString('fr-FR')}</strong> fichiers</span>
            </div>
          </div>`).join('')}
      </div>`;
  }

  /* ── Titres ───────────────────────────────────────────────────────────── */
  async function openCategory(catId) {
    _currentCat = _categories.find(c => c.id === catId);
    const el = document.getElementById('library-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const r = await fetch(`${API}/api/admin/library/titles?category_id=${catId}`);
      const titles = await r.json();
      _renderTitles(titles);
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _renderTitles(titles) {
    const cat = _currentCat;
    const el  = document.getElementById('library-content');

    el.innerHTML = `
      <div class="breadcrumb">
        <a onclick="Library.init()"><i class="bi bi-house"></i> Bibliothèque</a>
        <i class="bi bi-chevron-right"></i>
        <span>${esc(cap(cat.name))}</span>
      </div>

      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
        <input type="text" id="lib-search" placeholder="Rechercher…"
               style="max-width:280px" oninput="Library.search(this.value, ${cat.id})">
        <span style="font-size:12px;color:var(--muted)">${titles.length} titre${titles.length > 1 ? 's' : ''}</span>
      </div>

      <div id="titles-list">
        ${_titlesHtml(titles)}
      </div>`;
  }

  function _titlesHtml(titles) {
    if (!titles.length) {
      return `<div class="empty-state"><i class="bi bi-search"></i> Aucun résultat</div>`;
    }
    return `<div class="card" style="padding:0">
      ${titles.map(t => {
        const meta = [
          t.year ? t.year : null,
          t.season_count > 0 ? `${t.season_count} saison${t.season_count > 1 ? 's' : ''}` : null,
          `${t.file_count} fichier${t.file_count > 1 ? 's' : ''}`,
        ].filter(Boolean).join(' · ');

        const badge = t.folder_status === 'to_rename'
          ? `<span class="badge badge-warn"><i class="bi bi-pencil"></i> À renommer</span>`
          : '';
        const propBadge = t.proposals > 0
          ? `<span class="badge badge-warn">${t.proposals} proposition${t.proposals > 1 ? 's' : ''}</span>`
          : '';

        return `<div class="title-row" onclick="Library.openTitle(${t.id})">
          <div>
            <div class="title-name">${esc(t.display_name)}</div>
            <div class="title-meta">${esc(meta)}</div>
          </div>
          <div class="title-right">
            ${propBadge}
            ${badge}
            <i class="bi bi-chevron-right" style="color:var(--muted);font-size:12px"></i>
          </div>
        </div>`;
      }).join('')}
    </div>`;
  }

  async function search(query, catId) {
    try {
      const url = `${API}/api/admin/library/titles?category_id=${catId}`
        + (query ? `&search=${encodeURIComponent(query)}` : '');
      const r = await fetch(url);
      const titles = await r.json();
      document.getElementById('titles-list').innerHTML = _titlesHtml(titles);
    } catch(e) { console.warn('search:', e); }
  }

  /* ── Détail titre ─────────────────────────────────────────────────────── */
  async function openTitle(titleId) {
    const el = document.getElementById('library-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const r = await fetch(`${API}/api/admin/library/titles/${titleId}`);
      const t = await r.json();
      _currentTitle = t;
      _renderTitle(t);
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _renderTitle(t) {
    const el  = document.getElementById('library-content');
    const cat = _currentCat;

    // Bandeau stats
    const seasons  = Object.keys(t.seasons).filter(s => s !== 'null');
    const allItems = Object.values(t.seasons).flat();
    const totalFiles = allItems.length;
    const toRename   = allItems.filter(i => i.file_status === 'to_rename').length;
    const proposals  = allItems.filter(i => i.prop_id).length;

    el.innerHTML = `
      <div class="breadcrumb">
        <a onclick="Library.init()"><i class="bi bi-house"></i> Bibliothèque</a>
        <i class="bi bi-chevron-right"></i>
        <a onclick="Library.openCategory(${cat?.id})">${esc(cap(cat?.name ?? ''))}</a>
        <i class="bi bi-chevron-right"></i>
        <span>${esc(t.display_name)}</span>
      </div>

      <!-- Bandeau info titre -->
      <div class="card" style="margin-bottom:16px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px">
          <div>
            <div style="font-size:18px;font-weight:600;margin-bottom:4px">
              ${esc(t.display_name)}
              ${t.year ? `<span style="color:var(--muted);font-size:14px;font-weight:400">(${t.year})</span>` : ''}
            </div>
            <div style="font-size:12px;color:var(--muted);display:flex;gap:12px;flex-wrap:wrap">
              ${t.has_seasons ? `<span><i class="bi bi-collection"></i> ${seasons.length} saison${seasons.length > 1 ? 's' : ''}</span>` : ''}
              <span><i class="bi bi-file-play"></i> ${totalFiles} fichier${totalFiles > 1 ? 's' : ''}</span>
              ${toRename > 0 ? `<span style="color:var(--orange)"><i class="bi bi-pencil"></i> ${toRename} à renommer</span>` : ''}
              ${proposals > 0 ? `<span style="color:var(--orange)"><i class="bi bi-lightbulb"></i> ${proposals} proposition${proposals > 1 ? 's' : ''}</span>` : ''}
            </div>
          </div>
          ${t.folder_status === 'to_rename' ? `
            <span class="badge badge-warn">
              <i class="bi bi-folder"></i> Dossier à renommer
            </span>` : ''}
        </div>
      </div>

      <!-- Saisons / fichiers -->
      ${_renderSeasons(t)}`;
  }

  function _renderSeasons(t) {
    const entries = Object.entries(t.seasons);
    if (!entries.length) {
      return `<div class="empty-state"><i class="bi bi-file-x"></i> Aucun fichier</div>`;
    }

    if (!t.has_seasons) {
      // Films — pas de saisons, liste directe
      const items = entries.flatMap(([,v]) => v);
      return _renderItems(items, false);
    }

    // Séries — grouper par saison
    return entries.map(([season, items]) => {
      const sNum    = season === 'null' ? null : parseInt(season);
      const sLabel  = sNum === null ? 'Sans saison'
                    : sNum === 0   ? 'Spéciaux'
                    : `Saison ${String(sNum).padStart(2,'0')}`;
      const toRen   = items.filter(i => i.file_status === 'to_rename').length;
      const props   = items.filter(i => i.prop_id).length;

      return `<div class="tree-item">
        <div class="tree-header" onclick="toggleTree(this)">
          <div style="display:flex;align-items:center;gap:8px">
            <i class="bi bi-chevron-right"
               style="font-size:12px;color:var(--muted);transition:transform .15s"></i>
            <span style="font-weight:500">${esc(sLabel)}</span>
            <span style="font-size:11px;color:var(--muted)">${items.length} fichier${items.length>1?'s':''}</span>
          </div>
          <div style="display:flex;gap:6px">
            ${props   > 0 ? `<span class="badge badge-warn">${props} proposition${props>1?'s':''}</span>` : ''}
            ${toRen   > 0 ? `<span class="badge badge-warn">${toRen} à renommer</span>` : ''}
          </div>
        </div>
        <div class="tree-body">
          ${_renderItems(items, true)}
        </div>
      </div>`;
    }).join('');
  }

  function _renderItems(items, showEp) {
    return items.map(i => {
      const res = i.height
        ? (i.height >= 2160 ? '4K' : i.height >= 1080 ? '1080p' : i.height >= 720 ? '720p' : 'SD')
        : '';
      const dur = i.duration
        ? `${Math.floor(i.duration/3600)}h${String(Math.floor((i.duration%3600)/60)).padStart(2,'0')}`
        : '';
      const epNum = (i.season !== null && i.episode !== null)
        ? `${String(i.season).padStart(2,'0')}x${String(i.episode).padStart(2,'0')}`
        : '';

      return `<div style="display:flex;align-items:center;justify-content:space-between;
                   padding:8px 4px;border-bottom:1px solid var(--border);font-size:12px"
                   class="title-row">
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:2px">
            ${showEp && epNum ? `<span style="font-family:monospace;color:var(--blue);font-size:11px">${epNum}</span>` : ''}
            <span style="font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
              ${esc(i.episode_title || i.filename)}
            </span>
          </div>
          <div style="color:var(--muted);font-size:11px;display:flex;gap:8px">
            ${i.codec ? `<span>${i.codec.toUpperCase()}</span>` : ''}
            ${res ? `<span>${res}</span>` : ''}
            ${i.hdr && i.hdr !== 'SDR' ? `<span style="color:var(--purple)">${i.hdr}</span>` : ''}
            ${dur ? `<span>${dur}</span>` : ''}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
          ${i.prop_id ? `<span class="badge badge-warn"><i class="bi bi-lightbulb"></i></span>` : ''}
          ${i.file_status === 'to_rename' ? `<span class="badge badge-warn"><i class="bi bi-pencil"></i></span>` : ''}
        </div>
      </div>`;
    }).join('');
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  function toggleTree(header) {
    const body = header.nextElementSibling;
    const icon = header.querySelector('.bi-chevron-right');
    const open = body.classList.toggle('open');
    if (icon) icon.style.transform = open ? 'rotate(90deg)' : '';
  }

  // Exposer toggleTree globalement pour les onclick dans le HTML généré
  window.toggleTree = toggleTree;

  return { init, openCategory, openTitle, search };

})();