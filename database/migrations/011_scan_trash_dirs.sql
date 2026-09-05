-- Migration 011 : sépare deux notions distinctes de dossiers spéciaux au scan
--   - scan_excluded_dirs : ignorés COMPLÈTEMENT (ni scannés, ni mesurés) — ex: dossiers de test
--   - scan_trash_dirs    : corbeilles NAS — mesurées (taille récupérable) mais jamais cataloguées
-- scan_excluded_dirs contenait par erreur la liste des corbeilles (migration 010) ;
-- cette liste est reprise ici sous scan_trash_dirs, et scan_excluded_dirs redevient vide.

UPDATE config
SET description = 'Noms de dossiers à ignorer complètement du scan (ni scannés, ni mesurés), séparés par des virgules. Ex: test,brouillon'
WHERE key = 'scan_excluded_dirs';

INSERT INTO config (key, value, description)
VALUES (
    'scan_trash_dirs',
    '#recycle,@Recycle,#snapshot,eaRecycleBin,@sharebin,.Trash-1000,$RECYCLE.BIN,RECYCLER',
    'Noms de dossiers reconnus comme corbeilles NAS : mesurés (espace récupérable) mais jamais catalogués, séparés par des virgules. Ex: #recycle,@Recycle'
)
ON CONFLICT (key) DO NOTHING;
