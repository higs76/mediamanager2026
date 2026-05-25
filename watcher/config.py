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
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
LOG_LEVEL = 'DEBUG' if API_DEBUG else 'INFO'
LOG_FILE = LOGS_PATH / 'mediamanager.log'