/* =============================================================================
   MediaManager 2026 — shared.js
   Utilitaires communs à tous les modules admin (chargé avant les autres scripts)
   ============================================================================= */

function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function setText(id, v) {
  const el = document.getElementById(id);
  if (el) el.textContent = v;
}

function fmtBytes(bytes) {
  if (!bytes) return '—';
  if (bytes >= 1099511627776) return (bytes / 1099511627776).toFixed(1).replace('.', ',') + ' To';
  if (bytes >= 1073741824)    return (bytes / 1073741824).toFixed(1).replace('.', ',') + ' Go';
  if (bytes >= 1048576)       return (bytes / 1048576).toFixed(0) + ' Mo';
  return bytes + ' o';
}
