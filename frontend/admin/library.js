/* =============================================================================
   MediaManager 2026 — library.js
   Onglet Bibliothèque : filtres cumulatifs + liste paginée de fichiers
   ============================================================================= */

const Library = (() => {
  const LIMIT = 50;

  let _opts    = null;
  let _loading = false;
  let _state   = {
    cat_id:        null,
    resolutions:   new Set(),
    codecs:        new Set(),
    hdr:           new Set(),
    langs_audio:   new Set(),
    langs_sub:     new Set(),
    disk_statuses: new Set(),
    page:          1,
  };

  /* ── Public ──────────────────────────────────────────────────────────── */

  async function load() {
    await _fetchOpts();
    _renderFilters();
    await _fetchFiles();
    _fetchTrash();
  }

  // Ouvre la bibliothèque avec un seul filtre "statut disque" pré-appliqué
  // (utilisé par les liens "Voir" du dashboard : missing/duplicate)
  async function loadWithStatus(status) {
    _state.cat_id = null;
    ['resolutions', 'codecs', 'hdr', 'langs_audio', 'langs_sub', 'disk_statuses']
      .forEach(k => _state[k].clear());
    _state.disk_statuses.add(status);
    _state.page = 1;
    await _fetchOpts();
    _renderFilters();
    _renderCats();
    await _fetchFiles();
    _fetchTrash();
  }

  function toggle(dim, value) {
    if (_state[dim].has(value)) _state[dim].delete(value);
    else                        _state[dim].add(value);
    _state.page = 1;
    _renderFilters();
    _fetchFiles();
  }

  function setPage(p) {
    _state.page = p;
    _fetchFiles();
    document.getElementById('panel-library')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function reset() {
    ['resolutions', 'codecs', 'hdr', 'langs_audio', 'langs_sub', 'disk_statuses']
      .forEach(k => _state[k].clear());
    _state.page = 1;
    _renderFilters();
    _fetchFiles();
  }

  async function reanalyze() {
    const scopeLabel = _state.cat_id
      ? `la catégorie « ${_opts?.categories?.find(c => c.id === _state.cat_id)?.name || '?'} »`
      : 'toute la bibliothèque';
    const confirmed = confirm(
      `Réanalyser ${scopeLabel} ?\n\n` +
      `Les métadonnées actuelles (codec, bitrate, pistes audio/sous-titres, HDR) seront ` +
      `supprimées et ré-extraites depuis les fichiers. Les fichiers concernés disparaîtront ` +
      `temporairement de la bibliothèque jusqu'à leur ré-analyse.`
    );
    if (!confirmed) return;

    try {
      const r = await fetch(`${API}/api/admin/library/reanalyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cat_id: _state.cat_id }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      alert(`${d.reset_count} fichier${d.reset_count > 1 ? 's' : ''} remis en file d'analyse.`);
      _state.page = 1;
      await _fetchOpts();
      _renderFilters();
      _fetchFiles();
      _fetchTrash();
    } catch (e) {
      alert('Erreur : ' + e.message);
    }
  }

  async function cleanMissing() {
    const scopeLabel = _state.cat_id
      ? `la catégorie « ${_opts?.categories?.find(c => c.id === _state.cat_id)?.name || '?'} »`
      : 'toute la bibliothèque';
    const confirmed = confirm(
      `Supprimer définitivement tous les fichiers manquants de ${scopeLabel} ?\n\n` +
      `Cette action est irréversible — les entrées et leurs métadonnées seront ` +
      `retirées de la base. Si un fichier réapparaît sur le NAS, il sera re-scanné ` +
      `comme un nouveau fichier.`
    );
    if (!confirmed) return;

    try {
      const r = await fetch(`${API}/api/admin/library/clean-missing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cat_id: _state.cat_id }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      alert(`${d.deleted_count} fichier${d.deleted_count > 1 ? 's' : ''} supprimé${d.deleted_count > 1 ? 's' : ''}.`);
      _state.page = 1;
      await _fetchOpts();
      _renderFilters();
      _fetchFiles();
      _fetchTrash();
    } catch (e) {
      alert('Erreur : ' + e.message);
    }
  }

  async function setCat(id) {
    _state.cat_id = id ? Number(id) : null;
    ['resolutions', 'codecs', 'hdr', 'langs_audio', 'langs_sub', 'disk_statuses']
      .forEach(k => _state[k].clear());
    _state.page = 1;
    await _fetchOpts();
    _renderFilters();
    _fetchFiles();
    _fetchTrash();
  }

  /* ── Private ─────────────────────────────────────────────────────────── */

  async function _fetchTrash() {
    const banner = document.getElementById('lb-trash-banner');
    if (!banner) return;
    const qs = _state.cat_id ? `?cat_id=${_state.cat_id}` : '';
    try {
      const r = await fetch(`${API}/api/admin/library/trash${qs}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _renderTrash(d);
    } catch (e) {
      console.error('Library trash:', e);
      banner.classList.add('lb-hidden');
    }
  }

  function _renderTrash(d) {
    const banner = document.getElementById('lb-trash-banner');
    if (!banner) return;
    if (!d.folders || !d.folders.length) {
      banner.classList.add('lb-hidden');
      banner.innerHTML = '';
      return;
    }
    banner.classList.remove('lb-hidden');
    const items = d.folders.slice(0, 8).map(f => `
      <div class="lb-trash-item">
        <span class="lb-trash-path">${escHtml(f.path)}</span>
        <span class="lb-trash-cat">${escHtml(f.category)}</span>
        <span class="lb-trash-count">${f.file_count.toLocaleString('fr-FR')} fichier${f.file_count > 1 ? 's' : ''}</span>
        <span class="lb-trash-sz">${fmtBytes(f.size_bytes)}</span>
      </div>`).join('');
    const more = d.folders.length > 8
      ? `<div class="lb-trash-more">+ ${d.folders.length - 8} autre${d.folders.length - 8 > 1 ? 's' : ''} dossier${d.folders.length - 8 > 1 ? 's' : ''}</div>`
      : '';
    banner.innerHTML = `
      <div class="lb-trash-head">
        <i class="bi bi-trash3"></i>
        <strong>${d.folders.length} dossier${d.folders.length > 1 ? 's' : ''} corbeille</strong>
        détecté${d.folders.length > 1 ? 's' : ''} —
        <span class="lb-trash-total">${fmtBytes(d.total_bytes)} récupérables</span>
      </div>
      <div class="lb-trash-list">${items}${more}</div>`;
  }

  async function _fetchOpts() {
    const qs = _state.cat_id ? `?cat_id=${_state.cat_id}` : '';
    try {
      const r = await fetch(`${API}/api/admin/library/filter-options${qs}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      _opts = await r.json();
      _renderCats();
    } catch (e) {
      console.error('Library filter-options:', e);
    }
  }

  function _renderCats() {
    const sel = document.getElementById('lb-cat-select');
    if (!sel || !_opts) return;
    sel.innerHTML =
      `<option value="">Toutes les catégories</option>` +
      (_opts.categories || []).map(c =>
        `<option value="${c.id}" ${_state.cat_id === c.id ? 'selected' : ''}>` +
        `${escHtml(c.name)} (${c.count.toLocaleString('fr-FR')})</option>`
      ).join('');
  }

  function _renderFilters() {
    const el = document.getElementById('lb-filters');
    if (!el || !_opts) return;

    const dims = [
      {
        key: 'resolutions', label: 'Résolution',
        items: (_opts.resolutions || []).map(r => ({ v: r.label,  l: r.label,              n: r.count })),
      },
      {
        key: 'codecs', label: 'Codec vidéo',
        items: (_opts.codecs || []).map(c => ({ v: c.name,   l: c.label,              n: c.count })),
      },
      {
        key: 'hdr', label: 'HDR',
        items: (_opts.hdr || []).map(h => ({ v: h.name,   l: h.label,              n: h.count })),
      },
      {
        key: 'langs_audio', label: 'Langue audio',
        items: (_opts.langs_audio || []).map(l => ({ v: l.code, l: l.label || l.code.toUpperCase(), n: l.count })),
      },
      {
        key: 'langs_sub', label: 'Langue ST',
        items: (_opts.langs_sub || []).map(l => ({ v: l.code, l: l.label || l.code.toUpperCase(), n: l.count })),
      },
      {
        key: 'disk_statuses', label: 'Statut',
        items: (_opts.disk_statuses || []).map(s => ({ v: s.name, l: s.label, n: s.count })),
      },
    ].filter(d => d.items.length);

    if (!dims.length) {
      el.innerHTML = '<div class="lb-filter-row"><span class="lb-filter-label" style="color:var(--muted)">Aucun filtre disponible</span></div>';
      return;
    }

    el.innerHTML = dims.map(dim => `
      <div class="lb-filter-row">
        <span class="lb-filter-label">${dim.label}</span>
        <div class="lb-chips">
          ${dim.items.map(item => {
            const active = _state[dim.key].has(item.v);
            const extraCls = dim.key === 'disk_statuses' ? ` lb-chip-status-${escHtml(item.v)}` : '';
            return `<button class="lb-chip${active ? ' active' : ''}${extraCls}"
              onclick="Library.toggle('${dim.key}','${escHtml(item.v)}')"
              title="${item.n.toLocaleString('fr-FR')} fichiers">
              ${escHtml(item.l)}<span class="lb-chip-n">${_fmtN(item.n)}</span>
            </button>`;
          }).join('')}
        </div>
      </div>`
    ).join('');
  }

  async function _fetchFiles() {
    if (_loading) return;
    _loading = true;
    const body = document.getElementById('lb-body');
    if (body) body.innerHTML =
      `<tr><td colspan="7" class="lb-loader"><span class="spinner"></span></td></tr>`;

    const p = new URLSearchParams({ page: _state.page, limit: LIMIT });
    if (_state.cat_id)           p.set('cat_id',      _state.cat_id);
    if (_state.resolutions.size) p.set('resolutions',  [..._state.resolutions].join(','));
    if (_state.codecs.size)      p.set('codecs',       [..._state.codecs].join(','));
    if (_state.hdr.size)         p.set('hdr',          [..._state.hdr].join(','));
    if (_state.langs_audio.size) p.set('langs_audio',  [..._state.langs_audio].join(','));
    if (_state.langs_sub.size)   p.set('langs_sub',    [..._state.langs_sub].join(','));
    if (_state.disk_statuses.size) p.set('disk_statuses', [..._state.disk_statuses].join(','));

    try {
      const r = await fetch(`${API}/api/admin/library/files?${p}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _loading = false;
      _renderList(d);
    } catch (e) {
      _loading = false;
      if (body) body.innerHTML =
        `<tr><td colspan="7" class="lb-error">Erreur : ${escHtml(e.message)}</td></tr>`;
    }
  }

  function _renderList(d) {
    const body = document.getElementById('lb-body');
    const info = document.getElementById('lb-count');
    const pag  = document.getElementById('lb-pag');

    if (info) {
      info.textContent = d.total.toLocaleString('fr-FR') +
        ' fichier' + (d.total > 1 ? 's' : '');
    }

    if (!body) return;

    if (!d.items.length) {
      body.innerHTML =
        `<tr><td colspan="7" class="lb-empty">Aucun fichier ne correspond aux filtres.</td></tr>`;
      if (pag) pag.innerHTML = '';
      return;
    }

    const resMap = { '4K': 'r4k', '1080p': 'r1080', '720p': 'r720', 'SD': 'rsd' };

    body.innerHTML = d.items.map(f => {
      const parts   = (f.path || '').replace(/\\/g, '/').split('/');
      const ctx     = parts.length > 1 ? parts.slice(0, -1).join('/') : '';
      const rCls    = resMap[f.resolution] || 'rsd';
      const res     = f.resolution
        ? `<span class="lb-badge lb-res-${rCls}">${f.resolution}</span>` : '—';
      const codec   = f.codec
        ? `<span class="lb-badge lb-codec">${f.codec.toUpperCase()}</span>` : '—';
      const hdr     = f.hdr
        ? `<span class="lb-badge lb-hdr">${escHtml(f.hdr)}</span>` : '';
      const audio   = (f.audio_langs || [])
        .map(l => `<span class="lb-tag">${escHtml(l)}</span>`).join('');
      const subs    = (f.sub_langs || [])
        .map(l => `<span class="lb-tag lb-tag-sub">${escHtml(l)}</span>`).join('');
      const statusLabels = { missing: 'Manquant', duplicate: 'Doublon' };
      const missing = f.disk_status !== 'present'
        ? ` <span class="lb-badge lb-warn lb-warn-${f.disk_status}">${statusLabels[f.disk_status] || f.disk_status}</span>` : '';
      const dupInfo = f.disk_status === 'duplicate' && f.duplicate_of
        ? `<div class="lb-fdup"><i class="bi bi-arrow-left-right"></i> ${escHtml(f.duplicate_of)}</div>` : '';

      return `<tr>
        <td class="lb-file-td">
          <div class="lb-fname">${escHtml(f.filename)}${missing}</div>
          ${ctx ? `<div class="lb-fpath">${escHtml(ctx)}</div>` : ''}
          ${dupInfo}
        </td>
        <td>${res}</td>
        <td>${codec}</td>
        <td>${hdr}</td>
        <td>${audio}</td>
        <td>${subs}</td>
        <td class="lb-size">${fmtBytes(f.size_bytes)}</td>
      </tr>`;
    }).join('');

    if (pag) _renderPag(pag, d.total, d.page, LIMIT);
  }

  function _renderPag(el, total, cur, limit) {
    const n = Math.ceil(total / limit);
    if (n <= 1) { el.innerHTML = ''; return; }

    const pages = new Set();
    [1, 2, cur - 2, cur - 1, cur, cur + 1, cur + 2, n - 1, n]
      .filter(p => p >= 1 && p <= n)
      .forEach(p => pages.add(p));
    const sorted = [...pages].sort((a, b) => a - b);

    let html = `<div class="lb-pag">`;
    html += `<button class="lb-pag-btn" ${cur <= 1 ? 'disabled' : ''}
      onclick="Library.setPage(${cur - 1})"><i class="bi bi-chevron-left"></i></button>`;

    let prev = null;
    for (const pg of sorted) {
      if (prev !== null && pg - prev > 1)
        html += `<span class="lb-pag-dots">…</span>`;
      html += `<button class="lb-pag-btn${pg === cur ? ' active' : ''}"
        onclick="Library.setPage(${pg})">${pg}</button>`;
      prev = pg;
    }

    html += `<button class="lb-pag-btn" ${cur >= n ? 'disabled' : ''}
      onclick="Library.setPage(${cur + 1})"><i class="bi bi-chevron-right"></i></button>`;
    html += `</div>`;
    el.innerHTML = html;
  }

  /* ── Helpers ─────────────────────────────────────────────────────────── */

  function _fmtN(n) {
    if (n >= 10000) return Math.round(n / 1000) + 'k';
    if (n >= 1000)  return (n / 1000).toFixed(1).replace('.', ',') + 'k';
    return String(n);
  }

  return { load, loadWithStatus, toggle, setPage, reset, setCat, reanalyze, cleanMissing };
})();
