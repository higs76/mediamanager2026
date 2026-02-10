-- ==========================================
-- MediaManager 2026 - Database Schema
-- ==========================================

-- ==========================================
-- TABLE: folders_config
-- Configuration des dossiers à surveiller
-- ==========================================
CREATE TABLE IF NOT EXISTS folders_config (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    share_name VARCHAR(255) NOT NULL,
    smb_host VARCHAR(255) NOT NULL,
    smb_path VARCHAR(255) NOT NULL,
    smb_username VARCHAR(100),
    smb_password VARCHAR(100),
    mount_point VARCHAR(255) NOT NULL,
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(smb_path, category)
);

-- ==========================================
-- TABLE: files
-- Fichiers détectés
-- ==========================================
CREATE TABLE IF NOT EXISTS files (
    id SERIAL PRIMARY KEY,
    folder_config_id INTEGER REFERENCES folders_config(id) ON DELETE CASCADE,
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

-- ==========================================
-- INDEXES pour performance
-- ==========================================
CREATE INDEX IF NOT EXISTS idx_files_folder ON files(folder_config_id);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_metadata_file ON video_metadata(file_id);
CREATE INDEX IF NOT EXISTS idx_proposals_file ON rename_proposals(file_id);
CREATE INDEX IF NOT EXISTS idx_folders_category ON folders_config(category);