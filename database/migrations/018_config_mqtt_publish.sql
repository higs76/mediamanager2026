-- Migration 018 : réglages du publisher MQTT persistant (Home Assistant)
--   - mqtt_enabled : interrupteur général du publisher persistant (capteurs via
--     MQTT Discovery). Indépendant du bouton "Tester la connexion" (migration 017),
--     qui continue de fonctionner même si mqtt_enabled=false.
--   - mqtt_publish_interval_seconds : fréquence de republication de l'état
--     (version/uptime) ; la disponibilité online/offline est gérée en temps réel
--     par la connexion persistante (Last Will and Testament), pas par ce timer.
-- Ces réglages (ainsi que mqtt_host/port/username/password de la migration 017)
-- ne sont lus qu'au démarrage du service (connexion persistante) : un changement
-- nécessite un redémarrage pour être pris en compte.

INSERT INTO config (key, value, description)
VALUES ('mqtt_enabled', 'false', 'Active le publisher MQTT persistant (capteurs Home Assistant via MQTT Discovery). Redémarrage du service requis pour appliquer un changement.')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_publish_interval_seconds', '60', 'Intervalle (en secondes) de republication de l''état MQTT (version, uptime). Redémarrage du service requis pour appliquer un changement.')
ON CONFLICT (key) DO NOTHING;
