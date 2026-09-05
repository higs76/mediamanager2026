-- Migration 014 : nouveaux réglages Config
--   - log_retention_days : nombre de jours d'historique des logs conservés
--     (lu au démarrage du process — un changement nécessite un redémarrage)
--   - catalog_bonus_dirs : dossiers "bonus" de série à ignorer lors du catalogage
--     (auparavant un set Python figé {'bonus','extras','featurettes'})

INSERT INTO config (key, value, description)
VALUES (
    'log_retention_days',
    '14',
    'Nombre de jours de logs conservés avant suppression automatique (rotation quotidienne). Redémarrage du service requis pour appliquer un changement.'
)
ON CONFLICT (key) DO NOTHING;

INSERT INTO config (key, value, description)
VALUES (
    'catalog_bonus_dirs',
    'bonus,extras,featurettes',
    'Noms de dossiers de bonus à ignorer lors du catalogage des séries, séparés par des virgules. Ex: bonus,extras,suppléments'
)
ON CONFLICT (key) DO NOTHING;
