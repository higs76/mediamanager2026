/* =============================================================================
   MediaManager 2026 — stats.js
   Statistiques de la bibliothèque
   ============================================================================= */

const Stats = (() => {

  const PALETTE = [
    '#3b82f6','#8b5cf6','#10b981','#f59e0b',
    '#ef4444','#06b6d4','#f97316','#ec4899',
    '#a3e635','#e879f9','#38bdf8','#fb923c',
  ];

  let _charts    = {};
  let _catId     = null;   // null = toutes catégories
  let _categories = [];

  /* ── Entrée publique ──────────────────────────────────────────────────── */
  async function load() {
    await _loadCategories();
    await _reload();
  }

  /* ── Catégories ───────────────────────────────────────────────────────── */
  async function _loadCategories() {
    try {
      const r = await fetch(`${API}/api/admin/categories`);
      const d = await r.json();
      _categories = d.detail  ?? [];
      _renderCatTabs();
    } catch(e) {
      console.warn('Stats._loadCategories:', e.message);
    }
  }

  function _renderCatTabs() {
    const bar = document.getElementById('stats-cat-tabs');
    if (!bar) return;
    bar.innerHTML = [
      `<button class="tab-btn${_catId === null ? ' active' : ''}"
         onclick="Stats.filterCat(null)">Toutes</button>`,
      ..._categories.map(c =>
        `<button class="tab-btn${_catId === c.id ? ' active' : ''}"
           onclick="Stats.filterCat(${c.id},'${_esc(c.name)}')">
           ${_cap(c.name)}
         </button>`
      )
    ].join('');
  }

  function filterCat(id, name) {
    _catId = id;
    _renderCatTabs();
    _reload();
  }

  /* ── Chargement données ───────────────────────────────────────────────── */
  async function _reload() {
    const url = _catId
      ? `${API}/api/admin/files/quality-stats?cat_id=${_catId}`
      : `${API}/api/admin/files/quality-stats`;

    try {
      const d = await fetch(url).then(r => r.json());
      _renderKPIs(d);
      _renderVideoSection(d);
      _renderAudioSection(d);
      _renderSubSection(d);
      _renderTitles(d);
    } catch(e) {
      console.error('Stats._reload:', e);
    }
  }

  /* ── KPIs ─────────────────────────────────────────────────────────────── */
  function _renderKPIs(d) {
    _set('kpi-total', (d.total ?? 0).toLocaleString('fr-FR'));

    const h      = d.total_hours ?? 0;
    const years  = Math.floor(h / 8760);
    const months = Math.floor((h % 8760) / 730);
    let hl = '';
    if (years  > 0) hl += `${years} an${years  > 1 ? 's' : ''} `;
    if (months > 0) hl += `${months} mois`;
    if (!hl)        hl  = `${Math.round(h).toLocaleString('fr-FR')} h`;
    _set('kpi-hours', hl.trim());

    const gb = d.avg_size_gb ?? 0;
    _set('kpi-size', gb >= 1 ? `${gb} Go` : `${Math.round(gb * 1024)} Mo`);

    const tb = d.total_tb ?? 0;
    _set('kpi-total-size', tb >= 1 ? `${tb} To` : `${Math.round(tb * 1024)} Go`);

    const sd       = (d.resolutions ?? []).find(r => r.label === 'SD')?.count ?? 0;
    const oldCodec = (d.codecs ?? [])
      .filter(c => ['mpeg4','h264','xvid','divx'].includes(c.label))
      .reduce((a, c) => a + c.count, 0);
    _set('kpi-upgrade', Math.max(sd, oldCodec).toLocaleString('fr-FR'));
    // Titres et fichiers
    const nbTitles = d.nb_titles ?? 0;
    _set('kpi-titles',
      `${nbTitles.toLocaleString('fr-FR')} titre${nbTitles > 1 ? 's' : ''}`);
  }

  /* ── Section Vidéo ────────────────────────────────────────────────────── */
  function _renderVideoSection(d) {
    _donut('chart-codecs',      'legend-codecs',      d.codecs      ?? []);
    _donut('chart-resolutions', 'legend-resolutions', d.resolutions ?? []);
    _donut('chart-hdr',         'legend-hdr',         d.hdr         ?? []);

    // Répartition catégories (global) ou titres (filtré)
    if (!_catId) {
      const cats = (d.by_category ?? []).map(c => ({
        label: _cap(c.name), count: c.count
      }));
      _donut('chart-categories', 'legend-categories', cats);
      _set('chart-cat-title', 'Répartition par catégorie');
    } else {
      // Top 10 titres pour cette catégorie
      const top10 = (d.titles ?? [])
        .sort((a,b) => b.count - a.count)
        .slice(0, 10)
        .map(t => ({ label: t.name, count: t.count }));
      _donut('chart-categories', 'legend-categories', top10);
      _set('chart-cat-title', 'Top 10 — plus de fichiers');
    }
  }

  /* ── Section Audio ────────────────────────────────────────────────────── */
  function _renderAudioSection(d) {
    _donut('chart-audio-codecs',  'legend-audio-codecs',  d.audio_codecs    ?? []);
    _donut('chart-audio-channels','legend-audio-channels',d.audio_channels  ?? []);
    _renderTags('tags-audio-langs', d.audio_langs ?? []);
  }

  /* ── Section Sous-titres ──────────────────────────────────────────────── */
  function _renderSubSection(d) {
    const total    = d.total ?? 0;
    const withSub  = total - (d.no_sub_count ?? 0);
    _donut('chart-sub-presence', 'legend-sub-presence', [
      { label: 'Avec sous-titres',  count: withSub },
      { label: 'Sans sous-titres',  count: d.no_sub_count ?? 0 },
    ]);
    _renderTags('tags-sub-langs', d.sub_langs ?? []);
  }

  /* ── Titres détectés ──────────────────────────────────────────────────── */
  function _renderTitles(d) {
    const box = document.getElementById('titles-list');
    if (!box) return;

    const titles = d.titles ?? [];
    if (!titles.length) {
      box.innerHTML = '<span style="color:var(--muted);font-size:.83rem">Aucun titre détecté</span>';
      return;
    }

    const total = titles.reduce((a, t) => a + t.count, 0);
    _set('titles-count',
      `${titles.length} titre${titles.length > 1 ? 's' : ''} — ${total.toLocaleString('fr-FR')} fichiers`);

    // Afficher jusqu'à 50 titres, le reste masqué
    const visible  = titles.slice(0, 50);
    const hidden   = titles.slice(50);

    box.innerHTML = visible.map(t => `
      <div class="title-row">
        <span class="title-name">${_esc(t.name)}</span>
        <span class="title-count">
          ${t.count} fichier${t.count > 1 ? 's' : ''}
          — ${_formatSize(t.size_gb)}
        </span>
      </div>`).join('')
      + (hidden.length ? `
        <div id="titles-more" style="display:none">
          ${hidden.map(t => `
            <div class="title-row">
              <span class="title-name">${_esc(t.name)}</span>
              <span class="title-count">${t.count} fichier${t.count > 1 ? 's' : ''}</span>
            </div>`).join('')}
        </div>
        <button class="btn btn-sm" style="margin-top:8px"
          onclick="document.getElementById('titles-more').style.display='';this.style.display='none'">
          Voir ${hidden.length} de plus…
        </button>` : '');
  }

  /* ── Tags langues ─────────────────────────────────────────────────────── */
  function _renderTags(containerId, items) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!items.length) {
      el.innerHTML = '<span style="color:var(--muted);font-size:.83rem">—</span>';
      return;
    }
    const total = items.reduce((a, i) => a + i.count, 0);
    el.innerHTML = items.map((item, idx) => {
      const pct = Math.round(item.count / total * 100);
      const col = PALETTE[idx % PALETTE.length];
      return `<span class="lang-tag" style="--tag-color:${col}">
        ${_esc(item.label)}
        <span class="lang-tag-count">${item.count.toLocaleString('fr-FR')} (${pct}%)</span>
      </span>`;
    }).join('');
  }

  /* ── Donut Chart ──────────────────────────────────────────────────────── */
  function _donut(canvasId, legendId, data) {
    if (!data?.length) return;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    if (_charts[canvasId]) { _charts[canvasId].destroy(); delete _charts[canvasId]; }

    const labels = data.map(d => d.label);
    const values = data.map(d => d.count);
    const total  = values.reduce((a, b) => a + b, 0);
    const colors = data.map((_, i) => PALETTE[i % PALETTE.length]);

    _charts[canvasId] = new Chart(canvas, {
      type: 'doughnut',
      data: {
        labels,
        datasets: [{
          data: values,
          backgroundColor: colors,
          borderColor: 'transparent',
          borderWidth: 0,
          hoverOffset: 6,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '65%',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: ctx => {
                const pct = Math.round(ctx.parsed / total * 100);
                return ` ${ctx.label} : ${ctx.parsed.toLocaleString('fr-FR')} (${pct}%)`;
              }
            }
          }
        }
      }
    });

    const legendEl = document.getElementById(legendId);
    if (legendEl) {
      legendEl.innerHTML = data.map((d, i) => {
        const pct = Math.round(d.count / total * 100);
        return `<div class="legend-item">
          <div class="legend-dot" style="background:${colors[i]}"></div>
          <span>${_esc(d.label)} <strong>${pct}%</strong></span>
        </div>`;
      }).join('');
    }
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
  function _cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _formatSize(gb) {
    const v = parseFloat(gb) || 0;
    if (v >= 1024) return (v / 1024).toFixed(1) + ' To';
    if (v >= 1)    return v + ' Go';
    const mb = Math.round(v * 1024);
    if (mb === 0)  return '< 1 Mo';
    return mb + ' Mo';
  }

  return { load, filterCat };

})();