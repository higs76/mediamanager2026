-- Migration 016 : autorise plusieurs media_items pour un même fichier physique
-- Nécessaire pour les fichiers multi-épisodes (sorties Blu-ray/DVD groupées,
-- ex: 'Serie - 01x01_04.mkv' = épisodes 1 à 4 dans un seul fichier).
-- Chaque épisode devient sa propre ligne, toutes pointant vers le même file_id.

ALTER TABLE media_items DROP CONSTRAINT IF EXISTS media_items_file_id_key;
ALTER TABLE media_items ADD CONSTRAINT media_items_file_id_season_episode_key
    UNIQUE (file_id, season, episode);
