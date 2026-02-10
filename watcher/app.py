"""
Point d'entrée principal du Watcher MediaManager

Usage:
    python -m watcher.app
    ou
    python watcher/app.py
"""

import logging
import sys
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from watcher.config import (
    API_HOST, API_PORT, API_DEBUG, PROJECT_ROOT,
    DATABASE_URL, MOUNT_BASE_PATH, LOG_LEVEL, LOG_FILE
)
from watcher.database import test_db_connection

# ==========================================
# Configuration Logging
# ==========================================
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# ==========================================
# Créer l'app FastAPI
# ==========================================
app = FastAPI(
    title="MediaManager Watcher",
    description="Service de surveillance des fichiers vidéo",
    version="0.1.0"
)

# ==========================================
# Middleware CORS (pour accès depuis l'UI)
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # À restreindre en prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Endpoints Health Check
# ==========================================
@app.get("/health")
def health_check():
    """Endpoint de health check basique"""
    return JSONResponse({
        "status": "ok",
        "service": "mediamanager-watcher",
        "version": "0.1.0"
    })

# ==========================================
# Endpoints Status
# ==========================================
@app.get("/status")
def get_status():
    """
    Retourne le statut actuel du watcher
    Vérifie la connexion BD, la config, etc.
    """
    
    # Test connexion BD
    db_ok = test_db_connection()
    
    return JSONResponse({
        "status": "running" if db_ok else "error",
        "service": "mediamanager-watcher",
        "database": {
            "connected": db_ok,
            "url": DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else "***"
        },
        "mount_base_path": str(MOUNT_BASE_PATH),
        "debug": API_DEBUG,
        "project_root": str(PROJECT_ROOT)
    })

# ==========================================
# Endpoints Config
# ==========================================
@app.get("/config")
def get_config():
    """
    Retourne la configuration actuelle (pour debug)
    NE PAS exposer les mots de passe en prod !
    """
    return JSONResponse({
        "api_host": API_HOST,
        "api_port": API_PORT,
        "api_debug": API_DEBUG,
        "mount_base_path": str(MOUNT_BASE_PATH),
        "log_level": LOG_LEVEL,
        "log_file": str(LOG_FILE)
    })

# ==========================================
# Main
# ==========================================
if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 60)
    logger.info(f"🚀 Démarrage MediaManager Watcher")
    logger.info(f"   API: http://{API_HOST}:{API_PORT}")
    logger.info(f"   Debug: {API_DEBUG}")
    logger.info(f"   Logs: {LOG_FILE}")
    logger.info("=" * 60)
    
    try:
        uvicorn.run(
            "watcher.app:app",
            host=API_HOST,
            port=API_PORT,
            reload=API_DEBUG,
            log_level="info"
        )
    except KeyboardInterrupt:
        logger.info("Arrêt du watcher...")
        sys.exit(0)