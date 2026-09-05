-- Migration 013 : ajoute le tag "title" des pistes sous-titres
-- Certains mux (mkvmerge) encodent une distinction (ex: "Forced" vs "Full")
-- uniquement dans ce tag texte, pas de façon fiable via disposition.forced.

ALTER TABLE subtitle_tracks
    ADD COLUMN IF NOT EXISTS title VARCHAR(100);
