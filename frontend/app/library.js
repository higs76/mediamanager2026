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
      const r = await fetch(`${API}/api/admin/library/categories/stats`);
      _categories = await r.json();
      _renderCategories();
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _renderCategories() {
    const el = document.getElementById('library-content');
    const visible = _categories.filter(c => c.title_count > 0 || c.file_count > 0);

    if (!visible.length) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-collection"></i> Aucune catégorie</div>`;
      return;
    }

    el.innerHTML = `
      <div class="breadcrumb">
        <i class="bi bi-house"></i> Bibliothèque
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px">
        ${visible.map(c => _categoryCardHtml(c)).join('')}
      </div>`;
  }

function _categoryCardHtml(c) {
    const tb     = c.total_tb >= 1
      ? `${c.total_tb} To`
      : `${Math.round(c.total_tb * 1024)} Go`;
    const icon   = c.has_seasons ? 'bi-tv' : 'bi-film';
    const badge  = c.has_seasons
      ? `<span style="font-size:11px;padding:2px 8px;border-radius:20px;
             background:rgba(88,166,255,.15);color:var(--blue);
             border:1px solid rgba(88,166,255,.3)">Saisonnable</span>`
      : `<span style="font-size:11px;padding:2px 8px;border-radius:20px;
             background:var(--bg3);color:var(--muted);
             border:1px solid var(--border)">Film</span>`;

    const resHtml = c.resolutions.map(r => `
      <div style="display:flex;align-items:center;justify-content:space-between;font-size:12px;margin-bottom:3px">
        <span style="color:var(--muted)">${esc(r.label)}</span>
        <span style="font-weight:500">${r.pct}%</span>
      </div>
      <div style="height:3px;background:var(--bg3);border-radius:2px;margin-bottom:5px">
        <div style="width:${r.pct}%;height:100%;background:var(--blue);border-radius:2px"></div>
      </div>`).join('');

    const codHtml = c.codecs.map(r => `
      <div style="display:flex;align-items:center;justify-content:space-between;font-size:12px;margin-bottom:3px">
        <span style="color:var(--muted)">${esc(r.label)}</span>
        <span style="font-weight:500">${r.pct}%</span>
      </div>
      <div style="height:3px;background:var(--bg3);border-radius:2px;margin-bottom:5px">
        <div style="width:${r.pct}%;height:100%;background:var(--purple);border-radius:2px"></div>
      </div>`).join('');

    return `
      <div style="background:var(--card-bg);border:1px solid var(--border);
           border-radius:var(--radius-lg);overflow:hidden;cursor:pointer;
           transition:border-color .15s"
           onclick="Library.openCategory(${c.id})"
           onmouseover="this.style.borderColor='var(--blue)'"
           onmouseout="this.style.borderColor='var(--border)'">

        <!-- En-tête -->
        <div style="display:flex;align-items:center;justify-content:space-between;
             padding:12px 14px;border-bottom:1px solid var(--border)">
          <div style="display:flex;align-items:center;gap:8px">
            <i class="bi ${icon}" style="font-size:18px;color:var(--blue)"></i>
            <span style="font-weight:600;font-size:14px">${esc(cap(c.name))}</span>
          </div>
          ${badge}
        </div>

        <!-- Titres / Fichiers / Taille -->
        <div style="padding:12px 14px;border-bottom:1px solid var(--border)">
          <div style="display:flex;align-items:center;justify-content:space-between">
            <div style="display:flex;flex-direction:column;gap:5px">
              <div style="display:flex;align-items:center;gap:6px;font-size:13px">
                <i class="bi bi-collection-play" style="color:var(--muted);font-size:14px"></i>
                <strong>${c.title_count.toLocaleString('fr-FR')}</strong>
                <span style="color:var(--muted)">titres</span>
              </div>
              <div style="display:flex;align-items:center;gap:6px;font-size:13px">
                <i class="bi bi-files" style="color:var(--muted);font-size:14px"></i>
                <strong>${c.file_count.toLocaleString('fr-FR')}</strong>
                <span style="color:var(--muted)">fichiers</span>
              </div>
            </div>
            <div style="text-align:right">
              <i class="bi bi-database" style="font-size:18px;color:var(--muted);display:block;margin-bottom:2px"></i>
              <span style="font-size:18px;font-weight:600">${tb}</span>
            </div>
          </div>
        </div>

        <!-- Résolutions + Codecs -->
        <div style="display:grid;grid-template-columns:1fr 1fr;padding:10px 14px;gap:14px">
          <div>
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase;
                 letter-spacing:.04em;margin-bottom:7px">Résolutions</div>
            ${resHtml || '<span style="font-size:11px;color:var(--muted)">—</span>'}
          </div>
          <div>
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase;
                 letter-spacing:.04em;margin-bottom:7px">Codecs</div>
            ${codHtml || '<span style="font-size:11px;color:var(--muted)">—</span>'}
          </div>
        </div>

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

  function _statBars(items, cls) {
    return (items || []).map(r => `
      <div class="stat-bar-row">
        <span class="stat-bar-label">${esc(r.label.toUpperCase())}</span>
        <div class="stat-bar-bg"><div class="stat-bar-fill ${cls}" style="width:${r.pct}%"></div></div>
        <span class="stat-bar-val">${r.pct}%</span>
      </div>`).join('') || '<span style="font-size:11px;color:var(--muted)">—</span>';
  }

  function _watchProgress(pct) {
    const opacity = Math.max(0.25, pct / 100);
    return `<div class="watch-progress">
      <i class="bi bi-eye" style="font-size:11px;color:var(--muted)"></i>
      <div class="watch-progress-bg">
        <div class="watch-progress-fill" style="width:${pct}%;opacity:${opacity}"></div>
      </div>
      <span class="watch-progress-pct">${pct}%</span>
    </div>`;
  }

function _renderTitle(t) {
    const el  = document.getElementById('library-content');
    const cat = _currentCat;

    const sizeLabel = t.size_gb >= 1024
      ? `${(t.size_gb/1024).toFixed(2)} To`
      : `${t.size_gb} Go`;

    const propBadge = (t.proposals_total > 0) ? `
      <span class="badge badge-warn" style="display:inline-block;margin-bottom:6px">
        ${t.proposals_total} proposition${t.proposals_total > 1 ? 's' : ''}
      </span>` : '';

    el.innerHTML = `
      <div class="breadcrumb">
        <a onclick="Library.init()"><i class="bi bi-house"></i> Bibliothèque</a>
        <i class="bi bi-chevron-right"></i>
        <a onclick="Library.openCategory(${cat?.id})">${esc(cap(cat?.name ?? ''))}</a>
        <i class="bi bi-chevron-right"></i>
        <span>${esc(t.display_name)}</span>
      </div>

      <div class="card" style="margin-bottom:16px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:12px">
          <div style="flex:0 0 220px;min-width:0">
            <div style="font-size:18px;font-weight:600;margin-bottom:4px">
              ${esc(t.display_name)}
              ${t.year ? `<span style="color:var(--muted);font-size:14px;font-weight:400">(${t.year})</span>` : ''}
            </div>
            ${propBadge}
            <div style="font-size:12px;color:var(--muted)">
              ${t.has_seasons ? `${Object.keys(t.seasons).length} saison${Object.keys(t.seasons).length > 1 ? 's' : ''} · ` : ''}
              ${t.file_count} fichier${t.file_count > 1 ? 's' : ''}
            </div>
            ${_watchProgress(t.watched_pct)}
            ${t.folder_status === 'to_rename' ? `
              <span class="badge badge-warn" style="margin-top:6px;display:inline-block">
                <i class="bi bi-folder"></i> Dossier à renommer
              </span>` : ''}
          </div>

          <div style="flex:1;min-width:160px">
            <div class="stat-block-label">Résolutions</div>
            ${_statBars(t.resolutions, 'res')}
          </div>

          <div style="flex:1;min-width:160px">
            <div class="stat-block-label">Codecs</div>
            ${_statBars(t.codecs, 'codec')}
          </div>

          <div class="weight-pill">
            <i class="bi bi-database-fill" style="color:var(--blue)"></i>
            ${sizeLabel}
          </div>
        </div>
      </div>

      ${_renderSeasons(t)}`;
  }

  function _renderTitles(titles) {
    const cat = _currentCat;
    const el  = document.getElementById('library-content');

    el.innerHTML = `
      <div class="breadcrumb">
        <a onclick="Library.init()"><i class="bi bi-house"></i> Bibliothèque</a>
        <i class="bi bi-chevron-right"></i>
        <span>${esc(cap(cat?.name ?? ''))}</span>
      </div>

      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
        <input type="text" id="lib-search" placeholder="Rechercher…"
               style="max-width:280px" oninput="Library.search(this.value, ${cat?.id})">
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
        const propBadge = t.proposals > 0
          ? `<span class="badge badge-warn" style="display:inline-block;margin-bottom:6px">
               ${t.proposals} proposition${t.proposals > 1 ? 's' : ''}
             </span>`
          : '';

        const sizeLabel = t.size_gb >= 1024
          ? `${(t.size_gb/1024).toFixed(2)} To`
          : `${t.size_gb} Go`;

        const meta = [
          t.year ? t.year : null,
          t.season_count > 0 ? `${t.season_count} saison${t.season_count > 1 ? 's' : ''}` : null,
          `${t.file_count} fichier${t.file_count > 1 ? 's' : ''}`,
        ].filter(Boolean).join(' · ');

        // Barre de complétion (vu) — opacité proportionnelle au %
        const wp = t.watched_pct || 0;
        const opacity = Math.max(0.25, wp / 100);
        const watchedBlock = t.file_count > 0 ? `
          <div style="margin-top:8px">
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase;
                 letter-spacing:.04em;margin-bottom:4px">
              <i class="bi bi-eye"></i> Complétion : ${wp}%
            </div>
            <div style="height:5px;background:var(--bg3);border-radius:3px;width:160px">
              <div style="width:${wp}%;height:100%;background:var(--green);
                   opacity:${opacity};border-radius:3px"></div>
            </div>
          </div>` : '';

        const resBars = (t.resolutions || []).map(r => `
          <div style="display:grid;grid-template-columns:42px 1fr 32px;
               gap:8px;align-items:center;margin-bottom:3px">
            <span style="font-size:11px;color:var(--muted)">${esc(r.label)}</span>
            <div style="height:4px;background:var(--bg3);border-radius:2px">
              <div style="width:${r.pct}%;height:100%;background:var(--blue);border-radius:2px"></div>
            </div>
            <span style="font-size:11px;color:var(--muted);text-align:right">${r.pct}%</span>
          </div>`).join('');

        const codBars = (t.codecs || []).map(r => `
          <div style="display:grid;grid-template-columns:50px 1fr 32px;
               gap:8px;align-items:center;margin-bottom:3px">
            <span style="font-size:11px;color:var(--muted)">${esc(r.label)}</span>
            <div style="height:4px;background:var(--bg3);border-radius:2px">
              <div style="width:${r.pct}%;height:100%;background:var(--purple);border-radius:2px"></div>
            </div>
            <span style="font-size:11px;color:var(--muted);text-align:right">${r.pct}%</span>
          </div>`).join('');

        return `<div class="title-row" onclick="Library.openTitle(${t.id})"
                     style="align-items: center;padding:14px 16px">

          <!-- Gauche : titre + propositions + meta + complétion -->
          <div style="flex:0 0 220px;align-self: flex-start;min-width:0">
            <div class="title-name" style="font-size:15px;margin-bottom:4px">
              ${esc(t.display_name)}
            </div>
            ${propBadge}
            <div class="title-meta">${esc(meta)}</div>
            ${watchedBlock}
          </div>

          <!-- Milieu : résolutions -->
          <div style="flex:1;align-self: flex-start;min-width:160px;padding:0 16px">
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase;
                 letter-spacing:.04em;margin-bottom:6px">Résolutions</div>
            ${resBars || '<span style="font-size:11px;color:var(--muted)">—</span>'}
          </div>

          <!-- Milieu : codecs -->
          <div style="flex:1;align-self: flex-start;min-width:160px;padding:0 16px">
            <div style="font-size:10px;color:var(--muted);text-transform:uppercase;
                 letter-spacing:.04em;margin-bottom:6px">Codecs</div>
            ${codBars || '<span style="font-size:11px;color:var(--muted)">—</span>'}
          </div>

          <!-- Droite : poids + chevron -->
          <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;padding-top:2px">
            <div style="display:flex;align-items:center;gap:6px;padding:6px 12px;
                 background:var(--bg3);border-radius:8px;font-size:13px;font-weight:600"
                 title="Taille totale sur le disque">
              <i class="bi bi-database-fill" style="color:var(--blue)"></i>
              ${sizeLabel}
            </div>
            <i class="bi bi-chevron-right" style="color:var(--muted);font-size:14px"></i>
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


function _renderSeasons(t) {
    const entries = Object.entries(t.seasons);
    if (!entries.length) {
      return `<div class="empty-state"><i class="bi bi-file-x"></i> Aucun fichier</div>`;
    }

    if (!t.has_seasons) {
      const items = entries.flatMap(([,v]) => v.items);
      return `<div class="card" style="padding:8px 0">${_renderItems(items, false)}</div>`;
    }

    return entries.map(([season, data]) => {
      const sNum   = season === 'null' ? null : parseInt(season);
      const sLabel = sNum === null ? 'Sans saison'
                   : sNum === 0   ? 'Spéciaux'
                   : `Saison ${String(sNum).padStart(2,'0')}`;
      const toRen  = data.items.filter(i => i.file_status === 'to_rename').length;
      const props  = data.items.filter(i => i.prop_id).length;

      const sizeLabel = data.size_gb >= 1024
        ? `${(data.size_gb/1024).toFixed(2)} To`
        : `${data.size_gb} Go`;

      const propBadgeS = props > 0
        ? `<span class="badge badge-warn" style="display:inline-block;margin-bottom:4px">
             ${props} proposition${props > 1 ? 's' : ''}
           </span>` : '';

      return `<div class="tree-item">
        <div class="season-row" onclick="toggleTree(this.parentElement.querySelector('.tree-body'), this.querySelector('.bi-chevron-right'))">
          <div class="season-info" style="flex:0 0 220px">
            <div style="font-weight:500;font-size:14px">${esc(sLabel)}</div>
            ${propBadgeS}
            ${toRen > 0 ? `<span class="badge badge-warn" style="display:inline-block;margin-bottom:4px;margin-left:4px">${toRen} à renommer</span>` : ''}
            <div style="font-size:11px;color:var(--muted)">
              ${data.file_count} fichier${data.file_count>1?'s':''}
            </div>
            ${_watchProgress(data.watched_pct)}
          </div>
          <div class="season-stats">
            <div class="stat-block-label">Résolutions</div>
            ${_statBars(data.resolutions, 'res')}
          </div>
          <div class="season-stats">
            <div class="stat-block-label">Codecs</div>
            ${_statBars(data.codecs, 'codec')}
          </div>
          <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
            <div class="weight-pill" style="font-size:12px;padding:5px 10px">
              <i class="bi bi-database-fill" style="color:var(--blue);font-size:12px"></i>
              ${sizeLabel}
            </div>            
            <i class="bi bi-chevron-right" style="color:var(--muted);font-size:12px;transition:transform .15s"></i>
          </div>
        </div>
        <div class="tree-body">
          ${_renderItems(data.items, true)}
        </div>
      </div>`;
    }).join('');
  }

  function _renderItems(items, showEp) {
    return items.map(i => {
      const res = i.height
        ? (i.height >= 2160 ? '4K' : i.height >= 1080 ? '1080p' : i.height >= 720 ? '720p' : 'SD')
        : '';
      const dur = formatDuration(i.duration);
      const size = i.size_bytes
        ? (i.size_bytes/1073741824 >= 1
            ? `${(i.size_bytes/1073741824).toFixed(2)} Go`
            : `${(i.size_bytes/1048576).toFixed(0)} Mo`)
        : '';
      const epNum = (i.season !== null && i.episode !== null)
        ? `${String(i.season).padStart(2,'0')}x${String(i.episode).padStart(2,'0')}`
        : '';

      return `<div style="display:flex;align-items:center;justify-content:space-between;
                   padding:8px 4px;border-bottom:1px solid var(--border);font-size:12px"
                   class="title-row" onclick="Library.openItem(${i.item_id})">
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
            ${size ? `<span>${size}</span>` : ''}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-shrink:0">
          ${i.prop_id ? `<span class="badge badge-warn"><i class="bi bi-lightbulb"></i></span>` : ''}
          ${i.file_status === 'to_rename' ? `<span class="badge badge-warn"><i class="bi bi-pencil"></i></span>` : ''}
        </div>
      </div>`;
    }).join('');
  }

  /* ── Détail fichier ───────────────────────────────────────────────────── */
  async function openItem(itemId) {
    const el = document.getElementById('library-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const r = await fetch(`${API}/api/admin/library/items/${itemId}`);
      const item = await r.json();
      _renderItemDetail(item);
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _audioTracksHtml(audio) {
    const codecs = audio?.codecs || [];
    if (!codecs.length) {
      return `<div style="font-size:12px;color:var(--muted)">Aucune piste audio</div>`;
    }
    const n = codecs.length;
    const cols = `60px ${Array(n).fill('1fr').join(' ')}`;

    const headerCells = codecs.map((_, i) =>
      `<div class="audio-track-header">Piste ${i + 1}</div>`).join('');

    const langRow = codecs.map((_, i) =>
      `<div class="audio-track-value">${esc((audio.languages?.[i] || '?').toUpperCase())}</div>`).join('');

    const chanRow = codecs.map((_, i) =>
      `<div class="audio-track-value">${esc(audio.layouts?.[i] || audio.channels?.[i] || '?')}</div>`).join('');

    const codecRow = codecs.map(c =>
      `<div class="audio-track-value">${esc(c.toUpperCase())}</div>`).join('');

    return `<div class="audio-tracks-grid" style="grid-template-columns:${cols}">
      <div></div>${headerCells}
      <div class="audio-track-row-label">Langue</div>${langRow}
      <div class="audio-track-row-label">Canaux</div>${chanRow}
      <div class="audio-track-row-label">Codec</div>${codecRow}
    </div>`;
  }

  function _renderItemDetail(item) {
    const el  = document.getElementById('library-content');
    const cat = _currentCat;

    const epLabel = (item.season !== null && item.episode !== null)
      ? `${String(item.season).padStart(2,'0')}x${String(item.episode).padStart(2,'0')}`
      : null;

    const displayTitle = item.episode_title || item.filename;

    const sizeLabel = item.size_bytes
      ? (item.size_bytes / 1073741824 >= 1
          ? `${(item.size_bytes/1073741824).toFixed(2)} Go`
          : `${(item.size_bytes/1048576).toFixed(0)} Mo`)
      : '—';

    const durationLabel = formatDuration(item.video?.duration_seconds) || '—';
    const resolution = item.video?.height
      ? `${item.video.width}×${item.video.height}`
      : '—';

    const resLabel = item.video?.height
      ? (item.video.height >= 2160 ? '4K' : item.video.height >= 1080 ? '1080p'
         : item.video.height >= 720 ? '720p' : 'SD')
      : '';

    el.innerHTML = `
      <div class="breadcrumb">
        <a onclick="Library.init()"><i class="bi bi-house"></i> Bibliothèque</a>
        <i class="bi bi-chevron-right"></i>
        <a onclick="Library.openCategory(${cat?.id})">${esc(cap(cat?.name ?? item.category))}</a>
        <i class="bi bi-chevron-right"></i>
        <a onclick="Library.openTitle(${item.title_id})">${esc(item.title_name)}</a>
        <i class="bi bi-chevron-right"></i>
        <span>${epLabel ? epLabel + ' — ' : ''}${esc(displayTitle)}</span>
      </div>

      ${item.proposal ? `
        <div class="item-detail-banner">
          <div class="item-detail-banner-text">
            <i class="bi bi-lightbulb"></i>
            Une proposition de renommage existe pour ce fichier
          </div>
          <button class="btn btn-sm" onclick="Rename.openTitle(${item.title_id}); switchTab('rename')">
            Voir <i class="bi bi-arrow-right"></i>
          </button>
        </div>` : ''}

      <div class="item-detail-header">
        <div>
          <div class="item-detail-title">
            ${epLabel ? `<span style="color:var(--blue);font-family:monospace">${epLabel}</span> — ` : ''}
            ${esc(displayTitle)}
          </div>
          <div class="item-detail-sub">${esc(item.title_name)}</div>
        </div>
        <button class="item-watch-btn${item.watched ? ' watched' : ''}"
                onclick="Library.toggleWatched(${item.item_id}, ${!item.watched})">
          <i class="bi bi-eye${item.watched ? '-fill' : ''}"></i>
          ${item.watched ? 'Vu' : 'Marquer comme vu'}
        </button>
      </div>

      <div class="item-detail-grid item-detail-grid-vertical">

        <div class="item-detail-section">
          <div class="item-detail-section-title">
            <i class="bi bi-file-earmark"></i> Fichier
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Nom</span>
            <span class="item-detail-value" style="font-family:monospace;font-size:11px;
                 max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
                 title="${esc(item.filename)}">${esc(item.filename)}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Taille</span>
            <span class="item-detail-value">${sizeLabel}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Format</span>
            <span class="item-detail-value">${(item.video?.container || item.extension || '—').toUpperCase()}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">État disque</span>
            <span class="item-detail-value">
              ${item.disk_status === 'present'
                ? '<span style="color:var(--green)">Présent</span>'
                : `<span style="color:var(--orange)">${esc(item.disk_status)}</span>`}
            </span>
          </div>
        </div>

        <div class="item-detail-section">
          <div class="item-detail-section-title">
            <i class="bi bi-camera-video"></i> Vidéo
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Codec</span>
            <span class="item-detail-value">${(item.video?.codec || '—').toUpperCase()}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Résolution</span>
            <span class="item-detail-value">${resolution} ${resLabel ? `(${resLabel})` : ''}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">FPS</span>
            <span class="item-detail-value">${item.video?.fps ? item.video.fps.toFixed(2) : '—'}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Bitrate</span>
            <span class="item-detail-value">${item.video?.bitrate ? Math.round(item.video.bitrate/1000) + ' kb/s' : '—'}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">HDR</span>
            <span class="item-detail-value">
              ${item.video?.hdr_format && item.video.hdr_format !== 'SDR'
                ? `<span style="color:var(--purple)">${esc(item.video.hdr_format)}</span>`
                : 'SDR'}
            </span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Durée</span>
            <span class="item-detail-value">${durationLabel}</span>
          </div>
        </div>

         <div class="item-detail-section">
          <div class="item-detail-section-title">
            <i class="bi bi-volume-up"></i> Audio
            <span style="margin-left:auto;font-size:11px;color:var(--muted);font-weight:400">
              ${item.audio?.codecs?.length || 0} piste${(item.audio?.codecs?.length||0) > 1 ? 's' : ''}
            </span>
          </div>
          ${_audioTracksHtml(item.audio)}
        </div>

        <div class="item-detail-section">
          <div class="item-detail-section-title">
            <i class="bi bi-chat-square-text"></i> Sous-titres
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Nombre de pistes</span>
            <span class="item-detail-value">${item.subtitles?.count ?? 0}</span>
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Langues</span>
            <span class="item-detail-value">${item.subtitles?.languages?.join(', ') || 'Aucune'}</span>
          </div>
        </div>

      </div>
      
      <div class="debug-section">
        <div class="debug-header" onclick="Library.toggleDebug(this)">
          <i class="bi bi-bug"></i>
          Informations techniques complètes (debug)
          <i class="bi bi-chevron-right debug-chevron"></i>
        </div>
        <div class="debug-body">${esc(JSON.stringify(item, null, 2))}</div>
      </div>`;
  }

  function toggleDebug(header) {
    const body = header.nextElementSibling;
    const icon = header.querySelector('.debug-chevron');
    const open = body.classList.toggle('open');
    icon.style.transform = open ? 'rotate(90deg)' : '';
  }

  async function toggleWatched(itemId, newState) {
    try {
      const r = await fetch(`${API}/api/admin/library/items/${itemId}/watched`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ watched: newState }),
      });
      if (!r.ok) throw new Error('Erreur');
      // Recharger la fiche
      openItem(itemId);
    } catch(e) {
      alert('Erreur : ' + e.message);
    }
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }

  function toggleTree(body, icon) {
    const open = body.classList.toggle('open');
    if (icon) icon.style.transform = open ? 'rotate(90deg)' : '';
  }

  function formatDuration(seconds) {
    if (!seconds) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h${String(m).padStart(2,'0')}`;
    return `${m}min`;
  }

  // Exposer toggleTree globalement pour les onclick dans le HTML généré
  window.toggleTree = toggleTree;

  return { init, openCategory, openTitle, search, openItem, toggleWatched, toggleDebug };

})();