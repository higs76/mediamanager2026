-- Migration 019 : interrupteurs par bloc pour le publisher MQTT
--   Contrairement aux réglages de connexion (migration 017/018), ceux-ci sont relus
--   à chaque cycle de publication (pas de redémarrage requis pour activer/désactiver
--   un bloc) : premisse d'un futur contrôle plus fin ("quels capteurs publier") piloté
--   depuis l'admin MediaManager.

INSERT INTO config (key, value, description)
VALUES ('mqtt_publish_library', 'true', 'Publie les statistiques bibliothèque (titres, fichiers, taille, corbeille) vers MQTT')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_publish_jobs', 'true', 'Publie l''état des jobs (scan, analyse, renommages en attente) vers MQTT')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_publish_mounts', 'true', 'Publie l''état des montages NAS (montés/manquants) vers MQTT')
ON CONFLICT (key) DO NOTHING;
