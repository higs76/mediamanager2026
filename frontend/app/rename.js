const Rename = (() => {

  async function init() {
    document.getElementById('rename-content').innerHTML = `
      <div class="empty-state">
        <i class="bi bi-pencil-square"></i>
        Renommage en cours de chargement…
      </div>`;
  }

  async function loadBadge() {
    try {
      const r = await fetch(`${API}/api/admin/jobs/status`);
      const d = await r.json();
      const count = d.cataloger?.proposals_pending ?? 0;
      const badge = document.getElementById('rename-badge');
      if (badge) {
        badge.textContent = count.toLocaleString('fr-FR');
        badge.style.display = count > 0 ? '' : 'none';
      }
    } catch(e) {
      console.warn('loadBadge:', e.message);
    }
  }

  return { init, loadBadge };
})();