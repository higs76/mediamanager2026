"""
MediaManager 2026 - Catalogueur de médias

Pipeline : Scanner → Analyser → Catalogueur (cascade)

Responsabilités :
- Construit le catalogue (media_titles, media_items)
- Trie par date de modification (fichiers récents en priorité)
- Génère les propositions de renommage (rename_proposals)
- Lit les tech_tags depuis la config BDD
"""

import logging
import os
import re
import threading
import time
from pathlib import Path
from datetime import datetime

from sqlalchemy import text
from watcher.database import engine
from watcher.config_db import get_config, get_video_extensions

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Config dynamique
# ─────────────────────────────────────────────────────────────

def get_tech_tags_pattern() -> re.Pattern:
    """Construit la regex des tags techniques depuis la config BDD."""
    raw = get_config("catalog_tech_tags", "")
    if not raw:
        return re.compile(r'(?!)')  # ne matche rien
    tags = [re.escape(t.strip()) for t in raw.split(";") if t.strip()]
    return re.compile(r'\b(' + '|'.join(tags) + r')\b', re.IGNORECASE)

def get_catalog_interval_hours() -> float:
    try:
        return float(get_config("catalog_interval_hours", "24"))
    except ValueError:
        return 24.0


# ─────────────────────────────────────────────────────────────
# Nettoyage des noms
# ─────────────────────────────────────────────────────────────

_RELEASE_GROUP   = re.compile(r'-[A-Z0-9]{2,20}$', re.IGNORECASE)
_DOTS_UNDERSCORES = re.compile(r'[._]+')
_MULTI_SPACES    = re.compile(r' {2,}')
_PARASITIC_SUFFIX = re.compile(r'-\d+$')
_YEAR_PAREN      = re.compile(r'\((\d{4})\)')
_YEAR_PLAIN      = re.compile(r'\b(19\d{2}|20\d{2})\b')

_SE_PATTERNS = [
    re.compile(r'[Ss](\d{1,3})[Ee](\d{1,4})'),   # S01E01
    re.compile(r'(\d{1,3})[xX](\d{1,4})'),         # 01x01
]


def clean_name(name: str) -> str:
    """Nettoie un nom de fichier/dossier."""
    name = _RELEASE_GROUP.sub('', name)
    name = get_tech_tags_pattern().sub('', name)
    # Supprimer les points orphelins après suppression des tags
    name = re.sub(r'\.{2,}', '', name)       # points multiples
    name = re.sub(r'\s*\.\s*', ' ', name)    # points isolés
    name = _MULTI_SPACES.sub(' ', name).strip()
    name = re.sub(r'\s*-\s*$', '', name).strip()
    # Supprimer les tirets/espaces en début
    name = re.sub(r'^[\s\-]+', '', name).strip()
    return name


def dots_to_spaces(name: str) -> str:
    return _MULTI_SPACES.sub(' ', _DOTS_UNDERSCORES.sub(' ', name)).strip()


def extract_year(name: str) -> tuple[str, int | None]:
    m = _YEAR_PAREN.search(name)
    if m:
        return name[:m.start()].strip(), int(m.group(1))
    m = _YEAR_PLAIN.search(name)
    if m:
        clean = (name[:m.start()] + name[m.end():]).strip()
        return clean, int(m.group(1))
    return name, None


def extract_season_episode(filename: str) -> tuple[int | None, int | None]:
    for pattern in _SE_PATTERNS:
        m = pattern.search(filename)
        if m:
            return int(m.group(1)), int(m.group(2))
    return None, None


