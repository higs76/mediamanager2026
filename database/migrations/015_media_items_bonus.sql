-- Migration 015 : distingue le contenu bonus des épisodes/films dans media_items
-- Permet de référencer le bonus (poids, présence, navigable) sans le mélanger
-- visuellement avec le contenu principal côté app utilisateur.

ALTER TABLE media_items
    ADD COLUMN IF NOT EXISTS is_bonus BOOLEAN NOT NULL DEFAULT false;
