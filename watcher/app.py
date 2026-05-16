"""
Point d'entrée principal du Watcher MediaManager

Inclut :
- API de santé
- API Admin Panel (dashboard, contrôle services, logs)
- API utilisateur (future)
"""

import logging
import socket
import sys
import os
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from packaging import version

from watcher.config import (
    API_HOST, API_PORT, API_DEBUG, PROJECT_ROOT,
    DATABASE_URL, MOUNT_BASE_PATH, LOG_LEVEL, LOG_FILE
)
from watcher.database import test_db_connection, engine
from watcher.api import router as admin_router
from sqlalchemy import text

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

# Lire la version
VERSION_FILE = PROJECT_ROOT / 'VERSION'
if VERSION_FILE.exists():
    APP_VERSION = VERSION_FILE.read_text().strip()
else:
    APP_VERSION = "0.1.0-unknown"

# ==========================================
# Init BDD au démarrage
# NOTE : placé ici (niveau module) pour s'exécuter
# que l'app soit lancée via uvicorn ou __main__.
# ==========================================
def init_database_tables():
    """
    Crée les tables si elles n'existent pas (idempotent).
    Exécute database/schema.sql statement par statement.
    """
    schema_file = PROJECT_ROOT / 'database' / 'schema.sql'
    if not schema_file.exists():
        logger.warning(f"⚠ schema.sql non trouvé : {schema_file}")
        return
    try:
        import psycopg2
        from watcher.config import DATABASE_URL
        # encoding='utf-8' obligatoire : schema.sql contient des caractères
        # accentués dans les commentaires, et le LXC peut être en locale ASCII
        sql = schema_file.read_text(encoding='utf-8')
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        conn.set_client_encoding('UTF8')
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.close()
        logger.info("✓ Tables BDD vérifiées / créées")
    except Exception as e:
        logger.error(f"✗ Erreur init tables : {e}")


def ensure_system_dependencies():
    """
    Vérifie et installe les dépendances système nécessaires si absentes.
    Transparent pour l'utilisateur — géré automatiquement au démarrage.
    - smbclient  : nécessaire pour lister les partages SMB (bouton Parcourir)
    - nfs-common : contient showmount, nécessaire pour lister les exports NFS
    - cifs-utils : nécessaire pour monter les partages SMB (mount -t cifs)
    """
    import shutil
    import subprocess
 
    packages_needed = []
    if not shutil.which("smbclient"):
        packages_needed.append("smbclient")
    if not shutil.which("showmount"):
        packages_needed.append("nfs-common")
    if not shutil.which("mount.cifs"):
        packages_needed.append("cifs-utils")
 
    if not packages_needed:
        logger.info("✓ Dependances systeme OK")
        return
 
    logger.info(f"Installation des dependances manquantes : {', '.join(packages_needed)}")
    try:
        import shutil
        # Chemin absolu obligatoire : PATH restreint sous systemd
        apt = "/usr/bin/apt-get"
        if not os.path.exists(apt):
            apt = shutil.which("apt-get") or "/usr/bin/apt-get"
        # sudo obligatoire : le service tourne en tant que mediamanager (non-root)
        # Le sudoers autorise exactement cette commande pour cet utilisateur
        subprocess.run(
            ["sudo", apt, "install", "-y", "-qq"] + packages_needed,
            capture_output=True, text=True, timeout=120
        )
        logger.info(f"✓ Dependances installees : {', '.join(packages_needed)}")
    except Exception as e:
        logger.warning(f"⚠ Impossible d'installer les dependances : {e}")


