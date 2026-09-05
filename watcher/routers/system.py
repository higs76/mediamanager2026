"""
MediaManager 2026 - Router : Système & Administration
Routes depuis app.py : /api/admin/dashboard, /logs, /services/*, /status
Routes depuis api.py : /api/admin/config, /update, /version/check, /purge
"""

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from watcher.database import engine, test_db_connection
from watcher.config import DATABASE_URL, MOUNT_BASE_PATH, LOG_FILE, PROJECT_ROOT
from watcher.utils.versioning import (
    get_app_version, get_git_info, get_latest_github_version, compare_versions
)
from watcher.utils.system_info import (
    get_app_uptime, get_system_boot_time, get_hostname, get_local_ip,
    check_postgres_running, get_mounts_info
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config")
def get_config_all():
    """Retourne toutes les clés de configuration."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT key, value, description FROM config ORDER BY key"
            )).mappings().fetchall()
        return JSONResponse([dict(r) for r in rows])
    except Exception as e:
        logger.error(f"get_config_all: {e}")
        raise HTTPException(500, str(e))


@router.put("/config/{key}")
def update_config(key: str, data: dict = Body(...)):
    """Met à jour une valeur de configuration."""
    value = data.get("value")
    if value is None:
        raise HTTPException(400, "Champ 'value' obligatoire")
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                "UPDATE config SET value = :v WHERE key = :k RETURNING key"
            ), {"v": str(value), "k": key}).fetchone()
            conn.commit()
        if not result:
            raise HTTPException(404, f"Clé '{key}' introuvable")
        return JSONResponse({"success": True, "key": key, "value": str(value)})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"update_config {key}: {e}")
        raise HTTPException(500, str(e))


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/dashboard")
def get_dashboard():
    """Retourne le dashboard complet pour l'Admin Panel."""
    app_version = get_app_version()
    git_info    = get_git_info()
    github_info = get_latest_github_version()
    version_info: dict = {}

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
            version_info = compare_versions(app_version, github_info["version"])
            version_info["latest_url"] = github_info.get("url")
            version_info["prerelease"] = False
        else:
            version_info = {
                "has_update": False,
                "current":    app_version,
                "prerelease": False,
                "error":      github_info.get("error", "")
            }
        latest_version = version_info.get("latest") if version_info.get("has_update") else None

    db_ok            = test_db_connection()
    postgres_running = check_postgres_running()
    mounts_info      = get_mounts_info()

    library_stats: dict = {}
    pg_stats:      dict = {}
    db_size  = "—"
    try:
        with engine.connect() as conn:
            db_row = conn.execute(text(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )).fetchone()
            db_size = db_row[0] if db_row else "—"

            # ── Stats PostgreSQL ──────────────────────────────────────────────
            ver_row = conn.execute(text("SHOW server_version")).fetchone()
            pg_version = (ver_row[0] or "").split(" ")[0] if ver_row else "—"

            conn_row = conn.execute(text(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )).fetchone()
            pg_connections = int(conn_row[0]) if conn_row else 0

            sdb_row = conn.execute(text("""
                SELECT blks_hit, blks_read, xact_commit, xact_rollback, deadlocks
                FROM pg_stat_database WHERE datname = current_database()
            """)).fetchone()
            if sdb_row:
                blks_hit, blks_read = int(sdb_row[0]), int(sdb_row[1])
                total_blks = blks_hit + blks_read
                cache_hit = round(blks_hit * 100.0 / total_blks, 1) if total_blks > 0 else None
                pg_stats = {
                    "version":     pg_version,
                    "connections": pg_connections,
                    "cache_hit":   cache_hit,
                    "commits":     int(sdb_row[2]),
                    "rollbacks":   int(sdb_row[3]),
                    "deadlocks":   int(sdb_row[4]),
                }
            else:
                pg_stats = {"version": pg_version, "connections": pg_connections}

            dead_row = conn.execute(text(
                "SELECT COALESCE(SUM(n_dead_tup),0), COALESCE(SUM(n_live_tup),0) FROM pg_stat_user_tables"
            )).fetchone()
            if dead_row:
                dead, live = int(dead_row[0]), int(dead_row[1])
                pg_stats["dead_tup"] = dead
                pg_stats["bloat_pct"] = round(dead * 100.0 / (dead + live), 1) if (dead + live) > 0 else 0.0

            status_rows = conn.execute(text("""
                SELECT status, disk_status, COUNT(*)
                FROM media_files
                GROUP BY status, disk_status
            """)).fetchall()
            total_files     = sum(r[2] for r in status_rows)
            analyzed_files  = sum(r[2] for r in status_rows if r[0] == 'analyzed')
            missing_files   = sum(r[2] for r in status_rows if r[1] == 'missing')
            duplicate_files = sum(r[2] for r in status_rows if r[1] == 'duplicate')

            size_row = conn.execute(text(
                "SELECT ROUND(SUM(size_bytes)/1099511627776::numeric, 2) FROM media_files"
            )).fetchone()
            total_tb = float(size_row[0] or 0)

            # Retourne total_seconds pour que le frontend utilise formatDuration()
            titles_row = conn.execute(text("""
                SELECT
                    COUNT(DISTINCT SPLIT_PART(path_relative, '/', 1)) as nb_titles,
                    COALESCE(SUM(vm.duration_seconds), 0)               as total_seconds
                FROM media_files mf
                LEFT JOIN video_metadata vm ON vm.file_id = mf.id
                WHERE mf.status = 'analyzed'
            """)).fetchone()
            nb_titles     = int(titles_row[0] or 0)
            total_seconds = int(titles_row[1] or 0)

            trash_row = conn.execute(text(
                "SELECT COALESCE(SUM(size_bytes),0) FROM trash_folders"
            )).fetchone()
            trash_bytes = int(trash_row[0] or 0)

            library_stats = {
                "total_files":     total_files,
                "analyzed_files":  analyzed_files,
                "missing_files":   missing_files,
                "duplicate_files": duplicate_files,
                "total_tb":        total_tb,
                "nb_titles":       nb_titles,
                "total_seconds":   total_seconds,
                "trash_bytes":     trash_bytes,
            }
    except Exception as e:
        logger.warning(f"get_dashboard library_stats: {e}")

    return JSONResponse({
        "version":          app_version,
        "build":            git_info.get("commit", "unknown"),
        "branch":           git_info.get("branch", "unknown"),
        "latest_version":   latest_version,
        "update_available": version_info,
        "timestamp":        datetime.now().isoformat(),
        "services": {
            "watcher": {
                "name":   "Watcher Service",
                "status": "running",
                "uptime": get_app_uptime(),
                "pid":    os.getpid()
            },
            "database": {
                "name":        "PostgreSQL",
                "status":      "connected" if db_ok else "disconnected",
                "type":        f"PostgreSQL {pg_stats.get('version', '—')}",
                "database":    "mediamanager_db",
                "size":        db_size,
                "connections": pg_stats.get("connections"),
                "cache_hit":   pg_stats.get("cache_hit"),
                "deadlocks":   pg_stats.get("deadlocks"),
                "bloat_pct":   pg_stats.get("bloat_pct"),
            },
            "mounts": {
                "name":    "SMB Mounts",
                "status":  "healthy" if mounts_info["healthy"] else "degraded",
                "total":   mounts_info["total"],
                "healthy": mounts_info["healthy"],
                "failed":  mounts_info["failed"]
            }
        },
        "library": library_stats,
        "system": {
            "host":            get_hostname(),
            "ip":              get_local_ip(),
            "start_time":      get_system_boot_time(),
            "mount_base_path": str(MOUNT_BASE_PATH)
        }
    })


# ── Logs ──────────────────────────────────────────────────────────────────────

_LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+\s+-\s+([\w\.]+)\s+-\s+'
    r'(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+-\s+(.*)$'
)


