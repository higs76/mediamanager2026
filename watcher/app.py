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
# Heure de démarrage de l'app (pour uptime)
APP_START_TIME = datetime.now()

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
            ["/usr/bin/sudo", apt, "install", "-y", "-qq"] + packages_needed,
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
    # Démarrer la file de scans en arrière-plan
    from watcher.scanner import scan_queue
    scan_queue.start()
    from watcher.analyzer import analyze_queue
    analyze_queue.start()
    # Scanner tous les montages actifs au démarrage
    scan_queue.enqueue_all_active()
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
    """Retourne le dashboard complet pour l'Admin Panel."""

    # Infos git (branche + hash commit local)
    git_info = get_git_info()

    # Version GitHub — mode dev (hash) ou prod (release)
    github_info  = get_latest_github_version()
    version_info = {}

    if github_info.get("mode") == "dev":
        version_info = {
            "has_update": github_info.get("has_update", False),
            "current":    git_info.get("commit", "unknown"),
            "latest":     github_info.get("commit"),
            "mode":       "dev",
            "prerelease": True,
            "message":    github_info.get("message", ""),
        }
        latest_version = github_info.get("commit") if github_info.get("has_update") else None
    else:
        if github_info.get("error") is None and github_info.get("version"):
            version_info = compare_versions(APP_VERSION, github_info["version"])
            version_info["latest_url"]  = github_info.get("url")
            version_info["prerelease"]  = False
        else:
            version_info = {
                "has_update": False,
                "current":    APP_VERSION,
                "prerelease": False,
                "error":      github_info.get("error", "")
            }
        latest_version = version_info.get("latest") if version_info.get("has_update") else None

    # Test connexion BD
    db_ok = test_db_connection()

    # Statut watcher — si on reçoit la requête, il tourne
    watcher_running = True

    # Statut PostgreSQL
    postgres_running = check_postgres_running()

    # Statut montages
    mounts_info = get_mounts_info()

    
    return JSONResponse({
        "version":        APP_VERSION,
        "build":          git_info.get("commit", "unknown"),
        "branch":         git_info.get("branch", "unknown"),
        "latest_version": latest_version,
        "update_available": version_info,
        "timestamp": datetime.now().isoformat(),
        "services": {
            "watcher": {
                "name": "Watcher Service",
                "status": "running" if watcher_running else "stopped",
                "uptime": get_app_uptime(),
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
            "start_time": get_system_boot_time(),
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
    """Redémarre un service systemd. Le watcher se redémarre via un thread."""
    if service not in ["watcher", "postgresql"]:
        return JSONResponse({"error": f"Service '{service}' non reconnu"}, status_code=400)
 
    service_name = "mediamanager-watcher" if service == "watcher" else "postgresql"
 
    try:
        if service == "watcher":
            # Le watcher ne peut pas se tuer et répondre en même temps.
            # On répond d'abord, puis on envoie SIGTERM dans un thread.
            # systemd détecte l'arrêt et redémarre automatiquement (Restart=on-failure).
            import threading, time, os, signal
 
            def do_restart():
                time.sleep(0.5)
                os.kill(os.getpid(), signal.SIGTERM)
 
            threading.Thread(target=do_restart, daemon=True).start()
            logger.info("Redémarrage du watcher demandé (SIGTERM dans 0.5s)")
            return JSONResponse({
                "status": "success",
                "service": service,
                "message": "Redémarrage en cours — service disponible dans quelques secondes"
            })
        else:
            result = subprocess.run(
                ["/usr/bin/sudo", "systemctl", "restart", service_name],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                logger.info(f"Service {service_name} redémarré")
                return JSONResponse({"status": "success", "service": service,
                                     "message": f"Service {service} redémarré"})
            else:
                return JSONResponse({"status": "error", "error": result.stderr},
                                    status_code=500)
    except Exception as e:
        logger.error(f"Exception restart {service}: {e}")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)

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
            ["/usr/bin/sudo", "systemctl", "stop", service_name],
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

def get_git_info() -> dict:
    """
    Recupere la branche courante et le hash court du commit.
    Permet de distinguer le mode dev (branche dev) du mode prod (branche main).
    Retourne: {"branch": "main"|"dev"|..., "commit": "a1b2c3d"}
    """
    try:
        branch = subprocess.run(
            ["/usr/bin/git", "branch", "--show-current"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=5
        ).stdout.strip() or "unknown"
 
        commit = subprocess.run(
            ["/usr/bin/git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=5
        ).stdout.strip() or "unknown"
 
        return {"branch": branch, "commit": commit}
    except Exception:
        return {"branch": "unknown", "commit": "unknown"}

def get_latest_github_version() -> dict:
    """
        Recupere la derniere version disponible depuis GitHub.
    
        Selon ALLOW_PRERELEASE dans le .env :
        false (defaut) : interroge /releases/latest
                        retourne uniquement la derniere release STABLE
                        Les utilisateurs finaux ne voient jamais les versions -dev
        true           : interroge /releases et prend la toute derniere
                        (stable OU pre-release)
                        Reservé au developpeur dans son .env
    
        Resultat mis en cache 30 minutes.
        """
    import time
    from watcher.config import IS_DEV
 
    cache = getattr(get_latest_github_version, "_cache", None)
    if cache and (time.time() - cache["ts"]) < 1800:
        return cache["data"]
 
    headers = {"Accept": "application/vnd.github.v3+json"}
    repo    = "higs76/mediamanager2026"
 
    try:
        if IS_DEV:
            # Toutes les releases (stables + pre-releases) — developpeur uniquement
            url      = f"https://api.github.com/repos/{repo}/releases?per_page=1"
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                releases = response.json()
                if releases:
                    data   = releases[0]
                    result = {
                        "version":      data.get("tag_name", "").lstrip("v"),
                        "url":          data.get("html_url"),
                        "published_at": data.get("published_at"),
                        "prerelease":   data.get("prerelease", False),
                        "error":        None
                    }
                else:
                    result = {"version": None, "url": None, "prerelease": False,
                              "error": "Aucune release publiee sur GitHub"}
            else:
                result = {"version": None, "url": None, "prerelease": False,
                          "error": f"GitHub API: HTTP {response.status_code}"}
        else:
            # Releases stables uniquement — utilisateurs finaux
            url      = f"https://api.github.com/repos/{repo}/releases/latest"
            response = requests.get(url, headers=headers, timeout=5)
            if response.status_code == 200:
                data   = response.json()
                result = {
                    "version":      data.get("tag_name", "").lstrip("v"),
                    "url":          data.get("html_url"),
                    "published_at": data.get("published_at"),
                    "prerelease":   False,
                    "error":        None
                }
            elif response.status_code == 404:
                result = {"version": None, "url": None, "prerelease": False,
                          "error": "Aucune release stable publiee sur GitHub"}
            else:
                result = {"version": None, "url": None, "prerelease": False,
                          "error": f"GitHub API: HTTP {response.status_code}"}
 
    except Exception as e:
        result = {"version": None, "url": None, "prerelease": False, "error": str(e)}
 
    get_latest_github_version._cache = {"ts": time.time(), "data": result}
    return result
    
def compare_versions(current: str, latest: str) -> dict:
    """
    Compare deux versions et retourne l'info de mise a jour.
 
    N'utilise PAS packaging.version car il normalise les versions custom :
      "0.3.2-dev" → "0.3.2.dev0"  ← indésirable
 
    Comparaison manuelle sur les parties numeriques uniquement.
    Le suffixe (-dev, -beta, -rc) est ignore pour la comparaison
    mais conserve tel quel dans les champs retournes.
    """
    def _numeric_parts(v: str) -> tuple:
        # Retirer le prefixe "v" eventuel et tout ce qui suit le premier tiret
        # "0.3.2-dev" → (0, 3, 2)  /  "v1.2.0" → (1, 2, 0)
        clean = v.lstrip("v").split("-")[0].split(".")
        try:
            return tuple(int(x) for x in clean)
        except ValueError:
            return (0,)
 
    try:
        current_parts = _numeric_parts(current)
        latest_parts  = _numeric_parts(latest)
        has_update    = latest_parts > current_parts
 
        return {
            "has_update":  has_update,
            "current":     current,   # conserve le format original
            "latest":      latest,    # conserve le format original
            "message":     f"Update available: {current} → {latest}" if has_update else "You are up to date",
            "latest_url":  None       # sera rempli par l'appelant si besoin
        }
    except Exception as e:
        return {
            "has_update": False,
            "current":    current,
            "latest":     latest,
            "error":      str(e)
        }

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def check_postgres_running() -> bool:
    """Vérifie si PostgreSQL tourne"""
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "systemctl", "is-active", "postgresql"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False


def get_mounts_info() -> dict:
    """Récupère les stats réelles des montages depuis la BDD et /proc/mounts."""
    try:
        from watcher.database import engine
        from sqlalchemy import text
 
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT local_path FROM mounts WHERE active = true"
            )).fetchall()
 
        total = len(rows)
        if total == 0:
            return {"total": 0, "healthy": 0, "failed": 0, "name": "Montages"}
 
        # Lire /proc/mounts pour savoir ce qui est réellement monté
        mounted = set()
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] in ("cifs", "nfs", "nfs4"):
                        mounted.add(parts[1])
        except Exception:
            pass
 
        healthy = sum(1 for r in rows if r[0] in mounted)
        return {
            "name":    "Montages",
            "total":   total,
            "healthy": healthy,
            "failed":  total - healthy
        }
    except Exception as e:
        logger.warning(f"get_mounts_info: {e}")
        return {"total": 0, "healthy": 0, "failed": 0, "name": "Montages"}


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
    

def get_system_boot_time() -> str:
    """
    Date et heure de demarrage du systeme (pas de l'app).
    Lit /proc/uptime pour calculer depuis l'epoch.
    Retourne : "2026-05-28 08:32:14"
    """
    try:
        import datetime as dt
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
        boot_time = datetime.now() - dt.timedelta(seconds=uptime_seconds)
        return boot_time.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"
 
 
def get_app_uptime() -> str:
    """
    Duree depuis le demarrage de l'application.
    < 60s   → "42s"
    < 60min → "14min"
    sinon   → "2h05" ou "3 jours 5h07"
    """
    delta         = datetime.now() - APP_START_TIME
    total_seconds = int(delta.total_seconds())
    days    = total_seconds // 86400
    hours   = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
 
    if total_seconds < 60:
        return f"{seconds}s"
    elif total_seconds < 3600:
        return f"{minutes}min"
    elif days > 0:
        return f"{days} jours {hours}h{minutes:02d}"
    else:
        return f"{hours}h{minutes:02d}"

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