def ensure_timezone():
    """
    Configure le fuseau horaire Europe/Paris si le système est en UTC.
    Évite le décalage de 2h dans les logs.
    """
    import subprocess, os
    # Chemin absolu : le service systemd tourne avec un PATH restreint
    timedatectl = "/usr/bin/timedatectl"
    if not os.path.exists(timedatectl):
        logger.warning("⚠ timedatectl introuvable — timezone non configurée")
        return
    try:
        result = subprocess.run(
            [timedatectl, "show", "--property=Timezone", "--value"],
            capture_output=True, text=True, timeout=5
        )
        current_tz = result.stdout.strip()
        if current_tz != "Europe/Paris":
            subprocess.run(
                [timedatectl, "set-timezone", "Europe/Paris"],
                capture_output=True, timeout=5
            )
            os.environ["TZ"] = "Europe/Paris"
            logger.info("✓ Timezone configurée : Europe/Paris")
        else:
            logger.info(f"✓ Timezone OK : {current_tz}")
    except Exception as e:
        logger.warning(f"⚠ Impossible de configurer la timezone : {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Gestionnaire de cycle de vie — remplace le @on_event déprécié.
    Tout ce qui est avant 'yield' s'exécute au démarrage,
    tout ce qui est après s'exécutera à l'arrêt.
    """
    logger.info("=" * 60)
    logger.info(f"🚀 Démarrage MediaManager Watcher v{APP_VERSION}")
    logger.info(f"   API: http://{API_HOST}:{API_PORT}")
    logger.info(f"   Admin: http://{API_HOST}:{API_PORT}/admin")
    logger.info("=" * 60)
    ensure_timezone()
    ensure_system_dependencies()
    init_database_tables()
    yield
    # Arrêt propre (rien à faire pour l'instant)
    logger.info("Arrêt du service MediaManager Watcher")


# ==========================================
# Créer l'app FastAPI
# ==========================================
app = FastAPI(
    title="MediaManager Watcher",
    description="Service de surveillance des fichiers vidéo",
    version=APP_VERSION,
    lifespan=lifespan
)

# ==========================================
# Middleware CORS
# ==========================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# Router Admin (montages, catégories, browse)
# ==========================================
app.include_router(admin_router)


# ==========================================
# Servir les fichiers statiques (Frontend Admin)
# ==========================================
static_path = PROJECT_ROOT / "frontend" / "admin"
if static_path.exists():
    app.mount("/admin", StaticFiles(directory=str(static_path), html=True), name="admin")
    logger.info(f"✓ Admin frontend mounted at /admin → {static_path}")
else:
    logger.warning(f"⚠ Admin frontend not found at {static_path}")



@app.get("/admin")
def admin_redirect():
    """Redirige /admin vers /admin/"""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/admin/", status_code=307)

# ==========================================
# ENDPOINTS SANTÉ
# ==========================================

@app.get("/health")
def health_check():
    """Endpoint simple de santé"""
    return JSONResponse({
        "status": "ok",
        "service": "mediamanager-watcher",
        "version": APP_VERSION
    })

# ==========================================
# ENDPOINTS ADMIN PANEL
# ==========================================

@app.get("/api/admin/dashboard")
def get_dashboard():
    """
    Retourne le dashboard complet pour l'Admin Panel
    - Version app
    - Statut des services
    - Statut de la BD
    - Statut des montages
    """
    # Récupérer la version de GitHub
    github_version = get_latest_github_version()
    version_info = {}
    
    if github_version["error"] is None:
        version_info = compare_versions(APP_VERSION, github_version["version"])
        version_info["latest_url"] = github_version["url"]
    else:
        version_info = {
            "has_update": False,
            "current": APP_VERSION,
            "error": github_version["error"]
        }

    # Test connexion BD
    db_ok = test_db_connection()
    
    # Statut watcher (on considère qu'il tourne si on reçoit cette requête)
    watcher_running = True  # TODO: vérifier le PID du process réel
    
    # Statut PostgreSQL
    postgres_running = check_postgres_running()

    # Statut montages
    mounts_info = get_mounts_info()
    
    return JSONResponse({
        "version": APP_VERSION,
        "timestamp": datetime.now().isoformat(),
        "update_available": version_info,  # ← NOUVEAU
        "services": {
            "watcher": {
                "name": "Watcher Service",
                "status": "running" if watcher_running else "stopped",
                "uptime": "unknown",  # TODO: calculer uptime réel
                "pid": os.getpid()
            },
            "database": {
                "name": "PostgreSQL",
                "status": "connected" if db_ok else "disconnected",
                "type": "PostgreSQL 16",
                "database": "mediamanager_db"
            },
            "mounts": {
                "name": "SMB Mounts",
                "status": "healthy" if mounts_info["healthy"] else "degraded",
                "total": mounts_info["total"],
                "healthy": mounts_info["healthy"],
                "failed": mounts_info["failed"]
            }
        },
        "system": {
            "host": get_hostname(),
            "ip": get_local_ip(),
            "mount_base_path": str(MOUNT_BASE_PATH)
        }
    })


@app.get("/api/admin/logs")
def get_logs(lines: int = 50):
    """
    Retourne les dernières lignes du fichier log
    
    Paramètres:
    - lines: nombre de lignes à retourner (default: 50)
    """
    
    if not LOG_FILE.exists():
        return JSONResponse({
            "error": f"Log file not found: {LOG_FILE}",
            "logs": []
        }, status_code=404)
    
    try:
        log_content = LOG_FILE.read_text()
        log_lines = log_content.split('\n')
        
        # Prendre les dernières N lignes
        last_lines = log_lines[-lines:] if len(log_lines) > lines else log_lines
        
        return JSONResponse({
            "file": str(LOG_FILE),
            "total_lines": len(log_lines),
            "returned_lines": len(last_lines),
            "logs": last_lines
        })
    except Exception as e:
        logger.error(f"Erreur lecture logs: {e}")
        return JSONResponse({
            "error": str(e),
            "logs": []
        }, status_code=500)


@app.post("/api/admin/services/{service}/restart")
def restart_service(service: str):
    """
    Redémarre un service systemd
    
    Services disponibles:
    - watcher
    - postgresql
    """
    
    if service not in ["watcher", "postgresql"]:
        return JSONResponse({
            "error": f"Service '{service}' not recognized"
        }, status_code=400)
    
    service_name = f"mediamanager-watcher" if service == "watcher" else "postgresql"
    
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "restart", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logger.info(f"Service {service_name} redémarré")
            return JSONResponse({
                "status": "success",
                "service": service,
                "message": f"Service {service} restarted"
            })
        else:
            logger.error(f"Erreur restart {service_name}: {result.stderr}")
            return JSONResponse({
                "status": "error",
                "service": service,
                "error": result.stderr
            }, status_code=500)
            
    except Exception as e:
        logger.error(f"Exception restart service: {e}")
        return JSONResponse({
            "status": "error",
            "service": service,
            "error": str(e)
        }, status_code=500)


@app.post("/api/admin/services/{service}/stop")
def stop_service(service: str):
    """
    Arrête un service systemd
    """
    
    if service not in ["watcher"]:  # On laisse PostgreSQL tranquille
        return JSONResponse({
            "error": f"Cannot stop service '{service}'"
        }, status_code=400)
    
    service_name = "mediamanager-watcher"
    
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "stop", service_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            logger.info(f"Service {service_name} arrêté")
            return JSONResponse({
                "status": "success",
                "service": service,
                "message": f"Service {service} stopped"
            })
        else:
            return JSONResponse({
                "status": "error",
                "service": service,
                "error": result.stderr
            }, status_code=500)
            
    except Exception as e:
        logger.error(f"Exception stop service: {e}")
        return JSONResponse({
            "status": "error",
            "error": str(e)
        }, status_code=500)


@app.get("/api/admin/status")
def get_status():
    """
    Status détaillé (ancien endpoint, garde pour compatibilité)
    """
    
    db_ok = test_db_connection()
    
    return JSONResponse({
        "status": "running" if db_ok else "error",
        "service": "mediamanager-watcher",
        "database": {
            "connected": db_ok,
            "url": DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else "***"
        },
        "mount_base_path": str(MOUNT_BASE_PATH),
    })

# ==========================================
# Vérifier les versions
# ==========================================

def get_latest_github_version() -> dict:
    """
    Récupère la dernière version depuis GitHub releases
    Retourne: {"version": "x.y.z", "url": "...", "error": null/str}
    """
    try:
        # Récupérer les releases de GitHub
        url = "https://api.github.com/repos/higs76/mediamanager2026/releases/latest"
        headers = {"Accept": "application/vnd.github.v3+json"}
        
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            return {
                "version": data.get("tag_name", "unknown").lstrip("v"),
                "url": data.get("html_url"),
                "published_at": data.get("published_at"),
                "error": None
            }
        else:
            return {
                "version": None,
                "url": None,
                "published_at": None,
                "error": f"GitHub API returned {response.status_code}"
            }
    except Exception as e:
        return {
            "version": None,
            "url": None,
            "published_at": None,
            "error": str(e)
        }
    
def compare_versions(current: str, latest: str) -> dict:
    """
    Compare deux versions et retourne l'info
    Retourne: {"has_update": bool, "current": str, "latest": str}
    """
    try:
        current_v = version.parse(current)
        latest_v = version.parse(latest)
        
        has_update = latest_v > current_v
        
        return {
            "has_update": has_update,
            "current": str(current_v),
            "latest": str(latest_v),
            "message": f"Update available: {current} → {latest}" if has_update else "You are up to date"
        }
    except Exception as e:
        return {
            "has_update": False,
            "current": current,
            "latest": latest,
            "error": str(e)
        }    

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def check_postgres_running() -> bool:
    """Vérifie si PostgreSQL tourne"""
    try:
        result = subprocess.run(
            ["sudo", "systemctl", "is-active", "postgresql"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


def get_mounts_info() -> dict:
    """Récupère info sur les montages"""
    # TODO: implémenter vérification réelle des montages SMB
    return {
        "total": 0,
        "healthy": 0,
        "failed": 0
    }


def get_hostname() -> str:
    """Récupère le hostname de la machine"""
    try:
        return socket.gethostname()
    except:
        return "unknown"


def get_local_ip() -> str:
    """Récupère l'adresse IP locale"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "unknown"
    

# ==========================================
# Main
# ==========================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("=" * 60)
    logger.info(f"🚀 Démarrage MediaManager Watcher v{APP_VERSION}")
    logger.info(f"   API: http://{API_HOST}:{API_PORT}")
    logger.info(f"   Admin: http://{API_HOST}:{API_PORT}/admin")
    logger.info(f"   Debug: {API_DEBUG}")
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