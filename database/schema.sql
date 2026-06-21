-- ==========================================
-- MediaManager 2026 - Database Schema
-- Version : structure pure, idempotente
-- Les données initiales sont dans database/migrations/
-- ==========================================


-- ============================================================
-- FONCTION utilitaire : updated_at automatique
-- Doit être créée AVANT les triggers qui l'utilisent
-- ============================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- TABLE: config
-- Paramètres applicatifs clé/valeur
-- ============================================================
CREATE TABLE IF NOT EXISTS config (
    key         VARCHAR(100) PRIMARY KEY,
    value       TEXT NOT NULL,
    description TEXT,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS trg_config_updated_at ON config;
CREATE TRIGGER trg_config_updated_at
    BEFORE UPDATE ON config
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ============================================================
-- TABLE: naming_templates
-- Templates de nommage des fichiers médias.
-- Liés à un type (seasonal / noseasonal), pas à une catégorie.
-- Les templates système (is_default=true) sont en lecture seule.
-- ============================================================
CREATE TABLE IF NOT EXISTS naming_templates (
    id              SERIAL PRIMARY KEY,
    type            VARCHAR(20) NOT NULL
                    CHECK (type IN ('seasonal', 'noseasonal')),
    is_default      BOOLEAN NOT NULL DEFAULT false,

    -- Fichier saisonnable : {serie}{sep1}{prefS}{nn_s}{sep_se}{prefE}{nn_e}{sep2}{titre}.mkv
    sep1            VARCHAR(20),    -- séparateur série → numéro  ex: ' - '
    sep2            VARCHAR(20),    -- séparateur numéro → titre  ex: ' - '
    prefix_season   VARCHAR(10),    -- préfixe saison : '' ou 'S'
    digits_season   SMALLINT,       -- nb chiffres saison : 2 ou 3
    sep_se          VARCHAR(10),    -- séparateur S×E : 'x', 'E'…
    prefix_episode  VARCHAR(10),    -- préfixe épisode : '' ou 'E'
    digits_episode  SMALLINT,       -- nb chiffres épisode : 2 ou 3

    -- Dossier saison (indépendant du format fichier)
    folder_prefix   VARCHAR(20),    -- préfixe dossier : 'S', 'Saison ', ''
    folder_digits   SMALLINT,       -- nb chiffres dossier saison : 2 ou 3
    special_folder  VARCHAR(50),    -- nom dossier saison spéciale : 'S0', 'Spéciaux'…

    -- Film non saisonnable : {titre}{sep_year}{année}.mkv
    sep_year        VARCHAR(10),    -- séparateur titre → année : ' '
    year_format     VARCHAR(10)     -- format année : 'paren' | 'plain' | 'none'
                    CHECK (year_format IS NULL OR year_format IN ('paren', 'plain', 'none')),
    bonus_folder    VARCHAR(50),    -- nom dossier bonus films : 'Bonus'

    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- Unicité sur la combinaison des paramètres (évite les doublons)
    UNIQUE NULLS NOT DISTINCT (
        type, sep1, sep2, prefix_season, digits_season,
        sep_se, prefix_episode, digits_episode,
        folder_prefix, folder_digits, special_folder,
        sep_year, year_format, bonus_folder
    )
);


-- ============================================================
-- TABLE: categories
-- Types de médias définis par l'utilisateur.
-- Le "name" sert de nom de dossier dans MediaManagerMnt/
-- ============================================================
CREATE TABLE IF NOT EXISTS categories (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,    -- ex: series, films, animes
    has_seasons BOOLEAN NOT NULL DEFAULT true,   -- true = saisonnable
    template_id INTEGER REFERENCES naming_templates(id),
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


-- ============================================================
-- TABLE: known_servers
-- Serveurs réseau connus avec leurs credentials.
-- Permet de pré-remplir les infos lors de l'ajout de montages.
-- ============================================================
CREATE TABLE IF NOT EXISTS known_servers (
    id          SERIAL PRIMARY KEY,
    server      VARCHAR(255) NOT NULL UNIQUE,
    mount_type  VARCHAR(10)  NOT NULL CHECK (mount_type IN ('smb', 'nfs')),
    username    VARCHAR(100),
    password    VARCHAR(255),
    domain      VARCHAR(100) DEFAULT 'WORKGROUP',
    smb_version VARCHAR(10)  DEFAULT '3.0',
    nfs_version INTEGER      DEFAULT 4,
    note        TEXT,
    updated_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS trg_known_servers_updated_at ON known_servers;
CREATE TRIGGER trg_known_servers_updated_at
    BEFORE UPDATE ON known_servers
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_known_servers_type ON known_servers(mount_type);


-- ============================================================
-- TABLE: mounts
-- En-tête de chaque montage (indépendant du type).
-- Chemin local calculé : {MOUNT_BASE}/{category.name}/{id}-{category.name}
-- ============================================================
CREATE TABLE IF NOT EXISTS mounts (
    id             SERIAL PRIMARY KEY,
    mount_type     VARCHAR(10)  NOT NULL CHECK (mount_type IN ('smb', 'nfs')),
    category_id    INTEGER      NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    local_path     VARCHAR(500) NOT NULL UNIQUE,
    active         BOOLEAN      NOT NULL DEFAULT true,
    last_mount_at  TIMESTAMP,
    last_error     TEXT,
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS trg_mounts_updated_at ON mounts;
CREATE TRIGGER trg_mounts_updated_at
    BEFORE UPDATE ON mounts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_mounts_category ON mounts(category_id);
CREATE INDEX IF NOT EXISTS idx_mounts_active   ON mounts(active);


-- ============================================================
-- TABLE: mount_smb
-- Paramètres spécifiques aux montages SMB/CIFS (1-to-1 avec mounts).
-- ============================================================
CREATE TABLE IF NOT EXISTS mount_smb (
    id            SERIAL PRIMARY KEY,
    mount_id      INTEGER NOT NULL UNIQUE REFERENCES mounts(id) ON DELETE CASCADE,
    server        VARCHAR(255) NOT NULL,
    share         VARCHAR(255) NOT NULL,
    username      VARCHAR(100),
    password      VARCHAR(255),
    domain        VARCHAR(100) DEFAULT 'WORKGROUP',
    smb_version   VARCHAR(10)  DEFAULT '3.0',
    mount_options VARCHAR(500) DEFAULT 'uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8'
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_smb_source') THEN
        ALTER TABLE mount_smb ADD CONSTRAINT uq_smb_source UNIQUE (server, share);
    END IF;
END $$;


-- ============================================================
-- TABLE: mount_nfs
-- Paramètres spécifiques aux montages NFS (1-to-1 avec mounts).
-- ============================================================
CREATE TABLE IF NOT EXISTS mount_nfs (
    id            SERIAL PRIMARY KEY,
    mount_id      INTEGER NOT NULL UNIQUE REFERENCES mounts(id) ON DELETE CASCADE,
    server        VARCHAR(255) NOT NULL,
    export_path   VARCHAR(255) NOT NULL,
    nfs_version   INTEGER      DEFAULT 4,
    mount_options VARCHAR(500) DEFAULT 'rw,soft,timeo=30'
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_nfs_source') THEN
        ALTER TABLE mount_nfs ADD CONSTRAINT uq_nfs_source UNIQUE (server, export_path);
    END IF;
END $$;


-- ============================================================
-- TABLE: media_files
-- Fichiers vidéo détectés sur les montages.
-- hash_partial : SHA-256 sur début+fin+taille → anti-doublon stable
-- status      : étape d'analyse (pipeline)
-- disk_status : présence physique sur le disque
-- ============================================================
CREATE TABLE IF NOT EXISTS media_files (
    id              SERIAL PRIMARY KEY,
    mount_id        INTEGER NOT NULL REFERENCES mounts(id) ON DELETE CASCADE,
    hash_partial    VARCHAR(64) NOT NULL,
    path_relative   VARCHAR(1000) NOT NULL,
    filename        VARCHAR(500) NOT NULL,
    extension       VARCHAR(20),
    size_bytes      BIGINT NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'discovered'
                    CHECK (status IN ('discovered', 'analyzing', 'analyzed')),
    disk_status     VARCHAR(20) NOT NULL DEFAULT 'present'
                    CHECK (disk_status IN ('present', 'missing', 'duplicate')),
    first_seen_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    file_mtime      TIMESTAMP,
    UNIQUE(hash_partial, mount_id)
);

CREATE INDEX IF NOT EXISTS idx_media_files_mount       ON media_files(mount_id);
CREATE INDEX IF NOT EXISTS idx_media_files_status      ON media_files(status);
CREATE INDEX IF NOT EXISTS idx_media_files_hash        ON media_files(hash_partial);
CREATE INDEX IF NOT EXISTS idx_media_files_disk_status ON media_files(disk_status);


-- ============================================================
-- TABLE: scan_jobs
-- Historique des scans de découverte (un scan = un montage).
-- ============================================================
CREATE TABLE IF NOT EXISTS scan_jobs (
    id              SERIAL PRIMARY KEY,
    mount_id        INTEGER NOT NULL REFERENCES mounts(id) ON DELETE CASCADE,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'done', 'error')),
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    files_found     INTEGER DEFAULT 0,
    files_new       INTEGER DEFAULT 0,
    files_updated   INTEGER DEFAULT 0,
    files_missing   INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scan_jobs_mount  ON scan_jobs(mount_id);
CREATE INDEX IF NOT EXISTS idx_scan_jobs_status ON scan_jobs(status);


-- ============================================================
-- TABLE: analyze_sessions
-- Sessions d'analyse ffprobe par dossier (dernier niveau).
-- Sert de log de progression.
-- ============================================================
CREATE TABLE IF NOT EXISTS analyze_sessions (
    id              SERIAL PRIMARY KEY,
    mount_id        INTEGER NOT NULL REFERENCES mounts(id) ON DELETE CASCADE,
    folder_path     VARCHAR(1000) NOT NULL,
    files_total     INTEGER NOT NULL DEFAULT 0,
    files_done      INTEGER NOT NULL DEFAULT 0,
    files_error     INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'done', 'error')),
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_analyze_sessions_mount  ON analyze_sessions(mount_id);
CREATE INDEX IF NOT EXISTS idx_analyze_sessions_status ON analyze_sessions(status);


-- ============================================================
-- TABLE: video_metadata
-- Métadonnées vidéo extraites par ffprobe.
-- ============================================================
CREATE TABLE IF NOT EXISTS video_metadata (
    id                    SERIAL PRIMARY KEY,
    file_id               INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
    duration_seconds      FLOAT,
    video_codec           VARCHAR(50),
    video_bitrate         BIGINT,
    video_width           INTEGER,
    video_height          INTEGER,
    video_fps             FLOAT,
    audio_codecs          TEXT,
    audio_bitrates        TEXT,
    audio_profiles        TEXT,
    audio_languages       TEXT,
    audio_channels        TEXT,
    audio_channel_layouts TEXT,
    subtitle_languages    TEXT,
    subtitle_count        INTEGER,
    container_format      VARCHAR(50),
    hdr_format            VARCHAR(50),
    color_space           VARCHAR(50),
    file_path_snapshot    VARCHAR(1000),
    analyzed_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metadata_file ON video_metadata(file_id);


-- ============================================================
-- TABLE: rename_proposals
-- Gérée par la migration 002 (structure enrichie).
-- Ce bloc est intentionnellement vide pour éviter les conflits.
-- ============================================================
-- (voir database/migrations/002_catalogue_medias.sql)

--CREATE INDEX IF NOT EXISTS idx_proposals_file ON rename_proposals(file_id);


-- ============================================================
-- TABLE: schema_migrations
-- Trace les migrations déjà appliquées.
-- ============================================================
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     VARCHAR(60) PRIMARY KEY,
    applied_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);