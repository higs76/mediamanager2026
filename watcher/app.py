"""
Point d'entrée principal du Watcher MediaManager

Responsabilités :
- Cycle de vie FastAPI (lifespan, queues, init BDD)
- Middleware CORS
- Montage des fichiers statiques (admin, app)
- Endpoint /health
- Inclusion du router admin (watcher.api)
"""

import logging
import logging.handlers
import sys
import os
import subprocess

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager

from watcher.config import (
    API_HOST, API_PORT, API_DEBUG, PROJECT_ROOT, LOG_LEVEL, LOG_FILE, LOG_RETENTION_DAYS,
)
from watcher.database import engine
from watcher.api import router as admin_router
from watcher.routers.auth import router as auth_router
from watcher.utils.versioning import get_app_version
from sqlalchemy import text

# ==========================================
# Configuration Logging
# ==========================================
_file_handler = logging.handlers.TimedRotatingFileHandler(
    LOG_FILE, when='midnight', backupCount=LOG_RETENTION_DAYS, encoding='utf-8'
)
logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        _file_handler,
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# ==========================================
# Init BDD au démarrage
# ==========================================
def init_database_tables():
    """
    1. Exécute database/schema.sql (structure, idempotent)
    2. Applique les migrations non encore exécutées depuis database/migrations/
       Chaque migration est tracée dans la table schema_migrations.
    """
    import psycopg2
    from watcher.config import DATABASE_URL

    def _get_conn():
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        conn.set_client_encoding('UTF8')
        return conn

    schema_file = PROJECT_ROOT / 'database' / 'schema.sql'
    if not schema_file.exists():
        logger.warning(f"⚠ schema.sql non trouvé : {schema_file}")
        return
    try:
        sql = schema_file.read_text(encoding='utf-8')
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.close()
        logger.info("✓ Tables BDD vérifiées / créées")
    except Exception as e:
        logger.error(f"✗ Erreur init tables : {e}")
        return

    migrations_dir = PROJECT_ROOT / 'database' / 'migrations'
    if not migrations_dir.exists():
        return

    migration_files = sorted(migrations_dir.glob('*.sql'))
    if not migration_files:
        return

    try:
        conn = _get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

        for mf in migration_files:
            version = mf.stem
            if version in applied:
                logger.debug(f"Migration {version} déjà appliquée")
                continue
            logger.info(f"Application migration : {version}")
            try:
                sql = mf.read_text(encoding='utf-8')
                with conn.cursor() as cur:
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,)
                    )
                logger.info(f"✓ Migration {version} appliquée")
            except Exception as e:
                logger.error(f"✗ Erreur migration {version} : {e}")

        conn.close()
    except Exception as e:
        logger.error(f"✗ Erreur système migrations : {e}")


def ensure_system_dependencies():
    """Installe silencieusement les dépendances système manquantes (smbclient, nfs-common, cifs-utils)."""
    import shutil

    packages_needed = []
    if not shutil.which("smbclient"):
        packages_needed.append("smbclient")
    if not shutil.which("showmount"):
        packages_needed.append("nfs-common")
    if not shutil.which("mount.cifs"):
        packages_needed.append("cifs-utils")

    if not packages_needed:
        logger.info("✓ Dépendances système OK")
        return

    logger.info(f"Installation des dépendances manquantes : {', '.join(packages_needed)}")
    try:
        apt = "/usr/bin/apt-get"
        if not os.path.exists(apt):
            apt = shutil.which("apt-get") or "/usr/bin/apt-get"
        subprocess.run(
            ["/usr/bin/sudo", apt, "install", "-y", "-qq"] + packages_needed,
            capture_output=True, text=True, timeout=120
        )
        logger.info(f"✓ Dépendances installées : {', '.join(packages_needed)}")
    except Exception as e:
        logger.warning(f"⚠ Impossible d'installer les dépendances : {e}")


