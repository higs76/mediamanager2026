-- ==========================================
-- MediaManager 2026 - Database Schema
-- ==========================================

-- ============================================================
-- TABLE: categories
-- Types de médias définis par l'utilisateur.
-- Le "name" sert de nom de dossier dans MediaManagerMnt/
-- et peut être traduit dans l'interface plus tard.
-- ============================================================

CREATE TABLE IF NOT EXISTS categories (
    id         SERIAL PRIMARY KEY,
   name       VARCHAR(100) NOT NULL UNIQUE,  -- ex: series, films, animes
   created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Catégories par défaut
--INSERT INTO categories (name) VALUES
--('series'), ('films'), ('animes'), ('documentaires')
--ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- TABLE: mounts
-- En-tête de chaque montage (indépendant du type).
-- C'est cet ID qui sert à construire le nom du montage :
--   "{id} - {category.name}"  →  "1 - series", "2 - films"
-- Et le chemin local :
--   "{MOUNT_BASE}/{category.name}/{id}-{category.name}"
--   ex: /home/mediamanager/MediaManagerMnt/series/1-series
-- ============================================================
CREATE TABLE IF NOT EXISTS mounts (
    id             SERIAL PRIMARY KEY,
    mount_type     VARCHAR(10)  NOT NULL CHECK (mount_type IN ('smb', 'nfs')),
    category_id    INTEGER      NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    local_path     VARCHAR(500) NOT NULL UNIQUE,  -- calculé et géré par l'app
    active         BOOLEAN      NOT NULL DEFAULT true,
    last_mount_at  TIMESTAMP,   -- mis à jour à chaque montage réussi
    last_error     TEXT,        -- dernière erreur, NULL si tout va bien
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- TABLE: mount_smb
-- Paramètres spécifiques aux montages SMB/CIFS.
-- Un enregistrement par montage SMB (1-to-1 avec mounts).
-- ============================================================
CREATE TABLE IF NOT EXISTS mount_smb (
    id            SERIAL PRIMARY KEY,
    mount_id      INTEGER NOT NULL UNIQUE REFERENCES mounts(id) ON DELETE CASCADE,
    server        VARCHAR(255) NOT NULL,   -- ex: //192.168.1.10 ou //nas1
    share         VARCHAR(255) NOT NULL,   -- ex: /series
    username      VARCHAR(100),            -- NULL = accès invité
    password      VARCHAR(255),            -- NULL = accès invité
    domain        VARCHAR(100) DEFAULT 'WORKGROUP',
    smb_version   VARCHAR(10)  DEFAULT '3.0',  -- 1.0 / 2.0 / 2.1 / 3.0
    mount_options VARCHAR(500) DEFAULT 'uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8'
);

-- ============================================================
-- TABLE: mount_nfs
-- Paramètres spécifiques aux montages NFS.
-- Un enregistrement par montage NFS (1-to-1 avec mounts).
-- ============================================================
CREATE TABLE IF NOT EXISTS mount_nfs (
    id            SERIAL PRIMARY KEY,
    mount_id      INTEGER NOT NULL UNIQUE REFERENCES mounts(id) ON DELETE CASCADE,
    server        VARCHAR(255) NOT NULL,   -- ex: 192.168.1.10 ou nas1
    export_path   VARCHAR(255) NOT NULL,   -- ex: /volume1/series
    nfs_version   INTEGER      DEFAULT 4,  -- 3 ou 4
    mount_options VARCHAR(500) DEFAULT 'rw,soft,timeo=30'
);

-- ==========================================
-- TABLE: files
-- Fichiers détectés
-- ==========================================
CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    mount_id INTEGER REFERENCES mounts(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_size BIGINT,
    file_hash VARCHAR(64),
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'pending',
    UNIQUE(file_path)
);

-- ==========================================
-- TABLE: video_metadata
-- Métadonnées vidéo extraites
-- ==========================================
CREATE TABLE IF NOT EXISTS video_metadata (
    id SERIAL PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    duration_seconds FLOAT,
    video_codec VARCHAR(50),
    video_bitrate BIGINT,
    video_width INTEGER,
    video_height INTEGER,
    video_fps FLOAT,
    audio_codecs TEXT,
    audio_languages TEXT,
    subtitle_languages TEXT,
    container_format VARCHAR(50),
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- TABLE: rename_proposals
-- Propositions de renommage
-- ==========================================
CREATE TABLE IF NOT EXISTS rename_proposals (
    id SERIAL PRIMARY KEY,
    file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
    proposed_name VARCHAR(500) NOT NULL,
    category VARCHAR(50),
    confidence FLOAT,
    rule_used VARCHAR(255),
    status VARCHAR(50) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    accepted_at TIMESTAMP
);

-- ============================================================
-- TRIGGER : updated_at automatique sur mounts
-- ============================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_mounts_updated_at ON mounts;
CREATE TRIGGER trg_mounts_updated_at
    BEFORE UPDATE ON mounts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ==========================================
-- INDEXES pour performance
-- ==========================================
CREATE INDEX IF NOT EXISTS idx_mounts_category  ON mounts(category_id);
CREATE INDEX IF NOT EXISTS idx_mounts_active    ON mounts(active);
CREATE INDEX IF NOT EXISTS idx_files_mount      ON files(mount_id);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_metadata_file ON video_metadata(file_id);
CREATE INDEX IF NOT EXISTS idx_proposals_file ON rename_proposals(file_id);
CREATE INDEX IF NOT EXISTS idx_folders_category ON folders_config(category);