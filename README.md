# MediaManager 2026

Service de gestion des fichiers vidéo : détection, analyse, organisation et renommage intelligent.

## Vue d'ensemble

MediaManager 2026 est composé de deux services :

1. **Watcher Service** : surveillance 24/24 des dossiers NAS, détection de fichiers, extraction de métadonnées
2. **User App** : interface de consultation, validation des renommages, gestion contexte (vu/résumés)

## Architecture
```
PC/VM (Développement)
  └── VS Code (code Python)

Proxmox (Infra)
  ├── VM Dev (développement/test)
  └── VM Prod (futur)
    ├── PostgreSQL (BD)
    ├── Watcher Service (Python/FastAPI)
    └── MediaManagerMnt/ (montages SMB)
```

## Prérequis

- Python 3.11+
- PostgreSQL 13+
- Git
- ffprobe/mediainfo (pour analyse vidéo)
- Accès SMB aux NAS Synology

## Installation

### 1. Cloner le repo
```bash
cd C:\devs\Repos
git clone https://github.com/higs76/mediamanager2026.git
cd mediamanager2026
```

### 2. Créer l'environnement Python
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou sur Windows :
venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configurer l'environnement
```bash
cp .env.example .env
# Éditez .env avec vos paramètres
```

### 4. Initialiser la BD

Sur la VM Proxmox Linux :
```bash
python scripts/deploy.py --setup
# ou pas à pas :
python scripts/deploy.py --create-db
python scripts/deploy.py --init-tables
```

## Démarrage

### Watcher Service
```bash
python -m watcher.app
# ou
python watcher/app.py
```

API disponible sur : http://localhost:8000

Endpoints :
- `GET /health` : health check
- `GET /status` : statut du service
- `GET /config` : configuration (debug)

### Tests
```bash
pytest
```

## Structure du projet
```
mediamanager2026/
├── watcher/              # Service watcher principal
│   ├── app.py           # Point d'entrée
│   ├── config.py        # Configuration
│   ├── database.py      # Connexion BD
│   ├── monitor.py       # Surveillance fichiers
│   ├── analyzer.py      # Analyse métadonnées
│   └── api.py           # Endpoints additionnels
├── database/            # Gestion BD
│   ├── schema.sql       # Structure BD
│   └── init_db.py       # Initialisation
├── scripts/             # Scripts utilitaires
│   ├── deploy.py        # Déploiement et setup
│   ├── backup_db.sh     # Backup BD
│   └── restore_db.sh    # Restauration BD
├── tests/               # Tests unitaires
├── docker/              # Dockerisation (futur)
├── config/              # Fichiers config
└── logs/                # Logs du service
```

## Déploiement

### Setup complet
```bash
python scripts/deploy.py --setup
```

### Opérations individuelles
```bash
# Créer la BD
python scripts/deploy.py --create-db

# Initialiser les tables
python scripts/deploy.py --init-tables

# Vérifier l'installation
python scripts/deploy.py --check

# Backup BD
python scripts/deploy.py --backup

# Restaurer BD
python scripts/deploy.py --restore backup_file.sql
```

## Configuration

### Variables d'environnement (.env)
```
DATABASE_URL=postgresql://mediamanager:password@localhost:5432/mediamanager_db
API_HOST=0.0.0.0
API_PORT=8000
API_DEBUG=False
MOUNT_BASE_PATH=/home/mediamanager/MediaManagerMnt
```

### Dossiers NAS

Structure des montages :
```
MediaManagerMnt/
├── series/
│   ├── 1-series/         → //nas1/series
│   └── 2-series/         → //nas2/series
├── films/
│   ├── 1-films/          → //nas1/films
│   └── 2-films/          → //nas3/films
├── animes/
├── documentaires/
```

## Développement

### Ajouter une dépendance
```bash
pip install package_name
pip freeze > requirements.txt
```

### Créer une migration BD
```bash
# Ajouter un fichier dans database/migrations/
# Exécuter manuellement avec psql
```

## Logs

Les logs sont stockés dans `logs/mediamanager.log` et affichés en console.

## Roadmap

- [ ] Phase 1 : Watcher fiable
- [ ] Phase 2 : Extraction métadonnées
- [ ] Phase 3 : Moteur règles renommage
- [ ] Phase 4 : Interface utilisateur (Web/Desktop)

## Support

Pour les erreurs, consultez `logs/mediamanager.log`

## Licence

À définir