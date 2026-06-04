"""
MediaManager 2026 - Scanner de fichiers

Responsabilités :
- Calcul du hash partiel (début + fin du fichier)
- Scan d'un montage : découverte et classification des fichiers
- ScanQueue : file d'attente des scans à effectuer
"""

import hashlib
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from watcher.database import engine

logger = logging.getLogger(__name__)

# Taille des blocs lus pour le hash (512 Ko)
HASH_BLOCK_SIZE = 512 * 1024


# ─────────────────────────────────────────────────────────────
# Lecture de la config en base
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Hash partiel
# ─────────────────────────────────────────────────────────────

def compute_partial_hash(filepath: str) -> str | None:
    """
    Calcule un hash SHA-256 partiel d'un fichier.

    Stratégie :
    - Lit les 512 premiers Ko du fichier
    - Lit les 512 derniers Ko du fichier
    - Inclut la taille exacte du fichier
    - Hache l'ensemble en SHA-256

    Si le fichier fait moins de 1 Mo, il est lu en entier.
    Retourne None en cas d'erreur (fichier inaccessible, en cours de copie...).
    """
    try:
        file_size = os.path.getsize(filepath)

        # Sécurité : fichier vide ou en cours de création
        if file_size == 0:
            logger.debug(f"Fichier vide ignoré : {filepath}")
            return None

        h = hashlib.sha256()

        # On inclut la taille dans le hash
        # → deux fichiers avec même début/fin mais tailles différentes = hash différent
        h.update(file_size.to_bytes(8, byteorder="big"))

        with open(filepath, "rb") as f:
            if file_size <= HASH_BLOCK_SIZE * 2:
                # Fichier petit : on lit tout
                h.update(f.read())
            else:
                # Fichier grand : début + fin
                h.update(f.read(HASH_BLOCK_SIZE))
                f.seek(-HASH_BLOCK_SIZE, 2)   # 2 = depuis la fin du fichier
                h.update(f.read(HASH_BLOCK_SIZE))

        return h.hexdigest()

    except PermissionError:
        logger.warning(f"Accès refusé : {filepath}")
        return None
    except OSError as e:
        logger.warning(f"Erreur lecture {filepath} : {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Scan d'un montage
# ─────────────────────────────────────────────────────────────

def scan_mount(mount_id: int, job_id: int) -> dict:
    """
    Parcourt tous les fichiers vidéo d'un montage et met à jour media_files.

    Logique pour chaque fichier trouvé sur disque :
      - Hash inconnu               → INSERT  (nouveau fichier)
      - Hash connu, même chemin    → UPDATE last_seen_at seulement
      - Hash connu, chemin différent → UPDATE chemin (renommage/déplacement)
      - Hash connu, mount différent  → status = duplicate

    À la fin du scan :
      - Fichiers en base non revus → status = missing

    Retourne un dict avec les compteurs.
    """
    counters = {
        "files_found":   0,
        "files_new":     0,
        "files_updated": 0,
        "files_missing": 0,
        "files_duplicate": 0,
        "errors":        0,
    }

    # ── 1. Récupérer le montage ───────────────────────────────
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT local_path FROM mounts WHERE id = :id"),
                {"id": mount_id}
            ).fetchone()
    except Exception as e:
        _fail_job(job_id, f"Erreur lecture montage : {e}")
        return counters

    if not row:
        _fail_job(job_id, f"Montage {mount_id} introuvable en BDD")
        return counters

    local_path = row[0]

    # ── 2. Vérifier que le montage est accessible ─────────────
    if not os.path.isdir(local_path):
        _fail_job(job_id, f"Dossier inaccessible : {local_path}")
        return counters

    video_extensions = get_video_extensions()
    scan_start = datetime.now()

    # IDs des fichiers vus pendant ce scan (pour détecter les missing)
    seen_ids: set[int] = set()

    # ── 3. Parcours récursif ──────────────────────────────────
    logger.info(f"Scan montage {mount_id} : {local_path}")
    _update_job(job_id, status="running", started_at=scan_start)

    for dirpath, dirnames, filenames in os.walk(local_path):
        # Ignorer les dossiers cachés (ex: .Recycle, @eaDir sur Synology)
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and not d.startswith("@")]

        for filename in filenames:
            ext = Path(filename).suffix.lower()
            if ext not in video_extensions:
                continue

            filepath = os.path.join(dirpath, filename)

            # Chemin relatif depuis la racine du montage
            try:
                path_relative = str(Path(filepath).relative_to(local_path))
            except ValueError:
                path_relative = filepath

            # Hash partiel
            file_hash = compute_partial_hash(filepath)
            if file_hash is None:
                counters["errors"] += 1
                continue

            try:
                file_size = os.path.getsize(filepath)
            except OSError:
                counters["errors"] += 1
                continue

            counters["files_found"] += 1

            # ── Logique BDD ───────────────────────────────────
            try:
                with engine.connect() as conn:
                    existing = conn.execute(text("""
                        SELECT id, mount_id, path_relative, status
                        FROM media_files
                        WHERE hash_partial = :hash
                    """), {"hash": file_hash}).fetchone()

                    if existing is None:
                        # Cas A : nouveau fichier
                        conn.execute(text("""                            
                            INSERT INTO media_files
                                (mount_id, hash_partial, path_relative, filename,
                                extension, size_bytes, status, disk_status)
                            VALUES
                                (:mid, :hash, :path, :fname, :ext, :size, 'discovered', 'present')
                        """), {
                            "mid":   mount_id,
                            "hash":  file_hash,
                            "path":  path_relative,
                            "fname": filename,
                            "ext":   ext,
                            "size":  file_size,
                        })
                        new_id = conn.execute(text(
                            "SELECT id FROM media_files WHERE hash_partial = :hash",
                        ), {"hash": file_hash}).fetchone()[0]
                        seen_ids.add(new_id)
                        counters["files_new"] += 1

                    elif existing[1] != mount_id:
                        # Cas D : même hash, montage différent → doublon
                        conn.execute(text("""
                            UPDATE media_files
                            SET disk_status = 'duplicate', last_seen_at = NOW()
                            WHERE id = :id
                        """), {"id": existing[0]})
                        seen_ids.add(existing[0])
                        counters["files_duplicate"] += 1

                    elif existing[2] != path_relative:
                        # Cas C : même hash, même montage, chemin différent → renommage
                        conn.execute(text("""
                            UPDATE media_files
                            SET path_relative = :path,
                                filename      = :fname,
                                disk_status   = 'present',
                                last_seen_at  = NOW()
                            WHERE id = :id
                        """), {
                            "path":  path_relative,
                            "fname": filename,
                            "id":    existing[0],
                        })
                        seen_ids.add(existing[0])
                        counters["files_updated"] += 1

                    else:
                        # Cas B : fichier connu, rien n'a changé
                        conn.execute(text("""
                            UPDATE media_files
                            SET status = CASE
                                    WHEN EXISTS (
                                        SELECT 1 FROM video_metadata WHERE file_id = media_files.id
                                    ) THEN 'analyzed'
                                    ELSE 'discovered'
                                END,
                                disk_status  = 'present',
                                last_seen_at = NOW()
                            WHERE id = :id
                        """), {"id": existing[0]})
                        seen_ids.add(existing[0])

                    conn.commit()

            except Exception as e:
                logger.error(f"BDD erreur pour {filepath} : {e}")
                counters["errors"] += 1

    # ── 4. Marquer les fichiers non revus comme missing ───────
    try:
        with engine.connect() as conn:
            # Tous les fichiers de ce montage qui n'ont pas été vus
            all_rows = conn.execute(text("""
                SELECT id FROM media_files
                WHERE mount_id = :mid AND disk_status = 'present'
            """), {"mid": mount_id}).fetchall()

            missing_ids = [r[0] for r in all_rows if r[0] not in seen_ids]

            if missing_ids:
                conn.execute(text("""
                    UPDATE media_files
                    SET disk_status = 'missing'
                    WHERE id = ANY(:ids)
                """), {"ids": missing_ids})
                counters["files_missing"] = len(missing_ids)

            conn.commit()
    except Exception as e:
        logger.error(f"Erreur marquage missing montage {mount_id} : {e}")

    # ── 5. Clôturer le job ────────────────────────────────────
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE scan_jobs SET
                    status        = 'done',
                    finished_at   = NOW(),
                    files_found   = :found,
                    files_new     = :new,
                    files_updated = :updated,
                    files_missing = :missing
                WHERE id = :jid
            """), {
                "found":   counters["files_found"],
                "new":     counters["files_new"],
                "updated": counters["files_updated"],
                "missing": counters["files_missing"],
                "jid":     job_id,
            })
            conn.commit()
    except Exception as e:
        logger.error(f"Erreur clôture job {job_id} : {e}")

    duration = (datetime.now() - scan_start).total_seconds()
    logger.info(
        f"Scan {mount_id} terminé en {duration:.1f}s — "
        f"{counters['files_found']} trouvés, "
        f"{counters['files_new']} nouveaux, "
        f"{counters['files_updated']} renommés, "
        f"{counters['files_missing']} disparus"
    )

    # Déclencher l'analyse des nouveaux fichiers
    if counters["files_new"] > 0:
        try:
            from watcher.analyzer import analyze_queue
            analyze_queue.trigger()
        except Exception:
            pass

    return counters


# ─────────────────────────────────────────────────────────────
# Helpers jobs
# ─────────────────────────────────────────────────────────────

def _update_job(job_id: int, **kwargs):
    """Met à jour un scan_job avec les champs fournis."""
    if not kwargs:
        return
    set_parts = ", ".join(f"{k} = :{k}" for k in kwargs)
    kwargs["jid"] = job_id
    try:
        with engine.connect() as conn:
            conn.execute(
                text(f"UPDATE scan_jobs SET {set_parts} WHERE id = :jid"),
                kwargs
            )
            conn.commit()
    except Exception as e:
        logger.error(f"_update_job({job_id}): {e}")


def _fail_job(job_id: int, message: str):
    """Marque un job en erreur."""
    logger.error(f"Job {job_id} échoué : {message}")
    _update_job(job_id, status="error", finished_at=datetime.now(), error_message=message)


# ─────────────────────────────────────────────────────────────
# File de scans
# ─────────────────────────────────────────────────────────────

class ScanQueue:
    """
    File d'attente des scans de montages.

    - Un seul scan actif à la fois
    - On n'ajoute pas un montage déjà en file
    - Scan périodique automatique toutes les N heures
    - Tourne dans un thread daemon (ne bloque pas FastAPI)
    """

    def __init__(self):
        self._queue: deque[int] = deque()   # mount_ids en attente
        self._lock  = threading.Lock()
        self._event = threading.Event()     # réveille le worker quand un job arrive
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        """Démarre le thread de traitement en arrière-plan."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._worker, daemon=True, name="ScanQueueWorker"
        )
        self._thread.start()
        logger.info("ScanQueue démarrée")

    def stop(self):
        """Arrête proprement le worker."""
        self._running = False
        self._event.set()

    def enqueue(self, mount_id: int):
        """
        Ajoute un montage en file.
        Ignoré si ce mount_id est déjà en attente.
        """
        with self._lock:
            if mount_id in self._queue:
                logger.debug(f"Mount {mount_id} déjà en file, ignoré")
                return
            self._queue.append(mount_id)
            logger.info(f"Mount {mount_id} ajouté à la file de scan")
        self._event.set()   # réveille le worker

    def enqueue_all_active(self):
        """Met tous les montages actifs en file (scan périodique)."""
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT id FROM mounts WHERE active = true")
                ).fetchall()
            for row in rows:
                self.enqueue(row[0])
        except Exception as e:
            logger.error(f"enqueue_all_active: {e}")

    def _worker(self):
        """Boucle principale du worker."""
        # Attendre un peu au démarrage que la BDD soit prête
        time.sleep(3)

        while self._running:
            # ── Traiter tous les jobs en attente ──────────────
            while True:
                with self._lock:
                    if not self._queue:
                        break
                    mount_id = self._queue.popleft()

                self._process(mount_id)

            # ── Attendre le prochain événement ou timeout ──────
            interval_hours = get_scan_interval_hours()
            interval_sec   = interval_hours * 3600
            logger.debug(f"ScanQueue en attente ({interval_hours}h)")

            woken = self._event.wait(timeout=interval_sec)
            self._event.clear()

            # Si réveil par timeout (pas par enqueue) → scan périodique
            if not woken and self._running:
                logger.info("Scan périodique automatique")
                self.enqueue_all_active()

    def _process(self, mount_id: int):
        """Crée un job en BDD et lance le scan."""
        try:
            with engine.connect() as conn:
                row = conn.execute(text("""
                    INSERT INTO scan_jobs (mount_id, status)
                    VALUES (:mid, 'pending')
                    RETURNING id
                """), {"mid": mount_id}).fetchone()
                conn.commit()
                job_id = row[0]
        except Exception as e:
            logger.error(f"Impossible de créer le job pour mount {mount_id} : {e}")
            return

        logger.info(f"Démarrage scan — mount_id={mount_id}, job_id={job_id}")
        scan_mount(mount_id, job_id)

    def enqueue_priority(self, mount_id: int):
        """
        Ajoute un montage EN TÊTE de file (prioritaire).
        Utilisé quand un montage vient d'être monté physiquement —
        on veut qu'il soit scanné dès que le scan en cours se termine.
        Ignoré si ce mount_id est déjà en attente.
        """
        with self._lock:
            if mount_id in self._queue:
                logger.debug(f"Mount {mount_id} déjà en file, ignoré")
                return
            self._queue.appendleft(mount_id)
            logger.info(f"Mount {mount_id} ajouté en priorité dans la file de scan")
        self._event.set()


# Instance globale (importée dans app.py et api.py)
scan_queue = ScanQueue()