def ensure_timezone():
    """Configure le fuseau horaire Europe/Paris si le système est en UTC."""
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
    """Cycle de vie : démarrage → queues → arrêt propre."""
    app_version = get_app_version()
    logger.info("=" * 60)
    logger.info(f"🚀 Démarrage MediaManager Watcher v{app_version}")
    logger.info(f"   API: http://{API_HOST}:{API_PORT}")
    logger.info(f"   Admin: http://{API_HOST}:{API_PORT}/admin")
    logger.info("=" * 60)
    ensure_timezone()
    ensure_system_dependencies()
    init_database_tables()

    from watcher.auth import init_setup_flag
    init_setup_flag()

    # Nettoyage des jobs interrompus par un redémarrage brutal
    try:
        with engine.connect() as conn:
            r1 = conn.execute(text("""
                UPDATE scan_jobs
                SET status = 'error',
                    error_message = 'Interrompu par redémarrage',
                    finished_at = NOW()
                WHERE status = 'running'
            """))
            r2 = conn.execute(text("""
                UPDATE analyze_sessions
                SET status = 'pending',
                    started_at = NULL,
                    files_done = 0
                WHERE status = 'running'
            """))
            r3 = conn.execute(text("""
                UPDATE media_files
                SET status = 'discovered'
                WHERE status = 'analyzing'
            """))
            conn.commit()
            if r1.rowcount: logger.info(f"↺ {r1.rowcount} scan(s) interrompu(s) marqués en erreur")
            if r2.rowcount: logger.info(f"↺ {r2.rowcount} session(s) d'analyse remises en pending")
            if r3.rowcount: logger.info(f"↺ {r3.rowcount} fichier(s) remis en discovered")
    except Exception as e:
        logger.warning(f"Nettoyage jobs interrompus : {e}")

    from watcher.scanner import scan_queue
    scan_queue.start()
    from watcher.analyzer import analyze_queue
    analyze_queue.start()
    from watcher.cataloger import catalog_queue
    catalog_queue.start()
    scan_queue.enqueue_all_active()

    from watcher.routers.mounts import remount_all_active, mount_watchdog
    result = remount_all_active()
    if result["added"]:
        logger.info(f"✓ {len(result['added'])} montage(s) restauré(s) au démarrage")
    if result["errors"]:
        logger.warning(f"⚠ {len(result['errors'])} montage(s) inaccessible(s) au démarrage")
    mount_watchdog.start()

    yield

    logger.info("Arrêt du service MediaManager Watcher")
    try:
        mount_watchdog.stop()
        scan_queue.stop()
        analyze_queue.stop()
        catalog_queue.stop()
        logger.info("✓ Queues et watchdog arrêtés proprement")
    except Exception as e:
        logger.warning(f"Arrêt queues : {e}")


# ==========================================
# Application FastAPI
# ==========================================
class AuthMiddleware(BaseHTTPMiddleware):
    """Protège toutes les routes sauf login/setup/auth-api/health."""
    _PUBLIC = ("/login", "/setup", "/api/auth", "/health")

    async def dispatch(self, request, call_next):
        path = request.url.path

        # Routes publiques — passe directement
        if any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in self._PUBLIC):
            return await call_next(request)

        from watcher.auth import decode_session, COOKIE_NAME, is_setup_needed
        token = request.cookies.get(COOKIE_NAME)
        user  = decode_session(token) if token else None

        if user is None:
            # API → 401 JSON ; pages HTML → redirect
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Non authentifié"}, status_code=401)
            if is_setup_needed():
                return RedirectResponse("/setup", status_code=302)
            return RedirectResponse("/login", status_code=302)

        # /admin/* réservé aux admins
        if path.startswith("/admin") and user.get("role") != "admin":
            return RedirectResponse("/app/", status_code=302)

        request.state.user = user
        return await call_next(request)


app = FastAPI(
    title="MediaManager Watcher",
    description="Service de surveillance des fichiers vidéo",
    version=get_app_version(),
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)

app.include_router(auth_router)
app.include_router(admin_router)

# Pages auth (publiques)
for _name, _dir, _path in [
    ("login", "login", "/login"),
    ("setup", "setup", "/setup"),
]:
    _p = PROJECT_ROOT / "frontend" / _dir
    if _p.exists():
        app.mount(_path, StaticFiles(directory=str(_p), html=True), name=_name)
        logger.info(f"✓ {_name} frontend mounted at {_path}")

# Frontend Admin
static_path = PROJECT_ROOT / "frontend" / "admin"
if static_path.exists():
    app.mount("/admin", StaticFiles(directory=str(static_path), html=True), name="admin")
    logger.info(f"✓ Admin frontend mounted at /admin → {static_path}")
else:
    logger.warning(f"⚠ Admin frontend not found at {static_path}")

@app.get("/admin")
def admin_redirect():
    return RedirectResponse(url="/admin/", status_code=307)

# Frontend App utilisateur
app_path = PROJECT_ROOT / "frontend" / "app"
if app_path.exists():
    app.mount("/app", StaticFiles(directory=str(app_path), html=True), name="app")
    logger.info(f"✓ App frontend mounted at /app → {app_path}")
else:
    logger.warning(f"⚠ App frontend not found at {app_path}")

@app.get("/app")
def app_redirect():
    return RedirectResponse(url="/app/", status_code=307)


@app.get("/health")
def health_check():
    return JSONResponse({
        "status":  "ok",
        "service": "mediamanager-watcher",
        "version": get_app_version()
    })


# ==========================================
# Main
# ==========================================
if __name__ == "__main__":
    import uvicorn

    app_version = get_app_version()
    logger.info("=" * 60)
    logger.info(f"🚀 Démarrage MediaManager Watcher v{app_version}")
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
