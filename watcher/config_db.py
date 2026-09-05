"""
MediaManager 2026 - Config dynamique en base de données

Fonctions de lecture de la table `config` (clé/valeur).
Partagées par scanner, analyzer et cataloger.
"""

import logging

from sqlalchemy import text
from watcher.database import engine

logger = logging.getLogger(__name__)


def get_config(key: str, default: str = "") -> str:
    """Lit une valeur de config en base. Retourne default si absente."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT value FROM config WHERE key = :k"),
                {"k": key}
            ).fetchone()
        return row[0] if row else default
    except Exception as e:
        logger.warning(f"get_config({key}): {e}")
        return default


def get_video_extensions() -> set:
    """
    Retourne l'ensemble des extensions vidéo autorisées.
    Ex: {'.mkv', '.mp4', '.avi', ...}
    """
    raw = get_config("video_extensions", ".mkv;.mp4;.avi;.mov;.wmv")
    return {ext.strip().lower() for ext in raw.split(";") if ext.strip()}


def get_scan_interval_hours() -> float:
    """Retourne l'intervalle de scan périodique en heures."""
    try:
        return float(get_config("scan_interval_hours", "6"))
    except ValueError:
        return 6.0


def get_ignored_scan_dirs() -> set:
    """Noms de dossiers à ignorer complètement du scan (ni scannés, ni mesurés).
    Insensible à la casse. Vide par défaut — ex: dossiers de test."""
    raw = get_config("scan_excluded_dirs", "")
    return {d.strip().lower() for d in raw.split(",") if d.strip()}


def get_trash_scan_dirs() -> set:
    """Noms de dossiers reconnus comme corbeilles NAS : mesurés (taille + nb fichiers,
    espace récupérable) mais jamais catalogués. Insensible à la casse.
    Défaut : corbeilles Synology, Windows, Linux."""
    raw = get_config(
        "scan_trash_dirs",
        "#recycle,@Recycle,#snapshot,eaRecycleBin,@sharebin,.Trash-1000,$RECYCLE.BIN,RECYCLER",
    )
    return {d.strip().lower() for d in raw.split(",") if d.strip()}
