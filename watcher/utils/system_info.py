"""
MediaManager 2026 - Utilitaires système

Informations machine, uptime, état PostgreSQL, état des montages.
"""

import logging
import socket
import subprocess
from datetime import datetime, timedelta

from sqlalchemy import text

from watcher.database import engine

logger = logging.getLogger(__name__)

# Heure de démarrage du service (capturée à l'import du module)
SERVICE_START_TIME = datetime.now()


def get_app_uptime() -> str:
    """
    Durée depuis le démarrage du service.
    < 60s   → "42s"
    < 60min → "14min"
    sinon   → "2h05" ou "3 jours 5h07"
    """
    delta         = datetime.now() - SERVICE_START_TIME
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


def get_system_boot_time() -> str:
    """
    Date et heure de démarrage du système (pas du service).
    Lit /proc/uptime pour calculer depuis l'epoch.
    Retourne : "2026-05-28 08:32:14"
    """
    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
        boot_time = datetime.now() - timedelta(seconds=uptime_seconds)
        return boot_time.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "—"


def get_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "unknown"


def check_postgres_running() -> bool:
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "systemctl", "is-active", "postgresql"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def get_mounts_info() -> dict:
    """Récupère les stats des montages depuis la BDD et /proc/mounts."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT local_path FROM mounts WHERE active = true"
            )).fetchall()

        total = len(rows)
        if total == 0:
            return {"name": "Montages", "total": 0, "healthy": 0, "failed": 0}

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
            "failed":  total - healthy,
        }
    except Exception as e:
        logger.warning(f"get_mounts_info: {e}")
        return {"name": "Montages", "total": 0, "healthy": 0, "failed": 0}
