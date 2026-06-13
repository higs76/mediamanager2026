# MediaManager 2026

Service de gestion de fichiers vidéo : surveillance des NAS, détection,
analyse et organisation automatique.

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
| Interface admin | `http://<IP_LXC>:8000/admin/` |
| API REST | `http://<IP_LXC>:8000` |
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
├── watcher/                  # Service principal
│   ├── app.py               # Application FastAPI + démarrage
│   ├── api.py               # Endpoints admin (montages, sync, update)
│   ├── config.py            # Configuration depuis .env
│   └── database.py          # Connexion SQLAlchemy
├── database/
│   └── schema.sql           # Structure des tables (appliqué auto au démarrage)
├── frontend/admin/          # Interface web d'administration
│   ├── index.html           # Shell HTML
│   ├── admin.css            # Styles (thèmes dark/light/auto)
│   ├── admin.js             # Dashboard, logs, API, versioning
│   └── mounts.js            # Gestion des montages NAS
├── scripts/
│   ├── mediamanager-proxmox.sh      # Création du LXC sur Proxmox
│   ├── proxmox-install.sh           # Installation dans le LXC
│   └── mediamanager-watcher.service # Unité systemd
├── tests/                   # Tests (à développer)
├── run.py                   # Point d'entrée uvicorn
├── .env.example             # Template de configuration
└── VERSION                  # Version actuelle (ex: 0.4.0)
```

---

## Base de données

Les tables sont créées automatiquement au démarrage depuis `database/schema.sql`.
Aucune action manuelle nécessaire.

Tables principales :
- `categories` — types de médias (séries, films, animés…)
- `mounts` — montages NAS (header commun SMB/NFS)
- `mount_smb` — paramètres spécifiques SMB/CIFS
- `mount_nfs` — paramètres spécifiques NFS
- `files` — fichiers détectés
- `video_metadata` — métadonnées vidéo (Phase 2)
- `rename_proposals` — propositions de renommage (Phase 3)

---

## Versioning

| Suffixe | Branche | Visibilité |
|---|---|---|
| `0.4.0` | `main` | Tous les utilisateurs |
| `0.4.0-dev` | `dev` | Développeur uniquement (`ALLOW_PRERELEASE=true`) |

### Publier une nouvelle version

```bash
# Branche dev → test
git tag v0.4.0-dev
git push origin v0.4.0-dev
# Sur GitHub : Create release → cocher "Pre-release"

# Branche main → release stable
git checkout main && git merge dev
echo "0.4.0" > VERSION
git tag v0.4.0
git push origin main && git push origin v0.4.0
# Sur GitHub : Create release → NE PAS cocher "Pre-release"
git checkout dev && git merge main
```

---

## Roadmap

- [x] Phase 1 — Watcher fiable + gestion montages NAS (SMB/NFS)
- [x] Interface admin (dashboard, logs, API, thèmes)
- [x] Mise à jour automatique via GitHub
- [ ] Phase 2 — Extraction métadonnées vidéo (ffprobe/mediainfo)
- [ ] Phase 3 — Moteur de règles de renommage
- [ ] Phase 4 — Interface utilisateur finale

---

## Prérequis techniques

- Proxmox VE 7+ (pour l'installation LXC automatique)
- Python 3.12+
- PostgreSQL 15+
- Ubuntu 24.04 (dans le LXC)

# ![Dashboard](docs/screenshots/dashboard.png)