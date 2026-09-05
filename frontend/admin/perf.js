/* =============================================================================
   MediaManager 2026 — perf.js
   Journal des performances SQL (ring buffer en mémoire)
   ============================================================================= */

const Perf = (() => {

  async function load() {
    try {
      const r = await fetch(`${API}/api/admin/perf?limit=100`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      _renderStats(d.stats);
      _renderSummary(d.summary);
      _renderRecords(d.records);
    } catch(e) {
      console.error('Perf.load:', e);
    }
  }

  async function clear() {
    try {
      await fetch(`${API}/api/admin/perf`, { method: 'DELETE' });
      await load();
    } catch(e) {
      console.error('Perf.clear:', e);
    }
  }

  function _renderStats(stats) {
    setText('perf-buffered', stats.buffered);
    setText('perf-total',    stats.total_recorded);
    setText('perf-ring',     stats.ring_size);
  }

  function _renderSummary(summary) {
    const tbody = document.getElementById('perf-summary-body');
    if (!tbody) return;
    if (!summary.length) {
      tbody.innerHTML = '<tr><td colspan="7" class="perf-empty">Aucune requête enregistrée — naviguez dans l\'interface pour collecter des données.</td></tr>';
      return;
    }
    tbody.innerHTML = summary.map(r => {
      const cls = r.avg_ms > 500 ? 'perf-slow' : r.avg_ms > 100 ? 'perf-warn' : '';
      return `<tr class="${cls}">
        <td>${escHtml(r.endpoint)}</td>
        <td>${escHtml(r.name)}</td>
        <td>${r.calls}</td>
        <td>${r.avg_ms} ms</td>
        <td>${r.max_ms} ms</td>
        <td>${r.min_ms} ms</td>
        <td>${r.avg_rows}</td>
      </tr>`;
    }).join('');
  }

  function _renderRecords(records) {
    const tbody = document.getElementById('perf-records-body');
    if (!tbody) return;
    if (!records.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="perf-empty">—</td></tr>';
      return;
    }
    tbody.innerHTML = records.map(r => {
      const cls = r.duration_ms > 500 ? 'perf-slow' : r.duration_ms > 100 ? 'perf-warn' : '';
      return `<tr class="${cls}">
        <td class="perf-ts">${r.ts}</td>
        <td>${escHtml(r.endpoint)}</td>
        <td>${escHtml(r.name)}</td>
        <td>${r.duration_ms} ms</td>
        <td>${r.row_count}</td>
      </tr>`;
    }).join('');
  }

  return { load, clear };

})();
