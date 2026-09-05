/* =============================================================================
   MediaManager 2026 — library.js
   Navigation bibliothèque : catégories → titres → détail
   ============================================================================= */

const Library = (() => {

  let _categories   = [];
  let _trash        = null;
  let _currentCat   = null;
  let _currentTitle = null;
  let _offset       = 0;
  let _limit        = 50;
  let _total        = 0;
  let _searchQuery  = '';
  let _searchTimer  = null;

  /* ── Entrée publique ──────────────────────────────────────────────────── */
  async function init() {
    await _loadCategories();
  }

  /* ── Catégories ───────────────────────────────────────────────────────── */
  async function _loadCategories() {
    const el = document.getElementById('library-content');
    el.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;

    try {
      const [catRes, trashRes] = await Promise.all([
        fetch(`${API}/api/admin/library/categories/stats`),
        fetch(`${API}/api/admin/library/trash`).catch(() => null),
      ]);
      _categories = await catRes.json();
      _trash      = trashRes && trashRes.ok ? await trashRes.json() : null;
      _renderCategories();
    } catch(e) {
      el.innerHTML = `<div class="empty-state">
        <i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _fmtBytes(bytes) {
    if (!bytes) return '0 Go';
    if (bytes >= 1099511627776) return (bytes / 1099511627776).toFixed(1).replace('.', ',') + ' To';
    if (bytes >= 1073741824)    return (bytes / 1073741824).toFixed(1).replace('.', ',') + ' Go';
    if (bytes >= 1048576)       return (bytes / 1048576).toFixed(0) + ' Mo';
    return bytes + ' o';
  }

  function _trashBannerHtml() {
    if (!_trash || !_trash.folders || !_trash.folders.length) return '';
    const n = _trash.folders.length;
    const sizeLabel = _fmtBytes(_trash.total_bytes);
    return `
      <div class="trash-banner">
        <i class="bi bi-trash3"></i>
        <span>
          <strong>${n} dossier${n > 1 ? 's' : ''} corbeille</strong>
          détecté${n > 1 ? 's' : ''} sur le NAS —
          <span class="trash-banner-size">${sizeLabel}</span> récupérables
          en vidant la corbeille.
        </span>
      </div>`;
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
      ${_trashBannerHtml()}
      <div class="cat-grid">
        ${visible.map(c => _categoryCardHtml(c)).join('')}
      </div>`;
  }

  function _categoryCardHtml(c) {
    const tb    = c.total_tb >= 1 ? `${c.total_tb} To` : `${Math.round(c.total_tb * 1024)} Go`;
    const icon  = c.has_seasons ? 'bi-tv' : 'bi-film';
    const badge = c.has_seasons
      ? `<span class="cat-badge cat-badge-seasonal">Saisonnable</span>`
      : `<span class="cat-badge cat-badge-film">Film</span>`;

    const resHtml = c.resolutions.map(r => `
      <div class="prog-row">
        <span class="text-muted">${esc(r.label)}</span>
        <span class="fw-500">${r.pct}%</span>
      </div>
      <div class="prog-track"><div class="prog-fill prog-fill-blue" style="width:${r.pct}%"></div></div>
    `).join('');

    const codHtml = c.codecs.map(r => `
      <div class="prog-row">
        <span class="text-muted">${esc(r.label)}</span>
        <span class="fw-500">${r.pct}%</span>
      </div>
      <div class="prog-track"><div class="prog-fill prog-fill-purple" style="width:${r.pct}%"></div></div>
    `).join('');

    return `
      <div class="cat-card" onclick="Library.openCategory(${c.id})">

        <div class="cat-card-head">
          <div class="cat-card-brand">
            <i class="bi ${icon} cat-card-icon"></i>
            <span class="cat-card-name">${esc(cap(c.name))}</span>
          </div>
          ${badge}
        </div>

        <div class="cat-card-body">
          <div class="cat-card-counts">
            <div class="cat-card-count-list">
              <div class="cat-card-count-row">
                <i class="bi bi-collection-play cat-count-icon"></i>
                <strong>${c.title_count.toLocaleString('fr-FR')}</strong>
                <span class="text-muted">titres</span>
              </div>
              <div class="cat-card-count-row">
                <i class="bi bi-files cat-count-icon"></i>
                <strong>${c.file_count.toLocaleString('fr-FR')}</strong>
                <span class="text-muted">fichiers</span>
              </div>
            </div>
            <div class="cat-card-size">
              <i class="bi bi-database cat-card-size-icon"></i>
              <span class="cat-card-size-val">${tb}</span>
            </div>
          </div>
        </div>

        <div class="cat-card-stats">
          <div>
            <div class="cat-stat-label">Résolutions</div>
            ${resHtml || '<span class="stat-blank">—</span>'}
          </div>
          <div>
            <div class="cat-stat-label">Codecs</div>
            ${codHtml || '<span class="stat-blank">—</span>'}
          </div>
        </div>

      </div>`;
  }


  /* ── Titres ───────────────────────────────────────────────────────────── */
  async function openCategory(catId) {
    _currentCat  = _categories.find(c => c.id === catId);
    _offset      = 0;
    _searchQuery = '';
    await _fetchTitles(true);
  }

  async function _fetchTitles(fullRender = false) {
    const catId = _currentCat?.id;
    if (!catId) return;

    let url = `${API}/api/admin/library/titles?category_id=${catId}&limit=${_limit}&offset=${_offset}`;
    if (_searchQuery) url += `&search=${encodeURIComponent(_searchQuery)}`;

    if (fullRender) {
      document.getElementById('library-content').innerHTML =
        `<div class="empty-state"><span class="spinner"></span></div>`;
    } else {
      const list = document.getElementById('titles-list');
      if (list) list.innerHTML = `<div class="empty-state"><span class="spinner"></span></div>`;
    }

    try {
      const r    = await fetch(url);
      const data = await r.json();
      _total = data.total;
      if (fullRender) {
        _renderTitles(data.items);
      } else {
        _updateTitlesArea(data.items);
      }
    } catch(e) {
      document.getElementById('library-content').innerHTML =
        `<div class="empty-state"><i class="bi bi-wifi-off"></i> Erreur de chargement</div>`;
    }
  }

  function _updateTitlesArea(items) {
    const countEl = document.getElementById('lib-count');
    if (countEl) countEl.textContent = _countLabel();
    document.querySelectorAll('#lib-pagination, #lib-pagination-bottom').forEach(el => {
      el.innerHTML = _paginationHtml();
    });
    const list = document.getElementById('titles-list');
    if (list) list.innerHTML = _titlesHtml(items);
  }

  function _countLabel() {
    if (!_total) return 'Aucun résultat';
    const from = _offset + 1;
    const to   = Math.min(_offset + _limit, _total);
    return `${from} – ${to} sur ${_total}`;
  }

  function _paginationHtml() {
    const pages   = Math.ceil(_total / _limit);
    const current = Math.floor(_offset / _limit) + 1;
    const prevOk  = _offset > 0;
    const nextOk  = _offset + _limit < _total;
    const limitSel = [25, 50, 100, 150, 200].map(n =>
      `<option value="${n}"${n === _limit ? ' selected' : ''}>${n}</option>`
    ).join('');

    return `
      ${pages > 1 ? `
        <button class="btn btn-sm" ${prevOk ? '' : 'disabled'} onclick="Library.changePage(-1)">
          <i class="bi bi-chevron-left"></i>
        </button>
        <span class="lib-page-info">${current} / ${pages}</span>
        <button class="btn btn-sm" ${nextOk ? '' : 'disabled'} onclick="Library.changePage(1)">
          <i class="bi bi-chevron-right"></i>
        </button>` : ''}
      <select class="lib-limit-sel" onchange="Library.changeLimit(+this.value)">${limitSel}</select>`;
  }

  function changePage(dir) {
    _offset = Math.max(0, Math.min(_offset + dir * _limit, (_total - 1)));
    _offset = Math.floor(_offset / _limit) * _limit;
    _fetchTitles(true);
  }

  function changeLimit(n) {
    _limit  = n;
    _offset = 0;
    _fetchTitles(true);
  }

  function _statBars(items, cls) {
    return (items || []).map(r => `
      <div class="stat-bar-row">
        <span class="stat-bar-label">${esc(r.label.toUpperCase())}</span>
        <div class="stat-bar-bg"><div class="stat-bar-fill ${cls}" style="width:${r.pct}%"></div></div>
        <span class="stat-bar-val">${r.pct}%</span>
      </div>`).join('') || '<span class="stat-blank">—</span>';
  }

  function _watchProgress(pct) {
    const opacity = Math.max(0.25, pct / 100);
    return `<div class="watch-progress">
      <i class="bi bi-eye"></i>
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
      <span class="badge badge-warn badge-block-b">
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

      <div class="card card-mb">
        <div class="title-card-inner">
          <div class="title-info-col">
            <div class="title-heading-lg">
              ${esc(t.display_name)}
              ${t.year ? `<span class="title-year">(${t.year})</span>` : ''}
            </div>
            ${propBadge}
            <div class="title-meta">
              ${t.has_seasons ? `${Object.keys(t.seasons).length} saison${Object.keys(t.seasons).length > 1 ? 's' : ''} · ` : ''}
              ${t.file_count} fichier${t.file_count > 1 ? 's' : ''}
            </div>
            ${_watchProgress(t.watched_pct)}
            ${t.folder_status === 'to_rename' ? `
              <span class="badge badge-warn badge-block-t">
                <i class="bi bi-folder"></i> Dossier à renommer
              </span>` : ''}
          </div>

          <div class="title-stat-col">
            <div class="stat-block-label">Résolutions</div>
            ${_statBars(t.resolutions, 'res')}
          </div>

          <div class="title-stat-col">
            <div class="stat-block-label">Codecs</div>
            ${_statBars(t.codecs, 'codec')}
          </div>

          <div class="weight-pill">
            <i class="bi bi-database-fill"></i>
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

      <div class="lib-toolbar">
        <input type="text" id="lib-search" placeholder="Rechercher…"
               value="${esc(_searchQuery)}"
               oninput="Library.search(this.value)">
        <span id="lib-count" class="lib-count">${_countLabel()}</span>
        <div id="lib-pagination" class="lib-pagination">${_paginationHtml()}</div>
      </div>

      <div id="titles-list">
        ${_titlesHtml(titles)}
      </div>

      <div class="lib-toolbar lib-toolbar-bottom">
        <div id="lib-pagination-bottom" class="lib-pagination">${_paginationHtml()}</div>
      </div>`;
  }

  function _titlesHtml(titles) {
    if (!titles.length) {
      return `<div class="empty-state"><i class="bi bi-search"></i> Aucun résultat</div>`;
    }
    return `<div class="card card-flush">
      ${titles.map(t => {
        const propBadge = t.proposals > 0
          ? `<span class="badge badge-warn badge-block-b">
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

        const wp = t.watched_pct || 0;
        const opacity = Math.max(0.25, wp / 100);
        const watchedBlock = t.file_count > 0 ? `
          <div class="watched-block">
            <div class="watched-label"><i class="bi bi-eye"></i> Complétion : ${wp}%</div>
            <div class="watched-bar">
              <div class="watched-fill" style="width:${wp}%;opacity:${opacity}"></div>
            </div>
          </div>` : '';

        const resBars = (t.resolutions || []).map(r => `
          <div class="mini-bar-row">
            <span class="mini-bar-label">${esc(r.label)}</span>
            <div class="mini-bar-bg"><div class="mini-bar-fill res" style="width:${r.pct}%"></div></div>
            <span class="mini-bar-val">${r.pct}%</span>
          </div>`).join('');

        const codBars = (t.codecs || []).map(r => `
          <div class="mini-bar-row codec">
            <span class="mini-bar-label">${esc(r.label)}</span>
            <div class="mini-bar-bg"><div class="mini-bar-fill codec" style="width:${r.pct}%"></div></div>
            <span class="mini-bar-val">${r.pct}%</span>
          </div>`).join('');

        return `<div class="title-row title-row-list" onclick="Library.openTitle(${t.id})">

          <div class="title-info-col">
            <div class="title-heading-md">${esc(t.display_name)}</div>
            ${propBadge}
            <div class="title-meta">${esc(meta)}</div>
            ${watchedBlock}
          </div>

          <div class="title-stat-col title-stat-col-padded">
            <div class="stat-block-label">Résolutions</div>
            ${resBars || '<span class="stat-blank">—</span>'}
          </div>

          <div class="title-stat-col title-stat-col-padded">
            <div class="stat-block-label">Codecs</div>
            ${codBars || '<span class="stat-blank">—</span>'}
          </div>

          <div class="title-right-col">
            <div class="title-size-pill" title="Taille totale sur le disque">
              <i class="bi bi-database-fill"></i>
              ${sizeLabel}
            </div>
            <i class="bi bi-chevron-right nav-chevron"></i>
          </div>

        </div>`;
      }).join('')}
    </div>`;
  }

  function search(query) {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(() => {
      _searchQuery = query;
      _offset      = 0;
      _fetchTitles(false);
    }, 300);
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

    // Le bonus a son propre bloc repliable (comme une saison) — jamais mélangé
    // au contenu principal, qu'il y ait des saisons ou non (film unique).
    const bonusEntry     = entries.find(([k]) => k === 'bonus');
    const regularEntries = entries.filter(([k]) => k !== 'bonus');
    const bonusHtml      = bonusEntry ? _seasonBlockHtml('bonus', bonusEntry[1]) : '';

    if (!t.has_seasons) {
      // Même traitement visuel que le corps d'une saison (fond distinct, marges),
      // pas de header saison puisqu'il n'y a rien à replier pour le contenu principal.
      const items = regularEntries.flatMap(([,v]) => v.items);
      return `<div class="tree-item"><div class="tree-body open">${_renderItems(items, false)}</div></div>` + bonusHtml;
    }

    return regularEntries.map(([season, data]) => _seasonBlockHtml(season, data)).join('') + bonusHtml;
  }

  function _seasonBlockHtml(season, data) {
    const isBonus = season === 'bonus';
    const sNum    = season === 'null' ? null : parseInt(season);
    const sLabel  = isBonus ? 'Bonus'
                  : sNum === null ? 'Sans saison'
                  : sNum === 0    ? 'Spéciaux'
                  : `Saison ${String(sNum).padStart(2,'0')}`;
    const toRen  = data.items.filter(i => i.file_status === 'to_rename').length;
    const props  = data.items.filter(i => i.prop_id).length;

    const sizeLabel = data.size_gb >= 1024
      ? `${(data.size_gb/1024).toFixed(2)} To`
      : `${data.size_gb} Go`;

    const propBadgeS = props > 0
      ? `<span class="badge badge-warn badge-block-b">${props} proposition${props > 1 ? 's' : ''}</span>` : '';

    return `<div class="tree-item${isBonus ? ' tree-item-bonus' : ''}">
      <div class="season-row" onclick="toggleTree(this.parentElement.querySelector('.tree-body'), this.querySelector('.tree-chevron'))">
        <div class="season-info">
          <div class="season-name">${isBonus ? '<i class="bi bi-gift-fill bonus-icon"></i> ' : ''}${esc(sLabel)}</div>
          ${propBadgeS}
          ${toRen > 0 ? `<span class="badge badge-warn badge-block-b" style="margin-left:4px">${toRen} à renommer</span>` : ''}
          <div class="season-file-count">${data.file_count} fichier${data.file_count>1?'s':''}</div>
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
        <div class="season-right">
          <div class="weight-pill weight-pill-sm">
            <i class="bi bi-database-fill"></i>
            ${sizeLabel}
          </div>
          <i class="bi bi-chevron-right tree-chevron"></i>
        </div>
      </div>
      <div class="tree-body">
        ${_renderItems(data.items, true)}
      </div>
    </div>`;
  }

  function _renderItems(items, showEp) {
    return items.map(i => {
      const res = i.height
        ? ((i.width >= 3840 || i.height >= 2160) ? '4K' : (i.width >= 1920 || i.height >= 1080) ? '1080p' : (i.width >= 1280 || i.height >= 720) ? '720p' : 'SD')
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

      return `<div class="item-row" onclick="Library.openItem(${i.item_id})">
        <div class="item-main">
          <div class="item-title-line">
            ${showEp && epNum ? `<span class="item-ep-num">${epNum}</span>` : ''}
            <span class="item-title-text">${esc(i.episode_title || i.filename)}</span>
          </div>
          <div class="item-meta">
            ${i.codec ? `<span>${i.codec.toUpperCase()}</span>` : ''}
            ${res ? `<span>${res}</span>` : ''}
            ${i.hdr && i.hdr !== 'SDR' ? `<span class="item-hdr-badge">${i.hdr}</span>` : ''}
            ${dur ? `<span>${dur}</span>` : ''}
            ${size ? `<span>${size}</span>` : ''}
          </div>
        </div>
        <div class="item-badges">
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

  function _parseChannelLayout(layoutStr) {
    const LAYOUTS = {
      'mono':           ['FC'],
      'stereo':         ['FL','FR'],
      '2.1':            ['FL','FR','LFE'],
      '3.0':            ['FL','FR','FC'],
      '3.0(back)':      ['FL','FR','BC'],
      '4.0':            ['FL','FR','FC','BC'],
      'quad':           ['FL','FR','BL','BR'],
      'quad(side)':     ['FL','FR','SL','SR'],
      '4.1':            ['FL','FR','FC','LFE','BC'],
      '5.0':            ['FL','FR','FC','BL','BR'],
      '5.0(side)':      ['FL','FR','FC','SL','SR'],
      '5.1':            ['FL','FR','FC','LFE','BL','BR'],
      '5.1(side)':      ['FL','FR','FC','LFE','SL','SR'],
      '6.0':            ['FL','FR','FC','BC','SL','SR'],
      '6.1':            ['FL','FR','FC','LFE','BC','SL','SR'],
      '7.0':            ['FL','FR','FC','BL','BR','SL','SR'],
      '7.1':            ['FL','FR','FC','LFE','BL','BR','SL','SR'],
      '7.1(wide)':      ['FL','FR','FC','LFE','BL','BR','FLC','FRC'],
      'octagonal':      ['FL','FR','FC','BL','BR','BC','SL','SR'],
    };
    const key = (layoutStr || '').toLowerCase();
    if (LAYOUTS[key]) return new Set(LAYOUTS[key]);
    // Explicit channel list (FL+FR+FC...)
    return new Set((layoutStr || '').toUpperCase().split(/[+\s,]+/).filter(Boolean));
  }

  function _speakerDiagram(layoutStr) {
    if (!layoutStr) return '';
    const active = _parseChannelLayout(layoutStr);
    const on  = ch => active.has(ch);
    const spk = (ch, label, extra) =>
      `<div class="spk-node ${on(ch) ? 'spk-on' : 'spk-off'}${extra ? ' '+extra : ''}" title="${ch}">${label}</div>`;
    const empty = () => `<div class="spk-empty"></div>`;

    const hasSide  = on('SL') || on('SR');
    const hasBack  = on('BL') || on('BR') || on('BC');
    const hasFront = on('FL') || on('FR') || on('FC');

    const frontRow = `<div class="spk-row">
      ${hasFront ? spk('FL','FL') : empty()}
      ${spk('FC','C')}
      ${hasFront ? spk('FR','FR') : empty()}
    </div>`;

    const midRow = `<div class="spk-row">
      ${spk('SL','SL')}
      ${spk('LFE','⊕','spk-lfe')}
      ${spk('SR','SR')}
    </div>`;

    const rearRow = `<div class="spk-row">
      ${on('BL') || on('BC') || on('BR') ? spk('BL','BL') : empty()}
      ${spk('BC','BC')}
      ${on('BL') || on('BC') || on('BR') ? spk('BR','BR') : empty()}
    </div>`;

    return `<div class="spk-diagram">${frontRow}${midRow}${rearRow}</div>`;
  }

  function _audioTracksHtml(audio) {
    const tracks = audio?.tracks || [];
    if (!tracks.length) {
      return `<div class="stat-blank">Aucune piste audio</div>`;
    }
    const n = tracks.length;
    const cols = `72px ${Array(n).fill('1fr').join(' ')}`;

    const headerCells = tracks.map((t, i) =>
      `<div class="audio-track-header">Piste ${i + 1}${t.is_default ? ' ★' : ''}</div>`).join('');

    const langRow = tracks.map(t =>
      `<div class="audio-track-value" title="${esc((t.lang || '').toUpperCase())}">${esc(t.lang_label || (t.lang || '?').toUpperCase())}</div>`).join('');

    const fmtRow = tracks.map(t =>
      `<div class="audio-track-format">${esc(t.format || (t.codec || '?').toUpperCase())}</div>`).join('');

    const chanRow = tracks.map(t =>
      `<div class="audio-track-value">${esc(t.layout || t.channels || '?')}</div>`).join('');

    const layoutRow = tracks.map(t =>
      `<div class="audio-track-value">${_speakerDiagram(t.layout)}</div>`).join('');

    const brRow = tracks.map(t => {
      const label = t.bitrate ? `${Math.round(t.bitrate / 1000)} kb/s` : '—';
      return `<div class="audio-track-bitrate">${label}</div>`;
    }).join('');

    return `<div class="audio-tracks-grid" style="grid-template-columns:${cols}">
      <div></div>${headerCells}
      <div class="audio-track-row-label">Langue</div>${langRow}
      <div class="audio-track-row-label">Format</div>${fmtRow}
      <div class="audio-track-row-label">Canaux</div>${chanRow}
      <div class="audio-track-row-label">Layout</div>${layoutRow}
      <div class="audio-track-row-label">Débit</div>${brRow}
    </div>`;
  }

  function _subtitleTracksHtml(subtitles) {
    const tracks = subtitles?.tracks || [];
    if (!tracks.length) {
      return `<div class="stat-blank">Aucune piste de sous-titres</div>`;
    }
    // Le tag "title" (ex: "Fr Forced" / "Fr Full") distingue des pistes
    // partageant la même langue — is_forced n'est pas toujours fiable côté mux.
    return `<div class="sub-tracks-list">
      ${tracks.map((t, i) => `
        <div class="sub-track-row">
          <span class="sub-track-lang" title="${esc((t.lang || '').toUpperCase())}">${esc(t.label || (t.lang || '?').toUpperCase())}</span>
          <span class="sub-track-title">${esc(t.title || `Piste ${i + 1}`)}</span>
          <span class="sub-track-badges">
            ${t.is_default ? '<span class="track-badge track-badge-default">Défaut</span>' : ''}
            ${t.is_forced  ? '<span class="track-badge track-badge-forced">Forcé</span>'   : ''}
          </span>
        </div>`).join('')}
    </div>`;
  }

  // Épisode précédent/suivant dans la même saison (à partir des données de
  // _currentTitle déjà chargées — pas de requête réseau supplémentaire).
  function _siblingItems(item) {
    if (!_currentTitle || _currentTitle.id !== item.title_id) return { prev: null, next: null };
    const seasonData = _currentTitle.seasons?.[String(item.season)];
    const items = seasonData?.items || [];
    const idx = items.findIndex(i => i.item_id === item.item_id);
    if (idx === -1) return { prev: null, next: null };
    return {
      prev: idx > 0 ? items[idx - 1] : null,
      next: idx < items.length - 1 ? items[idx + 1] : null,
    };
  }

  function _itemNavHtml(prev, next) {
    if (!prev && !next) return '';
    const label = (i) => {
      if (i.season !== null && i.episode !== null) {
        return `${String(i.season).padStart(2,'0')}x${String(i.episode).padStart(2,'0')}`;
      }
      return esc(i.episode_title || i.filename);
    };
    const prevBtn = prev
      ? `<button class="btn btn-sm item-nav-btn" onclick="Library.openItem(${prev.item_id})" title="${esc(prev.episode_title || prev.filename)}">
           <i class="bi bi-chevron-left"></i> ${label(prev)}
         </button>`
      : `<button class="btn btn-sm item-nav-btn" disabled><i class="bi bi-chevron-left"></i> Précédent</button>`;
    const nextBtn = next
      ? `<button class="btn btn-sm item-nav-btn" onclick="Library.openItem(${next.item_id})" title="${esc(next.episode_title || next.filename)}">
           ${label(next)} <i class="bi bi-chevron-right"></i>
         </button>`
      : `<button class="btn btn-sm item-nav-btn" disabled>Suivant <i class="bi bi-chevron-right"></i></button>`;
    return `<div class="item-nav-row">${prevBtn}${nextBtn}</div>`;
  }

  function _renderItemDetail(item) {
    const el  = document.getElementById('library-content');
    const cat = _currentCat;

    const epLabel = (item.season !== null && item.episode !== null)
      ? `${String(item.season).padStart(2,'0')}x${String(item.episode).padStart(2,'0')}`
      : null;

    const displayTitle = item.episode_title || item.filename;
    const { prev, next } = _siblingItems(item);

    const sizeLabel = item.size_bytes
      ? (item.size_bytes / 1073741824 >= 1
          ? `${(item.size_bytes/1073741824).toFixed(2)} Go`
          : `${(item.size_bytes/1048576).toFixed(0)} Mo`)
      : '—';

    const durationLabel = formatDuration(item.video?.duration_seconds) || '—';
    const resolution = item.video?.height
      ? `${item.video.width}×${item.video.height}`
      : '—';

    const _w = item.video?.width || 0, _h = item.video?.height || 0;
    const resLabel = (_w || _h)
      ? ((_w >= 3840 || _h >= 2160) ? '4K' : (_w >= 1920 || _h >= 1080) ? '1080p'
         : (_w >= 1280 || _h >= 720) ? '720p' : 'SD')
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
            ${epLabel ? `<span class="ep-badge">${epLabel}</span> — ` : ''}
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

      ${_itemNavHtml(prev, next)}

      <div class="item-detail-grid item-detail-grid-vertical">

        <div class="item-detail-section">
          <div class="item-detail-section-title">
            <i class="bi bi-file-earmark"></i> Fichier
          </div>
          <div class="item-detail-row">
            <span class="item-detail-label">Nom</span>
            <span class="item-detail-value filename-mono" title="${esc(item.filename)}">${esc(item.filename)}</span>
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
                ? '<span class="status-ok">Présent</span>'
                : `<span class="status-warn">${esc(item.disk_status)}</span>`}
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
              ${(item.video?.hdr_formats || []).length
                ? item.video.hdr_formats.map(h => `<span class="hdr-badge">${esc(h)}</span>`).join(' ')
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
            <span class="audio-count">
              ${item.audio?.tracks?.length || 0} piste${(item.audio?.tracks?.length||0) > 1 ? 's' : ''}
            </span>
          </div>
          ${_audioTracksHtml(item.audio)}
        </div>

        <div class="item-detail-section">
          <div class="item-detail-section-title">
            <i class="bi bi-chat-square-text"></i> Sous-titres
            <span class="audio-count">
              ${item.subtitles?.count || 0} piste${(item.subtitles?.count||0) > 1 ? 's' : ''}
            </span>
          </div>
          ${_subtitleTracksHtml(item.subtitles)}
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

  window.toggleTree = toggleTree;

  return { init, openCategory, openTitle, search, openItem, toggleWatched, toggleDebug, changePage, changeLimit };

})();
