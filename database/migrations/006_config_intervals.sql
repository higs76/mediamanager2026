-- ==========================================
-- Migration 006 : intervalles de rafraîchissement configurables
-- ==========================================

INSERT INTO config (key, value, description) VALUES
    ('mount_watchdog_interval',       '300', 'Intervalle en secondes du watchdog de remontage NAS (minimum 60)'),
    ('mount_status_refresh_interval',  '30', 'Intervalle en secondes de rafraîchissement du statut des montages dans l''interface'),
    ('services_refresh_interval',      '15', 'Intervalle en secondes de rafraîchissement du panneau services/logs')
ON CONFLICT (key) DO NOTHING;