@router.get("/logs")
def get_logs(lines: int = 100, level: str = "", module: str = ""):
    """Retourne les N dernières entrées de log, structurées et filtrables."""
    if not LOG_FILE.exists():
        return JSONResponse({"error": f"Fichier log introuvable : {LOG_FILE}",
                             "logs": [], "modules": []}, status_code=404)
    try:
        raw_lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").split("\n")

        entries: list[dict] = []
        for raw in raw_lines:
            if not raw.strip():
                continue
            m = _LOG_RE.match(raw)
            if m:
                ts_full, mod, lvl, msg = m.groups()
                # DD/MM HH:MM:SS — la date évite de confondre une vieille erreur
                # avec un événement du jour quand on relit les logs plus tard.
                ts = f"{ts_full[8:10]}/{ts_full[5:7]} {ts_full[11:19]}"
                entries.append({
                    "ts":      ts,
                    "level":   lvl,
                    "module":  mod.split(".")[-1],       # watcher.scanner → scanner
                    "message": msg.strip(),
                })
            elif entries:
                entries[-1]["message"] += "\n" + raw    # continuation (traceback)

        modules = sorted({e["module"] for e in entries})

        if level:
            lvl_up = level.upper()
            entries = [e for e in entries if e["level"] == lvl_up]
        if module:
            entries = [e for e in entries if e["module"] == module]

        entries = entries[-lines:] if len(entries) > lines else entries

        return JSONResponse({"logs": entries, "modules": modules})
    except Exception as e:
        logger.error(f"get_logs: {e}")
        return JSONResponse({"error": str(e), "logs": [], "modules": []}, status_code=500)


