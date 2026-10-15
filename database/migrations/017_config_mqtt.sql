-- Migration 017 : réglages MQTT (publication vers Home Assistant)
--   Connexion au broker MQTT, utilisée pour l'instant uniquement par le bouton
--   "Tester la connexion" de l'onglet Config (publication d'un message de test
--   sur <mqtt_topic_prefix>/test). La publication périodique de stats/capteurs
--   viendra dans une itération suivante.

INSERT INTO config (key, value, description)
VALUES ('mqtt_host', '', 'Adresse du broker MQTT (ex: 192.168.1.50 ou IP de Home Assistant)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_port', '1883', 'Port du broker MQTT')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_username', '', 'Nom d''utilisateur MQTT (laisser vide si le broker n''exige pas d''authentification)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_password', '', 'Mot de passe MQTT')
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES ('mqtt_topic_prefix', 'mediamanager', 'Préfixe des topics MQTT publiés par MediaManager')
ON CONFLICT (key) DO NOTHING;
