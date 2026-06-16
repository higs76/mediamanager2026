-- ==========================================
-- Migration 002 : catalogue médias + historique
-- ==========================================

-- ============================================================
-- TABLE: media_titles
-- Le catalogue — un titre = une série ou un film.
-- Dissocié des fichiers physiques.
-- ============================================================
CREATE TABLE IF NOT EXISTS media_titles (
    id              SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES categories(id),
    mount_id        INTEGER NOT NULL REFERENCES mounts(id),
    folder_name     VARCHAR(500) NOT NULL,   -- nom du dossier actuel sur le disque
    display_name    VARCHAR(500),            -- nom "propre" validé par l'utilisateur
    year            INTEGER,                 -- pour les films
    folder_status   VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (folder_status IN ('pending','ok','to_rename','ignored')),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(mount_id, folder_name)            -- un dossier = un titre par montage
);

DROP TRIGGER IF EXISTS trg_media_titles_updated_at ON media_titles;
CREATE TRIGGER trg_media_titles_updated_at
    BEFORE UPDATE ON media_titles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_media_titles_category ON media_titles(category_id);
CREATE INDEX IF NOT EXISTS idx_media_titles_mount    ON media_titles(mount_id);
CREATE INDEX IF NOT EXISTS idx_media_titles_status   ON media_titles(folder_status);


-- ============================================================
-- TABLE: media_items
-- Un item = un fichier logique lié à un titre.
-- Pour les séries : saison + épisode.
-- Pour les films : juste le lien titre ↔ fichier.
-- Un fichier physique ne peut appartenir qu'à un seul item.
-- ============================================================
CREATE TABLE IF NOT EXISTS media_items (
    id              SERIAL PRIMARY KEY,
    title_id        INTEGER NOT NULL REFERENCES media_titles(id) ON DELETE CASCADE,
    file_id         INTEGER NOT NULL REFERENCES media_files(id)  ON DELETE CASCADE,
    season          INTEGER,                 -- NULL pour les films
    episode         INTEGER,                 -- NULL pour les films
    episode_title   VARCHAR(500),            -- titre de l'épisode si connu
    file_status     VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (file_status IN ('pending','ok','to_rename','ignored')),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(file_id)                          -- un fichier physique = un seul item
);

CREATE INDEX IF NOT EXISTS idx_media_items_title  ON media_items(title_id);
CREATE INDEX IF NOT EXISTS idx_media_items_file   ON media_items(file_id);
CREATE INDEX IF NOT EXISTS idx_media_items_season ON media_items(title_id, season, episode);


-- ============================================================
-- TABLE: media_files_history
-- Archive des fichiers physiques supprimés ou remplacés.
-- Permet de garder l'historique sans polluer media_files.
-- ============================================================
CREATE TABLE IF NOT EXISTS media_files_history (
    id              SERIAL PRIMARY KEY,
    original_id     INTEGER NOT NULL,        -- l'id qu'avait le fichier dans media_files
    mount_id        INTEGER REFERENCES mounts(id) ON DELETE SET NULL,
    hash_partial    VARCHAR(64),
    path_relative   VARCHAR(1000),
    filename        VARCHAR(500),
    extension       VARCHAR(20),
    size_bytes      BIGINT,
    reason          VARCHAR(50)              -- 'replaced' | 'deleted' | 'renamed'
                    CHECK (reason IN ('replaced','deleted','renamed')),
    archived_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- Snapshot des métadonnées au moment de l'archivage
    video_codec     VARCHAR(50),
    video_width     INTEGER,
    video_height    INTEGER,
    hdr_format      VARCHAR(50),
    duration_seconds FLOAT,
    audio_codecs    TEXT
);

CREATE INDEX IF NOT EXISTS idx_mfh_original ON media_files_history(original_id);
CREATE INDEX IF NOT EXISTS idx_mfh_hash     ON media_files_history(hash_partial);


-- ============================================================
-- TABLE: rename_proposals (remplace l'ancienne version)
-- Propositions de renommage — dossier OU fichier.
-- title_id : proposition sur le dossier titre
-- item_id  : proposition sur un fichier spécifique
-- ============================================================
DROP TABLE IF EXISTS rename_proposals;

CREATE TABLE IF NOT EXISTS rename_proposals (
    id              SERIAL PRIMARY KEY,
    title_id        INTEGER REFERENCES media_titles(id) ON DELETE CASCADE,
    item_id         INTEGER REFERENCES media_items(id)  ON DELETE CASCADE,
    current_name    VARCHAR(500) NOT NULL,
    proposed_name   VARCHAR(500) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','accepted','rejected','custom')),
    custom_name     VARCHAR(500),            -- nom saisi par l'utilisateur
    rule_used       VARCHAR(100),            -- règle ayant généré la proposition
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at     TIMESTAMP,
    CONSTRAINT chk_proposal_target
        CHECK (title_id IS NOT NULL OR item_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_proposals_title  ON rename_proposals(title_id);
CREATE INDEX IF NOT EXISTS idx_proposals_item   ON rename_proposals(item_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON rename_proposals(status);