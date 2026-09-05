-- Migration 009 : normalisation pistes audio, sous-titres et formats HDR
-- Remplace les colonnes TEXT semicolone-délimitées par des tables normalisées.
-- Idempotente : tous les CREATE/ALTER utilisent IF NOT EXISTS / ON CONFLICT DO NOTHING.

-- ─── Tables de référence ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS codecs (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    codec_type   VARCHAR(10) NOT NULL CHECK (codec_type IN ('video', 'audio'))
);

CREATE TABLE IF NOT EXISTS languages (
    id    SERIAL PRIMARY KEY,
    code  CHAR(3) UNIQUE NOT NULL,
    label VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS hdr_formats (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(30) UNIQUE NOT NULL,
    display_name VARCHAR(50)
);

-- ─── Tables de pistes ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audio_tracks (
    id          SERIAL PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
    track_order SMALLINT NOT NULL,
    codec_id    INTEGER REFERENCES codecs(id),
    language_id INTEGER REFERENCES languages(id),
    profile     VARCHAR(100),
    channels    SMALLINT,
    layout      VARCHAR(30),
    bitrate     INTEGER,
    is_default  BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (file_id, track_order)
);

CREATE TABLE IF NOT EXISTS subtitle_tracks (
    id          SERIAL PRIMARY KEY,
    file_id     INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
    track_order SMALLINT NOT NULL,
    language_id INTEGER REFERENCES languages(id),
    is_default  BOOLEAN NOT NULL DEFAULT false,
    is_forced   BOOLEAN NOT NULL DEFAULT false,
    UNIQUE (file_id, track_order)
);

CREATE TABLE IF NOT EXISTS file_hdr_formats (
    file_id       INTEGER NOT NULL REFERENCES media_files(id) ON DELETE CASCADE,
    hdr_format_id INTEGER NOT NULL REFERENCES hdr_formats(id),
    PRIMARY KEY (file_id, hdr_format_id)
);

-- ─── Index ────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_audio_tracks_file    ON audio_tracks(file_id);
CREATE INDEX IF NOT EXISTS idx_audio_tracks_codec   ON audio_tracks(codec_id);
CREATE INDEX IF NOT EXISTS idx_audio_tracks_lang    ON audio_tracks(language_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_tracks_file ON subtitle_tracks(file_id);
CREATE INDEX IF NOT EXISTS idx_subtitle_tracks_lang ON subtitle_tracks(language_id);
CREATE INDEX IF NOT EXISTS idx_file_hdr_file        ON file_hdr_formats(file_id);

-- ─── Données initiales : formats HDR connus ───────────────────────────────

INSERT INTO hdr_formats (name, display_name) VALUES
    ('HDR10',  'HDR10'),
    ('HDR10+', 'HDR10+'),
    ('DV',     'Dolby Vision'),
    ('HLG',    'HLG')
ON CONFLICT (name) DO NOTHING;

-- ─── Nouvelle colonne FK dans video_metadata ──────────────────────────────

ALTER TABLE video_metadata
    ADD COLUMN IF NOT EXISTS video_codec_id INTEGER REFERENCES codecs(id);

-- ─── Migration des données existantes ─────────────────────────────────────

-- 1. Peupler codecs vidéo depuis l'ancienne colonne video_codec
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'video_metadata' AND column_name = 'video_codec') THEN
        INSERT INTO codecs (name, display_name, codec_type)
        SELECT DISTINCT trim(video_codec), UPPER(trim(video_codec)), 'video'
        FROM video_metadata
        WHERE video_codec IS NOT NULL AND trim(video_codec) != ''
        ON CONFLICT (name) DO NOTHING;
    END IF;
END $$;

-- 2. Peupler codecs audio depuis audio_codecs semicolone-délimité
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'video_metadata' AND column_name = 'audio_codecs') THEN
        INSERT INTO codecs (name, display_name, codec_type)
        SELECT DISTINCT trim(c), UPPER(trim(c)), 'audio'
        FROM video_metadata
        CROSS JOIN LATERAL unnest(string_to_array(audio_codecs, ';')) AS c
        WHERE audio_codecs IS NOT NULL AND trim(c) != ''
        ON CONFLICT (name) DO NOTHING;
    END IF;
