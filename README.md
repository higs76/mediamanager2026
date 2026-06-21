# MediaManager 2026

Service de gestion de fichiers vidéo : surveillance de NAS (SMB/NFS), détection, analyse ffprobe, catalogage automatique et interface de renommage.

## Fonctionnalités

- **Surveillance NAS** — montages SMB/NFS scannés en arrière-plan, détection des nouveaux fichiers et des suppressions
- **Analyse ffprobe** — extraction codec, résolution, bitrate, HDR, pistes audio (format Dolby/DTS/TrueHD, layout canaux, bitrate), sous-titres
- **Catalogue** — titres et épisodes regroupés automatiquement, propositions de renommage générées selon des règles configurables
- **Interface bibliothèque** — navigation catégories → titres → épisodes, filtres, recherche, marquer comme vu, détail technique complet
- **Interface renommage** — validation des propositions titre par titre, édition inline, aperçu en temps réel
- **Interface admin** — dashboard, gestion des montages, configuration, logs, mise à jour via GitHub
- **Thèmes** — dark / light / auto

---

## Identifiants par défaut après installation

| Élément | Valeur |
|---|---|
| Utilisateur système | `mediamanager` |
| Mot de passe système | `mediamanager` |
| Utilisateur PostgreSQL | `mediamanager` |
| Mot de passe PostgreSQL | `mediamanager` |
| Base de données | `mediamanager_db` |

> ⚠️ À changer en production :
> ```bash
> passwd mediamanager
> sudo -u postgres psql -c "ALTER USER mediamanager PASSWORD 'nouveaumdp';"
> # Mettre à jour DATABASE_URL dans /home/mediamanager/app/.env
> ```

---

## Installation sur Proxmox (LXC)

### Méthode recommandée — script automatique

Sur le **host Proxmox** :

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/main/scripts/mediamanager-proxmox.sh)
```

Ce script :
- Crée et configure le LXC Ubuntu 24.04
- Détecte automatiquement la branche depuis le fichier `VERSION`
  - `VERSION` sans suffixe → installe depuis `main` (stable)
  - `VERSION` avec `-dev` → installe depuis `dev`
- Lance `proxmox-install.sh` à l'intérieur du LXC

### Installation manuelle dans un LXC existant

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/main/scripts/proxmox-install.sh)
```

---

## Accès après installation

| Service | URL |
|---|---|
| Interface bibliothèque | `http://<IP_LXC>:8000/` |
| Interface admin | `http://<IP_LXC>:8000/admin/` |
| Documentation API | `http://<IP_LXC>:8000/docs` |

---

## Gestion du service

```bash
# Statut
systemctl status mediamanager-watcher

# Redémarrage
sudo systemctl restart mediamanager-watcher

# Logs en temps réel
journalctl -u mediamanager-watcher -f
```

---

## Mise à jour

### Via l'interface admin
Bouton **⬆ Màj** dans le header → « Lancer la mise à jour »

Le service fait un `git pull` et redémarre automatiquement.

### Via ligne de commande
```bash
cd /home/mediamanager/app
git pull
sudo systemctl restart mediamanager-watcher
```

---

## Configuration

Fichier : `/home/mediamanager/app/.env`

| Variable | Description | Défaut |
|---|---|---|
| `DATABASE_URL` | URL PostgreSQL | `postgresql://mediamanager:...` |
| `API_HOST` | IP d'écoute | `0.0.0.0` |
| `API_PORT` | Port API | `8000` |
| `MOUNT_BASE_PATH` | Dossier racine des montages | `/home/mediamanager/MediaManagerMnt` |
| `ALLOW_PRERELEASE` | Voir les pre-releases (dev uniquement) | `false` |

---

## Structure du projet

