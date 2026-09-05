"""
Configuration management pour MediaManager Watcher
Charge les variables d'environnement et fournit des constantes
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Charger .env
ENV_FILE = Path(__file__).parent.parent / '.env'
if ENV_FILE.exists():
    load_dotenv(ENV_FILE)

# ==========================================
# Database Configuration
# ==========================================
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://mediamanager:changeme@localhost:5432/mediamanager_db'
)

# ==========================================
# API Configuration
# ==========================================
API_HOST = os.getenv('API_HOST', '0.0.0.0')
API_PORT = int(os.getenv('API_PORT', 8000))
API_DEBUG = os.getenv('API_DEBUG', 'False').lower() == 'true'

# ==========================================
# Paths
# ==========================================
PROJECT_ROOT = Path(__file__).parent.parent
MOUNT_BASE_PATH = Path(os.getenv('MOUNT_BASE_PATH', '/home/mediamanager/MediaManagerMnt'))
LOGS_PATH = Path(os.getenv('LOGS_PATH', PROJECT_ROOT / 'logs'))

# Créer les dossiers s'ils n'existent pas
LOGS_PATH.mkdir(exist_ok=True)

# ==========================================
# NAS/SMB Configuration
# ==========================================
SMB_DEFAULT_USERNAME = os.getenv('SMB_DEFAULT_USERNAME', 'user')
SMB_DEFAULT_PASSWORD = os.getenv('SMB_DEFAULT_PASSWORD', 'password')

# ==========================================
# Update / Versioning
# ==========================================
# IS_DEV est deduit automatiquement depuis le fichier VERSION :
#   "0.4.0"     → mode production  → seules les releases stables sont proposées
#   "0.4.0-dev" → mode dev         → les pre-releases sont aussi proposées
#
# Pas de variable .env à configurer — le fichier VERSION suffit.
_version_file = PROJECT_ROOT / 'VERSION'
_version_str  = _version_file.read_text(encoding='utf-8').strip() if _version_file.exists() else ''
IS_DEV         = '-dev' in _version_str or '-beta' in _version_str or '-rc' in _version_str
# ==========================================
# Auth / Sessions
# ==========================================
# Clé de signature des cookies de session.
# Si SECRET_KEY n'est pas dans .env, on dérive une valeur stable depuis DATABASE_URL
# (pas de configuration manuelle requise, mais moins sécurisé qu'une vraie clé).
import hashlib as _hashlib
SECRET_KEY = os.getenv("SECRET_KEY") or _hashlib.sha256(
    f"mm_2026_session__{DATABASE_URL}".encode()
).hexdigest()
del _hashlib

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_LEVEL = 'DEBUG' if API_DEBUG else 'INFO'
LOG_FILE = LOGS_PATH / 'mediamanager.log'


def _get_log_retention_days() -> int:
    """Rotation quotidienne (minuit) — nombre de jours d'historique conservés.
    Sans rotation, le fichier grossit indéfiniment (constaté : 41 Mo / 522k lignes).

    Lu depuis la table `config` (modifiable via l'UI Config) si la BDD est déjà
    accessible ; sinon retombe sur .env / la valeur par défaut — ce code tourne
    avant le reste du bootstrap (migrations pas encore appliquées au tout
    premier démarrage), donc toute erreur ici doit rester silencieuse."""
    default = int(os.getenv('LOG_RETENTION_DAYS', 14))
    try:
        from sqlalchemy import create_engine, text
        _probe = create_engine(DATABASE_URL)
        with _probe.connect() as conn:
            row = conn.execute(text(
                "SELECT value FROM config WHERE key = 'log_retention_days'"
            )).fetchone()
        _probe.dispose()
        if row:
            return int(row[0])
    except Exception:
        pass
    return default


LOG_RETENTION_DAYS = _get_log_retention_days()