# ── Services ──────────────────────────────────────────────────────────────────

@router.post("/services/{service}/restart")
def restart_service(service: str):
    """Redémarre un service systemd. Le watcher se redémarre via un thread."""
    if service not in ("watcher", "postgresql"):
        return JSONResponse({"error": f"Service '{service}' non reconnu"}, status_code=400)

    service_name = "mediamanager-watcher" if service == "watcher" else "postgresql"

    try:
        if service == "watcher":
            def do_restart():
                time.sleep(0.5)
                os.kill(os.getpid(), signal.SIGTERM)
            threading.Thread(target=do_restart, daemon=True).start()
            logger.info("Redémarrage du watcher demandé (SIGTERM dans 0.5s)")
            return JSONResponse({
                "status":  "success",
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
        logger.error(f"restart_service {service}: {e}")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.post("/services/{service}/stop")
def stop_service(service: str):
    """Arrête un service systemd (watcher uniquement)."""
    if service not in ("watcher",):
        return JSONResponse({"error": f"Arrêt du service '{service}' non autorisé"},
                            status_code=400)
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "systemctl", "stop", "mediamanager-watcher"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            logger.info("Service mediamanager-watcher arrêté")
            return JSONResponse({"status": "success", "service": service,
                                  "message": f"Service {service} arrêté"})
        else:
            return JSONResponse({"status": "error", "service": service,
                                  "error": result.stderr}, status_code=500)
    except Exception as e:
        logger.error(f"stop_service {service}: {e}")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ── Status (compatibilité) ────────────────────────────────────────────────────

@router.get("/status")
def get_status():
    """Status détaillé — conservé pour compatibilité."""
    db_ok = test_db_connection()
    return JSONResponse({
        "status":  "running" if db_ok else "error",
        "service": "mediamanager-watcher",
        "database": {
            "connected": db_ok,
            "url": DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else "***"
        },
        "mount_base_path": str(MOUNT_BASE_PATH),
    })


# ── Mise à jour application ───────────────────────────────────────────────────

@router.post("/update")
def trigger_update():
    """Lance un git pull + redémarrage du service."""
    results: dict = {}

    try:
        git = "/usr/bin/git"
        if not os.path.exists(git):
            git = shutil.which("git") or "/usr/bin/git"
        r = subprocess.run(
            [git, "pull"],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        )
        output = (r.stdout.strip() or r.stderr.strip()).encode("ascii", "replace").decode("ascii")
        results["git_pull"] = {"success": r.returncode == 0, "output": output}
    except Exception as e:
        results["git_pull"] = {"success": False, "output": str(e)}

    if results["git_pull"]["success"]:
        new_version = None
        try:
            version_file = PROJECT_ROOT / "VERSION"
            if version_file.exists():
                new_version = version_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        try:
            service_src = PROJECT_ROOT / "scripts" / "mediamanager-watcher.service"
            service_dst = "/etc/systemd/system/mediamanager-watcher.service"
            if service_src.exists():
                result = subprocess.run(
                    ["/usr/bin/sudo", "cp", str(service_src), service_dst],
                    capture_output=True, timeout=10
                )
                if result.returncode == 0:
                    subprocess.run(
                        ["/usr/bin/sudo", "systemctl", "daemon-reload"],
                        capture_output=True, timeout=10
                    )
                    results["service_updated"] = True
                    logger.info("Fichier service systemd mis à jour")
        except Exception as e:
            logger.warning(f"Impossible de mettre à jour le service systemd : {e}")
            results["service_updated"] = False

        # Invalider le cache de version GitHub
        if hasattr(get_latest_github_version, "_cache"):
            del get_latest_github_version._cache

        def restart():
            time.sleep(0.8)
            os.kill(os.getpid(), signal.SIGTERM)

        threading.Thread(target=restart, daemon=True).start()
        results["restart"]     = "Redémarrage dans 1 seconde"
        results["new_version"] = new_version
        message = (
            f"Mise à jour vers {new_version} — interface disponible dans quelques secondes"
            if new_version else
            "Mise à jour lancée — interface disponible dans quelques secondes"
        )
    else:
        results["restart"]     = "Redémarrage annulé (git pull échoué)"
        results["new_version"] = None
        message = f"Échec git pull : {results['git_pull']['output']}"

    return JSONResponse({
        "success":     results["git_pull"]["success"],
        "results":     results,
        "new_version": results.get("new_version"),
        "message":     message
    })


# ── Vérification de version ───────────────────────────────────────────────────

@router.get("/version/check")
def force_version_check():
    """Vide le cache de version pour forcer une nouvelle vérification GitHub."""
    try:
        if hasattr(get_latest_github_version, "_cache"):
            del get_latest_github_version._cache
            logger.info("Cache de version invalidé (force check)")
        return JSONResponse({
            "success": True,
            "message": "Cache vidé — prochain appel dashboard retournera la version fraîche"
        })
    except Exception as e:
        logger.error(f"force_version_check: {e}")
        raise HTTPException(500, str(e))


# ── Performances SQL ──────────────────────────────────────────────────────────

@router.get("/perf")
def get_perf(limit: int = 100):
    """Journal des performances SQL — ring buffer en mémoire."""
    from watcher.utils.perf import get_records, get_summary, get_stats
    return JSONResponse({
        "stats":   get_stats(),
        "summary": get_summary(),
        "records": get_records(limit=limit),
    })


@router.delete("/perf")
def clear_perf():
    """Vide le ring buffer des performances SQL."""
    from watcher.utils.perf import clear
    clear()
    return JSONResponse({"success": True, "message": "Journal de performances vidé"})


# ── Purge (développement) ─────────────────────────────────────────────────────

@router.delete("/purge")
def purge_scan_data():
    """Supprime tous les fichiers détectés et l'historique des scans (développement)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE media_files, scan_jobs RESTART IDENTITY CASCADE"))
            conn.commit()
        logger.info("Purge effectuée : media_files + scan_jobs vidés")
        return JSONResponse({"success": True, "message": "Données de scan supprimées"})
    except Exception as e:
        logger.error(f"purge: {e}")
        raise HTTPException(500, str(e))
