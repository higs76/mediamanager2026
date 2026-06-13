-- ==========================================
-- Migration 001 : données initiales
-- Config de base + templates de nommage + catégories par défaut
-- ==========================================
 
-- Config applicative
INSERT INTO config (key, value, description) VALUES
    ('video_extensions',
     '.mkv;.mp4;.avi;.mov;.wmv;.ts;.m2ts;.iso;.m4v;.flv;.divx;.xvid;.mpg;.mpeg;.vob;.rmvb',
     'Extensions de fichiers vidéo surveillées par le scanner (séparées par ;)'),
    ('scan_interval_hours',  '6',    'Intervalle en heures entre deux scans périodiques automatiques'),
    ('analyze_workers',      '2',    'Fichiers analysés en parallèle par session'),
    ('analyze_session_size', '50',   'Nombre max de fichiers par session'),
    ('analyze_auto',         'true', 'Lancer l''analyse automatiquement après un scan')
ON CONFLICT (key) DO NOTHING;
 
-- Templates de nommage système (saisonnables)
-- Format : {serie}{sep1}{prefS}{nn_s}{sep_se}{prefE}{nn_e}{sep2}{titre}.mkv
INSERT INTO naming_templates
    (type, is_default, sep1, sep2, prefix_season, digits_season,
     sep_se, prefix_episode, digits_episode,
     folder_prefix, folder_digits, special_folder)
VALUES
    -- 01x01 standard (séries FR)
    ('seasonal', true, ' - ', ' - ', '',  2, 'x', '', 2, 'S', 2, 'S0'),
    -- S01E01 (format international)
    ('seasonal', true, ' - ', ' - ', 'S', 2, 'E', '', 2, 'S', 2, 'S0'),
    -- 001x001 (animes, numéros longs)
    ('seasonal', true, ' - ', ' - ', '',  3, 'x', '', 3, 'S', 2, 'S0')
ON CONFLICT DO NOTHING;
 
-- Templates de nommage système (films)
INSERT INTO naming_templates
    (type, is_default, sep_year, year_format, bonus_folder)
VALUES
    ('noseasonal', true, ' ', 'paren', 'Bonus'),
    ('noseasonal', true, ' ', 'plain', 'Bonus'),
    ('noseasonal', true, ' ', 'none',  'Bonus')
ON CONFLICT DO NOTHING;
 