```
mediamanager2026/
├── watcher/                      # Service principal FastAPI
│   ├── app.py                   # Cycle de vie, middleware, montage statiques
│   ├── api.py                   # Assembleur des routers
│   ├── scanner.py               # Détection fichiers sur NAS (ScanQueue)
│   ├── analyzer.py              # Extraction ffprobe (AnalyzeQueue)
│   ├── cataloger.py             # Construction catalogue + propositions (CatalogQueue)
│   ├── config.py                # Variables d'environnement (.env)
│   ├── config_db.py             # Configuration dynamique depuis la BDD
│   ├── database.py              # Connexion SQLAlchemy
│   ├── routers/
│   │   ├── library.py           # Bibliothèque : catégories, titres, items, détail
│   │   ├── categories.py        # CRUD catégories, règles de nommage
│   │   ├── mounts.py            # CRUD montages NAS, sync, browse
│   │   ├── stats.py             # Statistiques qualité, jobs
│   │   └── system.py            # Config, update, version, logs
│   └── utils/
│       ├── perf.py              # Ring buffer monitoring performances SQL
│       ├── versioning.py        # git info, GitHub releases
│       └── system_info.py       # hostname, IP, uptime
├── database/
│   ├── schema.sql               # Structure des tables (appliqué auto au démarrage)
│   └── migrations/              # Migrations incrémentielles (appliquées une seule fois)
├── frontend/
│   ├── app/                     # Interface utilisateur (bibliothèque + renommage)
│   │   ├── index.html
│   │   ├── app.css              # Styles (thèmes dark/light/auto, ~1000 lignes)
│   │   ├── library.js           # Navigation catalogue, détail technique
│   │   └── rename.js            # Interface validation propositions de renommage
│   └── admin/                   # Interface d'administration
│       ├── index.html
│       ├── admin.css
│       ├── admin.js             # Dashboard, logs, jobs
│       ├── mounts.js            # Gestion montages NAS
│       ├── config.js            # Éditeur configuration
│       ├── stats.js             # Statistiques qualité vidéo
│       └── perf.js              # Monitoring performances SQL
├── scripts/
│   ├── mediamanager-proxmox.sh          # Création du LXC sur Proxmox
│   ├── proxmox-install.sh               # Installation dans le LXC
│   ├── mediamanager-watcher.service     # Unité systemd
│   └── deploy-to-lxc.ps1               # Déploiement rapide depuis Windows
├── run.py                       # Point d'entrée uvicorn
├── .env.example                 # Template de configuration
└── VERSION                      # Version actuelle (ex: 0.5.2-dev)
```

---

## Base de données

Les tables sont créées automatiquement au démarrage depuis `database/schema.sql`.  
Les migrations dans `database/migrations/` sont appliquées une seule fois et tracées dans `schema_migrations`.

Tables principales :

| Table | Description |
|---|---|
| `categories` | Types de médias (Séries, Films, Animés…) |
| `mounts` | Montages NAS (header commun SMB/NFS) |
| `mount_smb` | Paramètres spécifiques SMB/CIFS |
| `mount_nfs` | Paramètres spécifiques NFS |
| `media_files` | Fichiers détectés sur les montages |
| `media_titles` | Titres catalogués (série ou film) |
| `media_items` | Épisodes / fichiers liés à un titre |
| `video_metadata` | Métadonnées ffprobe (codec, résolution, audio, HDR…) |
| `rename_proposals` | Propositions de renommage générées par le catalogueur |
| `media_files_history` | Historique des fichiers renommés |
| `app_config` | Configuration dynamique (clé/valeur) |
| `scan_jobs` | Historique des scans par montage |
| `analyze_sessions` | Sessions d'analyse ffprobe |
| `schema_migrations` | Migrations appliquées |

---

## Prérequis techniques

- Proxmox VE 7+ (pour l'installation LXC automatique)
- Python 3.12+
- PostgreSQL 15+
- Ubuntu 24.04 (dans le LXC)
- ffprobe (ffmpeg) — installé automatiquement par le script

---

## Versioning

| Suffixe | Branche | Visibilité |
|---|---|---|
| `0.5.2` | `main` | Tous les utilisateurs |
| `0.5.2-dev` | `dev` | Développeur uniquement (`ALLOW_PRERELEASE=true`) |

### Publier une nouvelle version

```bash
# Branche dev → pre-release
git tag v0.5.2-dev
git push origin v0.5.2-dev
# Sur GitHub : Create release → cocher "Pre-release"

# Branche main → release stable
git checkout main && git merge dev
echo "0.5.2" > VERSION
git tag v0.5.2
git push origin main && git push origin v0.5.2
# Sur GitHub : Create release → NE PAS cocher "Pre-release"
git checkout dev && git merge main
```

---

## Roadmap

- [x] Phase 1 — Watcher + gestion montages NAS (SMB/NFS), scan arrière-plan
- [x] Phase 1 — Interface admin (dashboard, logs, montages, configuration)
- [x] Phase 1 — Mise à jour automatique via GitHub
- [x] Phase 2 — Extraction métadonnées vidéo (ffprobe) : codec, résolution, bitrate vidéo/audio, HDR, layout canaux, format Dolby/DTS
- [x] Phase 2 — Statistiques qualité par catégorie (résolutions, codecs, poids)
- [x] Phase 3 — Catalogueur automatique (titres, épisodes, saisons)
- [x] Phase 3 — Moteur de propositions de renommage (règles configurables)
- [x] Phase 4 — Interface bibliothèque (navigation, recherche, détail technique, marquer vu)
- [x] Phase 4 — Interface renommage (validation, édition inline, aperçu)
- [ ] Authentification (HTTP Basic Auth)
- [ ] Tests d'intégration
- [ ] Champs audio en arrays PostgreSQL natifs (TEXT[])