END $$;

-- 3. Peupler languages depuis les codes ISO 639-2 existants
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'video_metadata' AND column_name = 'audio_languages') THEN
        INSERT INTO languages (code, label)
        SELECT DISTINCT LOWER(trim(lc)), UPPER(trim(lc))
        FROM video_metadata
        CROSS JOIN LATERAL unnest(string_to_array(audio_languages, ';')) AS lc
        WHERE audio_languages IS NOT NULL AND LENGTH(trim(lc)) BETWEEN 2 AND 3
        ON CONFLICT (code) DO NOTHING;
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'video_metadata' AND column_name = 'subtitle_languages') THEN
        INSERT INTO languages (code, label)
        SELECT DISTINCT LOWER(trim(lc)), UPPER(trim(lc))
        FROM video_metadata
        CROSS JOIN LATERAL unnest(string_to_array(subtitle_languages, ';')) AS lc
        WHERE subtitle_languages IS NOT NULL AND LENGTH(trim(lc)) BETWEEN 2 AND 3
        ON CONFLICT (code) DO NOTHING;
    END IF;
END $$;

-- 4. Remplir video_codec_id depuis l'ancienne colonne
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'video_metadata' AND column_name = 'video_codec') THEN
        UPDATE video_metadata vm
        SET video_codec_id = c.id
        FROM codecs c
        WHERE c.name = trim(vm.video_codec)
          AND c.codec_type = 'video'
          AND vm.video_codec IS NOT NULL
          AND vm.video_codec_id IS NULL;
    END IF;
END $$;

-- 5. Migrer les pistes audio (PL/pgSQL pour gérer les tableaux positionnels)
DO $$
DECLARE
    r         RECORD;
    i         INT;
    codec_arr TEXT[];
    lang_arr  TEXT[];
    prof_arr  TEXT[];
    ch_arr    TEXT[];
    lay_arr   TEXT[];
    br_arr    TEXT[];
    cod_id    INT;
    lang_id   INT;
    ch_val    SMALLINT;
    br_val    INT;
    prof_val  TEXT;
    lay_val   TEXT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'video_metadata' AND column_name = 'audio_codecs') THEN
        RETURN;
    END IF;

    FOR r IN
        SELECT vm.file_id, vm.audio_codecs, vm.audio_languages,
               vm.audio_profiles, vm.audio_channels, vm.audio_channel_layouts,
               vm.audio_bitrates
        FROM video_metadata vm
        WHERE vm.audio_codecs IS NOT NULL AND vm.audio_codecs != ''
    LOOP
        codec_arr := string_to_array(r.audio_codecs, ';');
        lang_arr  := COALESCE(string_to_array(r.audio_languages, ';'), ARRAY[]::TEXT[]);
        prof_arr  := COALESCE(string_to_array(r.audio_profiles, ';'), ARRAY[]::TEXT[]);
        ch_arr    := COALESCE(string_to_array(r.audio_channels, ';'), ARRAY[]::TEXT[]);
        lay_arr   := COALESCE(string_to_array(r.audio_channel_layouts, ';'), ARRAY[]::TEXT[]);
        br_arr    := COALESCE(string_to_array(r.audio_bitrates, ';'), ARRAY[]::TEXT[]);

        FOR i IN 1..array_length(codec_arr, 1) LOOP
            -- codec_id
            cod_id := NULL;
            SELECT id INTO cod_id FROM codecs
            WHERE name = trim(codec_arr[i]) AND codec_type = 'audio';

            -- language_id
            lang_id := NULL;
            IF i <= array_length(lang_arr, 1) AND LENGTH(trim(lang_arr[i])) BETWEEN 2 AND 3 THEN
                SELECT id INTO lang_id FROM languages WHERE code = LOWER(trim(lang_arr[i]));
            END IF;

            -- profile
            prof_val := NULL;
            IF i <= array_length(prof_arr, 1) AND trim(prof_arr[i]) != '' THEN
                prof_val := trim(prof_arr[i]);
            END IF;

            -- channels
            ch_val := NULL;
            IF i <= array_length(ch_arr, 1) AND trim(ch_arr[i]) != '' THEN
                BEGIN
                    ch_val := trim(ch_arr[i])::SMALLINT;
                EXCEPTION WHEN OTHERS THEN ch_val := NULL;
                END;
            END IF;

            -- layout
            lay_val := NULL;
            IF i <= array_length(lay_arr, 1) AND trim(lay_arr[i]) != '' THEN
                lay_val := trim(lay_arr[i]);
            END IF;

            -- bitrate
            br_val := NULL;
            IF i <= array_length(br_arr, 1) AND trim(br_arr[i]) != '' THEN
                BEGIN
                    br_val := trim(br_arr[i])::INTEGER;
                EXCEPTION WHEN OTHERS THEN br_val := NULL;
                END;
            END IF;

            INSERT INTO audio_tracks
                (file_id, track_order, codec_id, language_id, profile, channels, layout, bitrate, is_default)
            VALUES
                (r.file_id, i - 1, cod_id, lang_id, prof_val, ch_val, lay_val, br_val, i = 1)
            ON CONFLICT (file_id, track_order) DO NOTHING;
        END LOOP;
    END LOOP;
