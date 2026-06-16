"""
MediaManager 2026 - Analyseur de fichiers vidéo

Responsabilités :
- Extraction des métadonnées via ffprobe
- Distribution par sessions (dernier niveau de dossier)
- AnalyzeQueue : file de sessions à traiter
"""

import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from watcher.database import engine
from watcher.scanner import get_config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────

def get_analyze_workers() -> int:
    try:
        return max(1, int(get_config("analyze_workers", "2")))
    except ValueError:
        return 2

def get_analyze_session_size() -> int:
    try:
        return max(1, int(get_config("analyze_session_size", "50")))
    except ValueError:
        return 50

def get_analyze_auto() -> bool:
    return get_config("analyze_auto", "true").lower() == "true"


# ─────────────────────────────────────────────────────────────
# FFprobe
# ─────────────────────────────────────────────────────────────

def run_ffprobe(filepath: str) -> dict | None:
    """
    Lance ffprobe sur un fichier et retourne le JSON parsé.
    Retourne None si ffprobe échoue ou si le fichier est inaccessible.
    """
    cmd = [
        "/usr/bin/ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        filepath
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,   # 60s max par fichier
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            logger.warning(f"ffprobe erreur ({result.returncode}) : {filepath}")
            return None
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        logger.warning(f"ffprobe timeout : {filepath}")
        return None
    except Exception as e:
        logger.warning(f"ffprobe exception {filepath} : {e}")
        return None


def parse_ffprobe(data: dict) -> dict:
    """
    Extrait les métadonnées utiles du JSON ffprobe.
    Retourne un dict prêt à insérer dans video_metadata.
    """
    fmt     = data.get("format", {})
    streams = data.get("streams", [])

    # ── Flux vidéo (premier trouvé) ───────────────────────────
    video = next((s for s in streams if s.get("codec_type") == "video"), None)

    video_codec   = None
    video_bitrate = None
    width = height = None
    fps           = None
    hdr_format    = "SDR"
    color_space   = None

    if video:
        video_codec = video.get("codec_name")
        width       = video.get("width")
        height      = video.get("height")
        color_space = video.get("color_space")

        # Bitrate vidéo
        if video.get("bit_rate"):
            try:
                video_bitrate = int(video["bit_rate"])
            except (ValueError, TypeError):
                pass

        # FPS — ffprobe retourne "24000/1001" ou "25/1"
        r_frame = video.get("r_frame_rate", "")
        if "/" in r_frame:
            try:
                num, den = r_frame.split("/")
                if int(den) > 0:
                    fps = round(int(num) / int(den), 3)
            except (ValueError, ZeroDivisionError):
                pass

        # HDR / Dolby Vision
        color_transfer = video.get("color_transfer", "")
        color_primaries = video.get("color_primaries", "")
        side_data = video.get("side_data_list", [])

        dv = any(
            "DOVI" in str(sd.get("side_data_type", "")) or
            "Dolby Vision" in str(sd.get("side_data_type", ""))
            for sd in side_data
        )
        if dv:
            hdr_format = "DV"
        elif color_transfer in ("smpte2084", "arib-std-b67"):
            # smpte2084 = PQ (HDR10/HDR10+), arib-std-b67 = HLG
            # Dolby Vision peut aussi utiliser PQ mais on l'a détecté au-dessus
            if any(
                "HDR10+" in str(sd.get("side_data_type", ""))
                for sd in side_data
            ):
                hdr_format = "HDR10+"
            else:
                hdr_format = "HDR10"
        elif color_transfer == "arib-std-b67":
            hdr_format = "HLG"
        else:
            hdr_format = "SDR"

    # ── Flux audio ────────────────────────────────────────────
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

    audio_codecs   = []
    audio_langs    = []
    audio_channels = []
    audio_layouts  = []

    for a in audio_streams:
        codec = a.get("codec_name", "")
        if codec:
            audio_codecs.append(codec)

        lang = a.get("tags", {}).get("language", "")
        if lang:
            audio_langs.append(lang)

        ch = a.get("channels")
        if ch:
            audio_channels.append(str(ch))

        layout = a.get("channel_layout", "")
        if layout:
            audio_layouts.append(layout)

    # ── Flux sous-titres ──────────────────────────────────────
    sub_streams = [s for s in streams if s.get("codec_type") == "subtitle"]
    sub_langs   = []
    for s in sub_streams:
        lang = s.get("tags", {}).get("language", "")
        if lang:
            sub_langs.append(lang)

    # ── Format global ─────────────────────────────────────────
    duration = None
    if fmt.get("duration"):
        try:
            duration = float(fmt["duration"])
        except (ValueError, TypeError):
            pass

    container = fmt.get("format_name", "")
    # ffprobe retourne parfois "matroska,webm" → on garde le premier
    if "," in container:
        container = container.split(",")[0]

    return {
        "duration_seconds":      duration,
        "video_codec":           video_codec,
        "video_bitrate":         video_bitrate,
        "video_width":           width,
        "video_height":          height,
        "video_fps":             fps,
        "audio_codecs":          ";".join(audio_codecs)  or None,
        "audio_languages":       ";".join(audio_langs)   or None,
        "audio_channels":        ";".join(audio_channels) or None,
        "audio_channel_layouts": ";".join(audio_layouts) or None,
        "subtitle_languages":    ";".join(sub_langs)     or None,
        "subtitle_count":        len(sub_streams),
        "container_format":      container or None,
        "hdr_format":            hdr_format,
        "color_space":           color_space,
    }


# ─────────────────────────────────────────────────────────────
# Analyse d'un fichier
# ─────────────────────────────────────────────────────────────

def analyze_file(file_id: int, filepath: str) -> bool:
    """
    Analyse un fichier et insère/met à jour video_metadata.
    Retourne True si succès, False sinon.
    """
    data = run_ffprobe(filepath)
    if data is None:
        return False

    meta = parse_ffprobe(data)
    meta["file_id"]            = file_id
    meta["file_path_snapshot"] = filepath

    try:
        with engine.connect() as conn:
            # Upsert : si déjà analysé (re-analyse), on met à jour
            existing = conn.execute(text(
                "SELECT id FROM video_metadata WHERE file_id = :fid"
            ), {"fid": file_id}).fetchone()

            if existing:
                conn.execute(text("""
                    UPDATE video_metadata SET
                        duration_seconds      = :duration_seconds,
                        video_codec           = :video_codec,
                        video_bitrate         = :video_bitrate,
                        video_width           = :video_width,
                        video_height          = :video_height,
                        video_fps             = :video_fps,
                        audio_codecs          = :audio_codecs,
                        audio_languages       = :audio_languages,
                        audio_channels        = :audio_channels,
                        audio_channel_layouts = :audio_channel_layouts,
                        subtitle_languages    = :subtitle_languages,
                        subtitle_count        = :subtitle_count,
                        container_format      = :container_format,
                        hdr_format            = :hdr_format,
                        color_space           = :color_space,
                        file_path_snapshot    = :file_path_snapshot,
                        analyzed_at           = NOW()
                    WHERE file_id = :file_id
                """), meta)
            else:
                conn.execute(text("""
                    INSERT INTO video_metadata (
                        file_id, duration_seconds, video_codec,
                        video_bitrate, video_width, video_height, video_fps,
                        audio_codecs, audio_languages, audio_channels,
                        audio_channel_layouts, subtitle_languages,
                        subtitle_count, container_format, hdr_format,
                        color_space, file_path_snapshot
                    ) VALUES (
                        :file_id, :duration_seconds, :video_codec,
                        :video_bitrate, :video_width, :video_height, :video_fps,
                        :audio_codecs, :audio_languages, :audio_channels,
                        :audio_channel_layouts, :subtitle_languages,
                        :subtitle_count, :container_format, :hdr_format,
                        :color_space, :file_path_snapshot
                    )
                """), meta)

            # Marquer le fichier comme analysé
            conn.execute(text("""
                UPDATE media_files SET status = 'analyzed' WHERE id = :id
            """), {"id": file_id})

            conn.commit()
        return True

    except Exception as e:
        logger.error(f"analyze_file {file_id} : {e}")
        return False


# ─────────────────────────────────────────────────────────────
# Distributeur de sessions
# ─────────────────────────────────────────────────────────────

def create_analyze_sessions() -> int:
    """
    Crée les sessions d'analyse manquantes pour tous les fichiers
    avec status='new', groupés par dernier niveau de dossier.
    Retourne le nombre de sessions créées.
    """
    created = 0
    try:
        with engine.connect() as conn:
            # Récupérer tous les fichiers 'new' avec leur dossier
            rows = conn.execute(text("""
                SELECT id, mount_id, path_relative
                FROM media_files
                WHERE status = 'discovered'
                ORDER BY mount_id, path_relative
            """)).fetchall()

            if not rows:
                return 0

            # Grouper par (mount_id, dernier dossier)
            groups: dict[tuple, list[int]] = {}
            for file_id, mount_id, path_rel in rows:
                folder = str(Path(path_rel).parent)
                key    = (mount_id, folder)
                groups.setdefault(key, []).append(file_id)

            session_size = get_analyze_session_size()

            for (mount_id, folder), file_ids in groups.items():
                # Découper en sous-sessions si trop grand
                for i in range(0, len(file_ids), session_size):
                    batch = file_ids[i:i + session_size]

                    row = conn.execute(text("""
                        INSERT INTO analyze_sessions
                            (mount_id, folder_path, files_total, status)
                        VALUES (:mid, :folder, :total, 'pending')
                        RETURNING id
                    """), {
                        "mid":    mount_id,
                        "folder": folder,
                        "total":  len(batch),
                    }).fetchone()

                    session_id = row[0]

                    # Lier les fichiers à la session via une table temporaire
                    # On stocke les IDs dans un champ JSON pour rester simple
                    conn.execute(text("""
                        UPDATE analyze_sessions
                        SET error_message = :ids
                        WHERE id = :sid
                    """), {
                        "ids": json.dumps(batch),
                        "sid": session_id,
                    })
                    created += 1

            conn.commit()

    except Exception as e:
        logger.error(f"create_analyze_sessions: {e}")

    return created


# ─────────────────────────────────────────────────────────────
# Traitement d'une session
# ─────────────────────────────────────────────────────────────

def process_session(session_id: int):
    """
    Traite une session d'analyse : analyse tous ses fichiers
    en parallèle (selon analyze_workers), met à jour les compteurs.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT mount_id, folder_path, error_message
                FROM analyze_sessions WHERE id = :sid
            """), {"sid": session_id}).fetchone()

            if not row:
                return

            mount_id    = row[0]
            folder_path = row[1]
            file_ids    = json.loads(row[2] or "[]")

            # Récupérer local_path du montage
            m_row = conn.execute(text(
                "SELECT local_path FROM mounts WHERE id = :id"
            ), {"id": mount_id}).fetchone()
            mount_path = m_row[0] if m_row else ""

        if not file_ids:
            _update_session(session_id, "done", 0, 0)
            return

        logger.info(
            f"Session {session_id} — {folder_path} "
            f"({len(file_ids)} fichiers)"
        )
        _update_session(session_id, "running", started_at=datetime.now())

        done_count  = 0
        error_count = 0
        workers     = get_analyze_workers()

        def _task(file_id: int):
            """Tâche unitaire : récupère le chemin et analyse."""
            try:
                with engine.connect() as c:
                    r = c.execute(text(
                        "SELECT path_relative FROM media_files WHERE id = :id"
                    ), {"id": file_id}).fetchone()
                if not r:
                    return False
                # Marquer comme en cours d'analyse
                with engine.connect() as c:
                    c.execute(text(
                        "UPDATE media_files SET status = 'analyzing' WHERE id = :id"
                    ), {"id": file_id})
                    c.commit()
                full_path = os.path.join(mount_path, r[0])
                ok = analyze_file(file_id, full_path)
                if not ok:
                    # Remettre en discovered si erreur
                    with engine.connect() as c:
                        c.execute(text(
                            "UPDATE media_files SET status = 'discovered' WHERE id = :id"
                        ), {"id": file_id})
                        c.commit()
                return ok
            except Exception as e:
                logger.error(f"_task {file_id}: {e}")
                return False

        # Analyse en parallèle
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_task, fid): fid for fid in file_ids}
            for future in as_completed(futures):
                if future.result():
                    done_count  += 1
                else:
                    error_count += 1
                # Mise à jour progressive en BDD
                _update_session(
                    session_id, "running",
                    files_done=done_count,
                    files_error=error_count,
                )

        status = "done" if error_count == 0 else "error"
        _update_session(
            session_id, status,
            files_done=done_count,
            files_error=error_count,
            finished_at=datetime.now(),
            # Effacer la liste des IDs du champ error_message si succès
            error_message=None if status == "done" else f"{error_count} erreur(s)",
        )
        logger.info(
            f"Session {session_id} terminée — "
            f"{done_count} OK, {error_count} erreurs"
        )

    except Exception as e:
        logger.error(f"process_session {session_id}: {e}")
        _update_session(session_id, "error", error_message=str(e))