def extract_episode_title(filename: str) -> str | None:
    stem = Path(filename).stem
    # Convertir les points en espaces d'abord
    if '.' in stem and ' ' not in stem:
        stem = dots_to_spaces(stem)
    
    for pattern in _SE_PATTERNS:
        m = pattern.search(stem)
        if m:
            after = stem[m.end():].strip()
            # Supprimer séparateurs de début
            after = re.sub(r'^[\s\-–]+', '', after).strip()
            # Supprimer les tags techniques
            after = clean_name(after)
            # Supprimer les résidus très courts (1-2 lettres isolées)
            #after = re.sub(r'\b[A-Za-z]{1,2}\b', '', after) #bug : supprimer les Le la ...
            after = _MULTI_SPACES.sub(' ', after).strip()
            # Supprimer les années isolées
            after = _YEAR_PLAIN.sub('', after).strip()
            after = _PARASITIC_SUFFIX.sub('', after).strip()
            # Ne retourner que si le résultat est significatif (> 2 chars)
            return after if len(after) > 2 else None
    return None


def extract_season_number(folder_name: str, special_folder: str) -> int | None:
    if folder_name.lower() == special_folder.lower():
        return 0
    m = re.match(r'^[Ss](\d{1,3})$', folder_name)
    if m:
        return int(m.group(1))
    m = re.match(r'^(?:Saison|Season)\s*(\d{1,3})$', folder_name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r'^(\d{1,3})$', folder_name)
    if m:
        return int(m.group(1))
    return None


# ─────────────────────────────────────────────────────────────
# Construction des noms proposés
# ─────────────────────────────────────────────────────────────

def build_movie_name(title: str, year: int | None, template: dict) -> str:
    sep  = template.get('sep_year') or ' '
    fmt  = template.get('year_format') or 'paren'
    if year and fmt == 'paren':
        return f"{title}{sep}({year})"
    elif year and fmt == 'plain':
        return f"{title}{sep}{year}"
    return title


def build_episode_name(serie: str, season: int, episode: int,
                        ep_title: str | None, template: dict) -> str:
    sep1  = template.get('sep1')           or ' - '
    sep2  = template.get('sep2')           or ' - '
    prefS = template.get('prefix_season')  or ''
    digS  = template.get('digits_season')  or 2
    sepSE = template.get('sep_se')         or 'x'
    prefE = template.get('prefix_episode') or ''
    digE  = template.get('digits_episode') or 2
    s = str(season).zfill(digS)
    e = str(episode).zfill(digE)
    num = f"{prefS}{s}{sepSE}{prefE}{e}"
    if ep_title:
        return f"{serie}{sep1}{num}{sep2}{ep_title}"
    return f"{serie}{sep1}{num}"


# ─────────────────────────────────────────────────────────────
# Vérification du nommage
# ─────────────────────────────────────────────────────────────

def is_clean_movie_folder(folder: str, template: dict) -> bool:
    fmt = template.get('year_format') or 'paren'
    if fmt == 'paren':
        return bool(_YEAR_PAREN.search(folder))
    elif fmt == 'plain':
        return bool(_YEAR_PLAIN.search(folder))
    return True


def is_clean_movie_file(filename: str, folder: str) -> bool:
    return Path(filename).stem.lower().startswith(folder.lower())


def is_clean_episode(filename: str, template: dict) -> bool:
    stem  = Path(filename).stem
    sep1  = re.escape(template.get('sep1')           or ' - ')
    prefS = re.escape(template.get('prefix_season')  or '')
    digS  = template.get('digits_season')             or 2
    sepSE = re.escape(template.get('sep_se')         or 'x')
    prefE = re.escape(template.get('prefix_episode') or '')
    digE  = template.get('digits_episode')            or 2
    pat = re.compile(
        r'.+' + sep1 + prefS + r'\d{' + str(digS) + r'}' +
        sepSE + prefE + r'\d{' + str(digE) + r'}',
        re.IGNORECASE
    )
    return bool(pat.match(stem))


# ─────────────────────────────────────────────────────────────
# Upsert propositions
# ─────────────────────────────────────────────────────────────

def _upsert_title_proposal(conn, title_id: int, current: str,
                            proposed: str, rule: str):
    if current == proposed:
        return
    existing = conn.execute(text("""
        SELECT id FROM rename_proposals
        WHERE title_id = :tid
        AND status NOT IN ('accepted','rejected','custom')
    """), {"tid": title_id}).fetchone()

    if not existing:
        conn.execute(text("""
            INSERT INTO rename_proposals
                (title_id, current_name, proposed_name, rule_used)
            VALUES (:tid, :cur, :prop, :rule)
        """), {"tid": title_id, "cur": current,
               "prop": proposed, "rule": rule})
    else:
        conn.execute(text("""
            UPDATE rename_proposals
            SET proposed_name = :prop, rule_used = :rule
            WHERE id = :id
        """), {"prop": proposed, "rule": rule, "id": existing[0]})