END $$;

-- 6. Migrer les pistes sous-titres
DO $$
DECLARE
    r        RECORD;
    i        INT;
    lang_arr TEXT[];
    lang_id  INT;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'video_metadata' AND column_name = 'subtitle_languages') THEN
        RETURN;
    END IF;

    FOR r IN
        SELECT vm.file_id, vm.subtitle_languages
        FROM video_metadata vm
        WHERE vm.subtitle_languages IS NOT NULL AND vm.subtitle_languages != ''
    LOOP
        lang_arr := string_to_array(r.subtitle_languages, ';');
        FOR i IN 1..array_length(lang_arr, 1) LOOP
            lang_id := NULL;
            IF LENGTH(trim(lang_arr[i])) BETWEEN 2 AND 3 THEN
                SELECT id INTO lang_id FROM languages WHERE code = LOWER(trim(lang_arr[i]));
            END IF;

            INSERT INTO subtitle_tracks (file_id, track_order, language_id, is_default, is_forced)
            VALUES (r.file_id, i - 1, lang_id, i = 1, false)
            ON CONFLICT (file_id, track_order) DO NOTHING;
        END LOOP;
    END LOOP;
END $$;

-- 7. Migrer les formats HDR (SDR = pas d'entrée dans file_hdr_formats)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name = 'video_metadata' AND column_name = 'hdr_format') THEN
        INSERT INTO file_hdr_formats (file_id, hdr_format_id)
        SELECT vm.file_id, hf.id
        FROM video_metadata vm
        JOIN hdr_formats hf ON hf.name = vm.hdr_format
        WHERE vm.hdr_format IS NOT NULL AND vm.hdr_format NOT IN ('SDR', '')
        ON CONFLICT DO NOTHING;
    END IF;
END $$;

-- ─── Suppression des colonnes obsolètes ───────────────────────────────────

DO $$
DECLARE
    cols TEXT[] := ARRAY[
        'audio_codecs', 'audio_bitrates', 'audio_profiles',
        'audio_languages', 'audio_channels', 'audio_channel_layouts',
        'subtitle_languages', 'subtitle_count',
        'video_codec', 'hdr_format'
    ];
    col TEXT;
BEGIN
    FOREACH col IN ARRAY cols LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'video_metadata' AND column_name = col) THEN
            EXECUTE 'ALTER TABLE video_metadata DROP COLUMN ' || col;
        END IF;
    END LOOP;
END $$;