def _update_session(session_id: int, status: str, **kwargs):
    """Met à jour une session avec les champs fournis."""
    kwargs["status"] = status
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    kwargs["sid"] = session_id
    try:
        with engine.connect() as conn:
            conn.execute(
                text(f"UPDATE analyze_sessions SET {set_parts} WHERE id = :sid"),
                kwargs
            )
            conn.commit()
    except Exception as e:
        logger.error(f"_update_session {session_id}: {e}")


# ─────────────────────────────────────────────────────────────
# File d'analyse
# ─────────────────────────────────────────────────────────────

class AnalyzeQueue:
    """
    File de sessions d'analyse.
    - Crée les sessions depuis les fichiers 'new'
    - Traite les sessions pending une par une
    - Tourne en thread daemon
    """

    def __init__(self):
        self._event   = threading.Event()
        self._thread  = None
        self._running = False

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._worker, daemon=True, name="AnalyzeQueueWorker"
        )
        self._thread.start()
        logger.info("AnalyzeQueue démarrée")

    def stop(self):
        self._running = False
        self._event.set()

    def trigger(self):
        """
        Déclenche une création de sessions + traitement.
        Appelé après un scan ou manuellement.
        """
        self._event.set()

    def _worker(self):
        """Boucle principale."""
        time.sleep(5)  # Attendre que la BDD soit prête

        while self._running:
            if not get_analyze_auto():
                # Analyse auto désactivée → attendre un trigger manuel
                self._event.wait(timeout=60)
                self._event.clear()
                continue

            # Créer les sessions manquantes
            nb = create_analyze_sessions()
            if nb > 0:
                logger.info(f"AnalyzeQueue : {nb} nouvelle(s) session(s) créée(s)")

            # Traiter toutes les sessions pending
            while self._running:
                session_id = self._next_pending_session()
                if session_id is None:
                    break
                process_session(session_id)
                time.sleep(0.5)  # Petite pause entre sessions

            # Déclencher le catalogueur quand l'analyse est terminée
            if not self._running:
                break
            try:
                from watcher.cataloger import run_cataloger
                run_cataloger()
            except Exception as e:
                logger.error(f"Catalogueur: {e}")

            # Attendre le prochain trigger (scan terminé, etc.)
            # ou timeout de 30 min pour re-vérifier
            self._event.wait(timeout=1800)
            self._event.clear()

        

    def _next_pending_session(self) -> int | None:
        """Retourne l'ID de la prochaine session pending, ou None."""
        try:
            with engine.connect() as conn:
                row = conn.execute(text("""
                    SELECT id FROM analyze_sessions
                    WHERE status = 'pending'
                    ORDER BY created_at
                    LIMIT 1
                """)).fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"_next_pending_session: {e}")
            return None


# Instance globale
analyze_queue = AnalyzeQueue()