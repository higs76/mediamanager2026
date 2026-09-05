-- Migration 010 : config scan_excluded_dirs
-- Ajoute la clé de configuration des dossiers à exclure du scan.
-- Les dossiers #recycle (Synology) n'étaient pas filtrés (uniquement . et @ l'étaient).

INSERT INTO config (key, value, description)
VALUES (
    'scan_excluded_dirs',
    '#recycle,@Recycle,#snapshot,eaRecycleBin,@sharebin,.Trash-1000,$RECYCLE.BIN,RECYCLER',
    'Noms de dossiers à exclure du scan, séparés par des virgules (insensible à la casse). Ex: #recycle,@Recycle'
)
ON CONFLICT (key) DO NOTHING;