def _upsert_item_proposal(conn, item_id: int, current: str,
                           proposed: str, rule: str):
    if current == proposed:
        return
    existing = conn.execute(text("""
        SELECT id FROM rename_proposals
        WHERE item_id = :iid
        AND status NOT IN ('accepted','rejected','custom')
    """), {"iid": item_id}).fetchone()

    if not existing:
        conn.execute(text("""
            INSERT INTO rename_proposals
                (item_id, current_name, proposed_name, rule_used)
            VALUES (:iid, :cur, :prop, :rule)
        """), {"iid": item_id, "cur": current,
               "prop": proposed, "rule": rule})
    else:
        conn.execute(text("""
            UPDATE rename_proposals
            SET proposed_name = :prop, rule_used = :rule
            WHERE id = :id
        """), {"prop": proposed, "rule": rule, "id": existing[0]})


# ─────────────────────────────────────────────────────────────
# Chargement du template
# ─────────────────────────────────────────────────────────────

def load_template(template_id: int | None) -> dict | None:
    if not template_id:
        return None
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT sep1, sep2, prefix_season, digits_season,
                       sep_se, prefix_episode, digits_episode,
                       folder_prefix, folder_digits, special_folder,
                       sep_year, year_format, bonus_folder
                FROM naming_templates WHERE id = :id
            """), {"id": template_id}).fetchone()
        if not row:
            return None
        return {
            "sep1":           row[0],
            "sep2":           row[1],
            "prefix_season":  row[2],
            "digits_season":  row[3],
            "sep_se":         row[4],
            "prefix_episode": row[5],
            "digits_episode": row[6],
            "folder_prefix":  row[7],
            "folder_digits":  row[8],
            "special_folder": row[9],
            "sep_year":       row[10],
            "year_format":    row[11],
            "bonus_folder":   row[12],
        }
    except Exception as e:
        logger.error(f"load_template {template_id}: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# Films
# ─────────────────────────────────────────────────────────────

def catalog_movies(mount_id: int, local_path: str,
                   category_id: int, template: dict):
    logger.info(f"Films — mount {mount_id}")
    bonus = (template.get('bonus_folder') or 'Bonus').lower()

    try:
        # Trier par mtime décroissant (récents en premier)
        entries = sorted(
            [e for e in os.scandir(local_path) if e.is_dir()
             and not e.name.startswith('.') and not e.name.startswith('@') and not e.name.startswith('#')],
            key=lambda e: e.stat().st_mtime,
            reverse=True
        )
    except OSError as e:
        logger.error(f"catalog_movies scan {local_path}: {e}")
        return

    for entry in entries:
        try:
            _process_movie_folder(mount_id, category_id, template,
                                  entry.name, entry.path, bonus)
        except Exception as e:
            logger.error(f"catalog_movies {entry.name}: {e}")


def _process_movie_folder(mount_id, category_id, template,
                           folder_name, folder_path, bonus_folder):
    clean_folder, year = extract_year(folder_name)
    well_named = is_clean_movie_folder(folder_name, template)

    with engine.connect() as conn:
        existing = conn.execute(text("""
            SELECT id, folder_status FROM media_titles
            WHERE mount_id = :mid AND folder_name = :fn
        """), {"mid": mount_id, "fn": folder_name}).fetchone()

        if not existing:
            row = conn.execute(text("""
                INSERT INTO media_titles
                    (category_id, mount_id, folder_name, display_name,
                     year, folder_status)
                VALUES (:cat, :mid, :fn, :dn, :yr, :st)
                RETURNING id
            """), {
                "cat": category_id, "mid": mount_id,
                "fn": folder_name,  "dn": clean_folder,
                "yr": year, "st": 'ok' if well_named else 'to_rename'
            }).fetchone()
            title_id = row[0]
        else:
            title_id = existing[0]
            if existing[1] == 'pending':
                conn.execute(text("""
                    UPDATE media_titles
                    SET folder_status=:st, display_name=:dn, year=:yr
                    WHERE id=:id
                """), {
                    "st": 'ok' if well_named else 'to_rename',
                    "dn": clean_folder, "yr": year, "id": title_id
                })

        if not well_named:
            proposed = build_movie_name(clean_folder, year, template)
            _upsert_title_proposal(conn, title_id, folder_name,
                                   proposed, 'movie_folder')
        conn.commit()

    _process_movie_files(mount_id, title_id, template,
                         folder_path, folder_name, clean_folder,
                         year, bonus_folder)


def _process_movie_files(mount_id, title_id, template, folder_path,
                          folder_name, clean_folder, year, bonus_folder):
    exts = get_video_extensions()

    try:
        entries = sorted(
            os.scandir(folder_path),
            key=lambda e: e.stat().st_mtime,
            reverse=True
        )
    except OSError:
        return

    for entry in entries:
        if entry.is_dir():
            if entry.name.lower() == bonus_folder:
                logger.debug(f"Bonus ignoré : {entry.path}")
            continue
        if Path(entry.name).suffix.lower() not in exts:
            continue

        filename = entry.name
        well_named = is_clean_movie_file(filename, folder_name)

        try:
            with engine.connect() as conn:
                mf = conn.execute(text("""
                    SELECT id FROM media_files
                    WHERE mount_id=:mid AND path_relative=:path
                    AND disk_status='present'
                """), {
                    "mid": mount_id,
                    "path": f"{folder_name}/{filename}"
                }).fetchone()
                if not mf:
                    continue
                file_id = mf[0]

                existing = conn.execute(text(
                    "SELECT id, file_status FROM media_items WHERE file_id=:fid"
                ), {"fid": file_id}).fetchone()

                if not existing:
                    row = conn.execute(text("""
                        INSERT INTO media_items (title_id, file_id, file_status)
                        VALUES (:tid, :fid, :st) RETURNING id
                    """), {
                        "tid": title_id, "fid": file_id,
                        "st": 'ok' if well_named else 'to_rename'
                    }).fetchone()
                    item_id = row[0]
                else:
                    item_id = existing[0]
                    if existing[1] == 'pending':
                        conn.execute(text("""
                            UPDATE media_items SET file_status=:st WHERE id=:id
                        """), {
                            "st": 'ok' if well_named else 'to_rename',
                            "id": item_id
                        })

                if not well_named:
                    stem = Path(filename).stem
                    c = clean_name(dots_to_spaces(stem))
                    _, fy = extract_year(c)
                    proposed = build_movie_name(
                        clean_folder, fy or year, template
                    ) + Path(filename).suffix
                    _upsert_item_proposal(conn, item_id, filename,
                                         proposed, 'movie_file')
                conn.commit()
        except Exception as e:
            logger.error(f"_process_movie_files {filename}: {e}")


# ─────────────────────────────────────────────────────────────
# Séries
# ─────────────────────────────────────────────────────────────

def catalog_series(mount_id: int, local_path: str,
                   category_id: int, template: dict):
    logger.info(f"Séries — mount {mount_id}")

    try:
        entries = sorted(
            [e for e in os.scandir(local_path) if e.is_dir()
             and not e.name.startswith('.') and not e.name.startswith('@') and not e.name.startswith('#')],
            key=lambda e: e.stat().st_mtime,
            reverse=True
        )
    except OSError as e:
        logger.error(f"catalog_series scan {local_path}: {e}")
        return

    for entry in entries:
        try:
            _process_serie_folder(mount_id, category_id, template,
                                  entry.name, entry.path)
        except Exception as e:
            logger.error(f"catalog_series {entry.name}: {e}")

def _process_serie_folder(mount_id, category_id, template,
                           folder_name, folder_path):
    
    def is_acronym(name: str) -> bool:
        """Détecte si un nom est un acronyme style B.R.I ou C.S.I"""
        return bool(re.match(r'^[A-Z](\.[A-Z])+\.?$', name))

    has_dots   = '.' in folder_name and ' ' not in folder_name
    is_acro    = is_acronym(folder_name)
    clean      = folder_name if is_acro else (dots_to_spaces(folder_name) if has_dots else folder_name)
    well_named = not has_dots or is_acro

    with engine.connect() as conn:
        existing = conn.execute(text("""
            SELECT id, folder_status FROM media_titles
            WHERE mount_id=:mid AND folder_name=:fn
        """), {"mid": mount_id, "fn": folder_name}).fetchone()

        if not existing:
            row = conn.execute(text("""
                INSERT INTO media_titles
                    (category_id, mount_id, folder_name,
                     display_name, folder_status)
                VALUES (:cat, :mid, :fn, :dn, :st)
                RETURNING id
            """), {
                "cat": category_id, "mid": mount_id,
                "fn": folder_name,  "dn": clean,
                "st": 'ok' if well_named else 'to_rename'
            }).fetchone()
            title_id = row[0]
        else:
            title_id = existing[0]
            if existing[1] == 'pending':
                conn.execute(text("""
                    UPDATE media_titles
                    SET folder_status=:st, display_name=:dn WHERE id=:id
                """), {
                    "st": 'ok' if well_named else 'to_rename',
                    "dn": clean, "id": title_id
                })

        if not well_named:
            _upsert_title_proposal(conn, title_id, folder_name,
                                   clean, 'serie_dots')
        conn.commit()

    _process_season_folders(mount_id, title_id, template,
                            folder_name, folder_path, clean)


def _process_season_folders(mount_id, title_id, template,
                             serie_folder, serie_path, serie_name):
    bonus_folders = {'bonus', 'extras', 'featurettes'}
    special = (template.get('special_folder') or 'S0').lower()
    exts = get_video_extensions()

    try:
        entries = sorted(os.scandir(serie_path), key=lambda e: e.name)
    except OSError:
        return

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name.startswith('.') or entry.name.startswith('@') or entry.name.startswith('#'):
            continue
        if entry.name.lower() in bonus_folders:
            logger.debug(f"Bonus ignoré : {entry.path}")
            continue

        season_num = extract_season_number(entry.name, special)
        _process_episode_files(
            mount_id, title_id, template,
            serie_folder, entry.path, entry.name,
            serie_name, season_num, exts
        )


def _process_episode_files(mount_id, title_id, template,
                            serie_folder, season_path, season_folder,
                            serie_name, season_num, exts):
    try:
        entries = sorted(
            os.scandir(season_path),
            key=lambda e: e.stat().st_mtime,
            reverse=True
        )
    except OSError:
        return

    for entry in entries:
        if not entry.is_file():
            continue
        if Path(entry.name).suffix.lower() not in exts:
            continue

        filename  = entry.name
        season, episode = extract_season_episode(filename)
        if season is None and season_num is not None:
            season = season_num
        ep_title = extract_episode_title(filename) if (
            season is not None and episode is not None) else None
        well_named = (season is not None and episode is not None
                      and is_clean_episode(filename, template))

        try:
            with engine.connect() as conn:
                path_rel = f"{serie_folder}/{season_folder}/{filename}"
                mf = conn.execute(text("""
                    SELECT id FROM media_files
                    WHERE mount_id=:mid AND path_relative=:path
                    AND disk_status='present'
                """), {"mid": mount_id, "path": path_rel}).fetchone()
                if not mf:
                    continue
                file_id = mf[0]

                existing = conn.execute(text(
                    "SELECT id, file_status FROM media_items WHERE file_id=:fid"
                ), {"fid": file_id}).fetchone()

                if not existing:
                    row = conn.execute(text("""
                        INSERT INTO media_items
                            (title_id, file_id, season, episode,
                             episode_title, file_status)
                        VALUES (:tid, :fid, :s, :e, :et, :st)
                        RETURNING id
                    """), {
                        "tid": title_id, "fid": file_id,
                        "s": season, "e": episode, "et": ep_title,
                        "st": 'ok' if well_named else 'to_rename'
                    }).fetchone()
                    item_id = row[0]
                else:
                    item_id = existing[0]
                    if existing[1] == 'pending':
                        conn.execute(text("""
                            UPDATE media_items
                            SET season=:s, episode=:e, episode_title=:et,
                                file_status=:st
                            WHERE id=:id
                        """), {
                            "s": season, "e": episode, "et": ep_title,
                            "st": 'ok' if well_named else 'to_rename',
                            "id": item_id
                        })

                if not well_named and season is not None and episode is not None:
                    # Nettoyer le titre d'épisode des résidus
                    clean_ep_title = ep_title
                    if clean_ep_title:
                        # Supprimer les résidus de points isolés
                        clean_ep_title = re.sub(r'\b\w{1,2}\b\.?', '', clean_ep_title)
                        clean_ep_title = _MULTI_SPACES.sub(' ', clean_ep_title).strip()
                        clean_ep_title = clean_ep_title if clean_ep_title else None
                    proposed = build_episode_name(
                        serie_name, season, episode, clean_ep_title, template
                    ) + Path(filename).suffix
                    _upsert_item_proposal(conn, item_id, filename,
                                          proposed, 'episode_format')
                conn.commit()
        except Exception as e:
            logger.error(f"_process_episode_files {filename}: {e}")


# ─────────────────────────────────────────────────────────────
# Point d'entrée
# ─────────────────────────────────────────────────────────────

def run_cataloger():
    """Lance le catalogueur sur tous les montages actifs."""
    logger.info("Catalogueur démarré")
    try:
        with engine.connect() as conn:
            mounts = conn.execute(text("""
                SELECT m.id, m.local_path, m.category_id,
                       c.has_seasons, c.template_id, c.name
                FROM mounts m
                JOIN categories c ON c.id = m.category_id
                WHERE m.active = true
            """)).fetchall()
    except Exception as e:
        logger.error(f"run_cataloger: {e}")
        return

    for m in mounts:
        mount_id, local_path, cat_id, has_seasons, tpl_id, cat_name = m
        if not os.path.isdir(local_path):
            logger.warning(f"Inaccessible : {local_path}")
            continue
        template = load_template(tpl_id)
        if not template:
            logger.warning(f"Pas de template pour {cat_name}")
            continue
        try:
            if has_seasons:
                catalog_series(mount_id, local_path, cat_id, template)
            else:
                catalog_movies(mount_id, local_path, cat_id, template)
        except Exception as e:
            logger.error(f"run_cataloger mount {mount_id}: {e}")

    logger.info("Catalogueur terminé")


# ─────────────────────────────────────────────────────────────
# CatalogQueue — file d'exécution asynchrone
# ─────────────────────────────────────────────────────────────

class CatalogQueue:
    """
    File dédiée au catalogueur.
    Tourne dans son propre thread daemon pour ne pas bloquer l'AnalyzeQueue.
    Déclenché par trigger() à la fin de chaque session d'analyse.
    """

    def __init__(self):
        self._event   = threading.Event()
        self._thread  = None
        self._running = False

    def start(self):
        self._running = True
        self._thread  = threading.Thread(
            target=self._worker, daemon=True, name="CatalogQueueWorker"
        )
        self._thread.start()
        logger.info("CatalogQueue démarrée")

    def stop(self):
        self._running = False
        self._event.set()

    def trigger(self):
        """Déclenche une passe de catalogage. Appelé après analyse ou manuellement."""
        self._event.set()

    def _worker(self):
        time.sleep(8)  # Attendre que la BDD et l'analyze soient prêtes
        while self._running:
            self._event.wait(timeout=1800)
            self._event.clear()
            if not self._running:
                break
            try:
                run_cataloger()
            except Exception as e:
                logger.error(f"CatalogQueue: {e}")


# Instance globale
catalog_queue = CatalogQueue()