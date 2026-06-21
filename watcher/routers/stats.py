"""
MediaManager 2026 - Router : Statistiques
Routes : /api/admin/files/stats, /files/quality-stats, /jobs/status
Partagé entre l'interface admin et l'interface utilisateur.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

import time as _time

from watcher.database import engine
from watcher.utils.perf import record as _perf

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_lang_names(conn) -> dict:
    """Charge les noms de langues depuis la BDD (table language_names).

    Utilise un savepoint : si la table n'existe pas encore, seul le savepoint est annulé,
    la transaction parente reste valide et les requêtes suivantes peuvent continuer.
    """
    try:
        with conn.begin_nested():
            rows = conn.execute(text(
                "SELECT code, label FROM language_names"
            )).mappings().fetchall()
        return {r["code"]: r["label"] for r in rows}
    except Exception:
        return {}


def _resolve_lang(code: str, lang_map: dict) -> str:
    """Résout un code ISO 639 en libellé lisible via le dictionnaire de la BDD."""
    normalized = code.strip().lower()
    return lang_map.get(normalized, code.strip().upper() or "Inconnue")


@router.get("/files/stats")
def files_stats():
    """Compteurs de fichiers par statut, par catégorie et dernier scan par montage."""
    try:
        with engine.connect() as conn:

            status_rows = conn.execute(text("""
                SELECT status, disk_status, COUNT(*) as cnt
                FROM media_files
                GROUP BY status, disk_status
            """)).fetchall()
            total      = sum(r[2] for r in status_rows)
            analyzed   = sum(r[2] for r in status_rows if r[0] == 'analyzed')
            discovered = sum(r[2] for r in status_rows if r[0] == 'discovered')
            analyzing  = sum(r[2] for r in status_rows if r[0] == 'analyzing')
            missing    = sum(r[2] for r in status_rows if r[1] == 'missing')
            duplicate  = sum(r[2] for r in status_rows if r[1] == 'duplicate')

            cat_rows = conn.execute(text("""
                SELECT c.name, COUNT(f.id) as cnt
                FROM categories c
                LEFT JOIN mounts m ON m.category_id = c.id
                LEFT JOIN media_files f ON f.mount_id = m.id
                GROUP BY c.name
                ORDER BY c.name
            """)).mappings().fetchall()

            last_scans = conn.execute(text("""
                SELECT DISTINCT ON (mount_id)
                    mount_id, status, started_at, finished_at,
                    files_found, files_new, files_updated, files_missing
                FROM scan_jobs
                ORDER BY mount_id, created_at DESC
            """)).mappings().fetchall()

        def _fmt(dt):
            return str(dt)[:19] if dt else None

        return JSONResponse({
            "total":      total,
            "analyzed":   analyzed,
            "discovered": discovered,
            "analyzing":  analyzing,
            "missing":    missing,
            "duplicate":  duplicate,
            "by_category": [{"name": r["name"], "count": r["cnt"]} for r in cat_rows],
            "last_scans":  [{
                "mount_id":      r["mount_id"],
                "status":        r["status"],
                "started_at":    _fmt(r["started_at"]),
                "finished_at":   _fmt(r["finished_at"]),
                "files_found":   r["files_found"],
                "files_new":     r["files_new"],
                "files_updated": r["files_updated"],
                "files_missing": r["files_missing"],
            } for r in last_scans],
        })
    except Exception as e:
        logger.error(f"files_stats: {e}")
        raise HTTPException(500, str(e))


@router.get("/files/quality-stats")
def files_quality_stats(cat_id: int = None):
    """Statistiques qualité (codecs, résolutions, HDR, langues). Filtre optionnel par catégorie.

    Les durées sont retournées en secondes brutes — le frontend utilise formatDuration().
    """
    try:
        with engine.connect() as conn:
            lang_map = _get_lang_names(conn)

            # vm_join : inclut le JOIN media_files uniquement quand on filtre par catégorie.
            # Sans filtre, scan direct sur video_metadata (pas de JOIN inutile).
            vm_join = (
                "JOIN media_files mf ON mf.id = vm.file_id"
                " JOIN mounts mcat ON mcat.id = mf.mount_id AND mcat.category_id = :cat_id"
            ) if cat_id else ""
            # mounts_join : pour totals qui a toujours JOIN media_files mais filtre mounts optionnel.
            mounts_join = "JOIN mounts mcat ON mcat.id = mf.mount_id AND mcat.category_id = :cat_id" if cat_id else ""
            semi_filter = (
                "EXISTS (SELECT 1 FROM media_files mf2"
                " JOIN mounts mcat2 ON mcat2.id = mf2.mount_id"
                " WHERE mf2.id = video_metadata.file_id AND mcat2.category_id = :cat_id)"
            ) if cat_id else "1=1"
            path_filter = (
                "EXISTS (SELECT 1 FROM mounts mcat3"
                " WHERE mcat3.id = mf.mount_id AND mcat3.category_id = :cat_id)"
            ) if cat_id else "1=1"
            params = {"cat_id": cat_id} if cat_id else {}

            _t = _time.perf_counter()
            codecs = conn.execute(text(f"""
                SELECT video_codec, COUNT(*) as cnt
                FROM video_metadata vm
                {vm_join}
                WHERE video_codec IS NOT NULL
                GROUP BY video_codec ORDER BY cnt DESC
            """), params).mappings().fetchall()
            _perf("quality_stats", "codecs", (_time.perf_counter() - _t) * 1000, len(codecs))

            _t = _time.perf_counter()
            resolutions = conn.execute(text(f"""
                SELECT
                    CASE
                        WHEN video_height >= 2160 THEN '4K'
                        WHEN video_height >= 1080 THEN '1080p'
                        WHEN video_height >= 720  THEN '720p'
                        ELSE 'SD'
                    END as label,
                    COUNT(*) as cnt
                FROM video_metadata vm
                {vm_join}
                WHERE video_height IS NOT NULL
                GROUP BY label ORDER BY cnt DESC
            """), params).mappings().fetchall()
            _perf("quality_stats", "resolutions", (_time.perf_counter() - _t) * 1000, len(resolutions))

            _t = _time.perf_counter()
            hdr = conn.execute(text(f"""
                SELECT hdr_format, COUNT(*) as cnt
                FROM video_metadata vm
                {vm_join}
                WHERE hdr_format IS NOT NULL
                GROUP BY hdr_format ORDER BY cnt DESC
            """), params).mappings().fetchall()
            _perf("quality_stats", "hdr", (_time.perf_counter() - _t) * 1000, len(hdr))

            _t = _time.perf_counter()
            audio_rows = conn.execute(text(f"""
                SELECT audio_codecs, audio_languages, audio_channel_layouts
                FROM video_metadata
                WHERE {semi_filter}
                  AND (audio_codecs IS NOT NULL OR audio_languages IS NOT NULL
                       OR audio_channel_layouts IS NOT NULL)
            """), params).fetchall()
            _perf("quality_stats", "audio", (_time.perf_counter() - _t) * 1000, len(audio_rows))

            _t = _time.perf_counter()
            sub_rows = conn.execute(text(f"""
                SELECT subtitle_languages FROM video_metadata
                WHERE {semi_filter} AND subtitle_languages IS NOT NULL
            """), params).fetchall()
            _perf("quality_stats", "subtitles", (_time.perf_counter() - _t) * 1000, len(sub_rows))

            no_sub = conn.execute(text(f"""
                SELECT COUNT(*) FROM video_metadata
                WHERE {semi_filter}
                  AND (subtitle_languages IS NULL OR subtitle_languages = '')
            """), params).fetchone()[0]

            _t = _time.perf_counter()
            titles_rows = conn.execute(text(f"""
                SELECT
                    SPLIT_PART(mf.path_relative, '/', 1) as title,
                    COUNT(*) as cnt,
                    ROUND(SUM(mf.size_bytes)/1073741824::numeric, 2) as size_gb
                FROM media_files mf
                WHERE {path_filter} AND mf.status = 'analyzed'
                GROUP BY title ORDER BY title
            """), params).mappings().fetchall()
            _perf("quality_stats", "titles", (_time.perf_counter() - _t) * 1000, len(titles_rows))

            _t = _time.perf_counter()
            totals = conn.execute(text(f"""
                SELECT
                    COUNT(*)                                            as total,
                    COALESCE(SUM(vm.duration_seconds), 0)               as total_seconds,
                    ROUND(AVG(mf.size_bytes)/1073741824::numeric, 2)    as avg_size_gb,
                    ROUND(SUM(mf.size_bytes)/1099511627776::numeric, 2) as total_tb
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                {mounts_join}
            """), params).mappings().fetchone()
            _perf("quality_stats", "totals", (_time.perf_counter() - _t) * 1000, 1)

            by_category = []
            if not cat_id:
                cat_rows = conn.execute(text("""
                    SELECT c.id, c.name, COUNT(mf.id) as cnt
                    FROM categories c
                    LEFT JOIN mounts m ON m.category_id = c.id
                    LEFT JOIN media_files mf ON mf.mount_id = m.id
                    GROUP BY c.id, c.name
                    ORDER BY cnt DESC
                """)).mappings().fetchall()
                by_category = [{"id": r["id"], "name": r["name"], "count": r["cnt"]} for r in cat_rows]

        # Agrégation des champs semicolon-délimités en Python
        audio_codec_counts: dict = {}
        audio_lang_counts:  dict = {}
        chan_counts:        dict = {}
        for row in audio_rows:
            for c in (row[0] or "").split(";"):
                c = c.strip().upper()
                if c:
                    audio_codec_counts[c] = audio_codec_counts.get(c, 0) + 1
            for lc in (row[1] or "").split(";"):
                lc = lc.strip().lower()
                if lc:
                    name = _resolve_lang(lc, lang_map)
                    audio_lang_counts[name] = audio_lang_counts.get(name, 0) + 1
            for ch in (row[2] or "").split(";"):
                ch = ch.strip()
                if ch:
                    chan_counts[ch] = chan_counts.get(ch, 0) + 1

        sub_lang_counts: dict = {}
        for row in sub_rows:
            for lc in (row[0] or "").split(";"):
                lc = lc.strip().lower()
                if lc:
                    name = _resolve_lang(lc, lang_map)
                    sub_lang_counts[name] = sub_lang_counts.get(name, 0) + 1

        def _sorted_list(d: dict) -> list:
            return sorted([{"label": k, "count": v} for k, v in d.items()], key=lambda x: -x["count"])

        return JSONResponse({
            "cat_id":         cat_id,
            "total":          totals["total"] or 0,
            "total_seconds":  int(totals["total_seconds"] or 0),
            "avg_size_gb":    float(totals["avg_size_gb"] or 0),
            "total_tb":       float(totals["total_tb"] or 0),
            "codecs":         [{"label": r["video_codec"], "count": r["cnt"]} for r in codecs],
            "resolutions":    [{"label": r["label"],       "count": r["cnt"]} for r in resolutions],
            "hdr":            [{"label": r["hdr_format"],  "count": r["cnt"]} for r in hdr],
            "audio_codecs":   _sorted_list(audio_codec_counts),
            "audio_langs":    _sorted_list(audio_lang_counts),
            "audio_channels": _sorted_list(chan_counts),
            "sub_langs":      _sorted_list(sub_lang_counts),
            "no_sub_count":   int(no_sub),
            "titles":         [{"name": r["title"], "count": r["cnt"], "size_gb": float(r["size_gb"] or 0)} for r in titles_rows],
            "nb_titles":      len(titles_rows),
            "by_category":    by_category,
        })

    except Exception as e:
        logger.error(f"files_quality_stats: {e}")
        raise HTTPException(500, str(e))


@router.get("/jobs/status")
def jobs_status():
    """État actuel des 3 jobs : scanner, analyser, catalogueur."""
    try:
        with engine.connect() as conn:

            last_scan = conn.execute(text("""
                SELECT j.status, j.started_at, j.finished_at,
                       j.files_found, j.files_new, m.local_path
                FROM scan_jobs j
                JOIN mounts m ON m.id = j.mount_id
                ORDER BY j.created_at DESC LIMIT 1
            """)).mappings().fetchone()

            running_session = conn.execute(text("""
                SELECT status, folder_path, files_done, files_total, started_at
                FROM analyze_sessions
                WHERE status = 'running'
                ORDER BY started_at DESC LIMIT 1
            """)).mappings().fetchone()

            last_session = conn.execute(text("""
                SELECT status, folder_path, files_done, files_total, finished_at
                FROM analyze_sessions
                WHERE status = 'done'
                ORDER BY finished_at DESC LIMIT 1
            """)).mappings().fetchone()

            analyze_stats = conn.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status='done')    as done,
                    COUNT(*) FILTER (WHERE status='pending') as pending,
                    COUNT(*) FILTER (WHERE status='running') as running,
                    COUNT(*) FILTER (WHERE status='error')   as error
                FROM analyze_sessions
            """)).mappings().fetchone()

            catalog_stats = conn.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE folder_status='ok')        as ok,
                    COUNT(*) FILTER (WHERE folder_status='to_rename') as to_rename,
                    COUNT(*) FILTER (WHERE folder_status='pending')   as pending
                FROM media_titles
            """)).mappings().fetchone()

            proposals_pending = conn.execute(text("""
                SELECT COUNT(*) FROM rename_proposals WHERE status='pending'
            """)).fetchone()[0]

        def _fmt(dt):
            return str(dt)[:19] if dt else None

        return JSONResponse({
            "scanner": {
                "last_status":   last_scan["status"]      if last_scan else None,
                "last_started":  _fmt(last_scan["started_at"])  if last_scan else None,
                "last_finished": _fmt(last_scan["finished_at"]) if last_scan else None,
                "files_found":   last_scan["files_found"] if last_scan else 0,
                "files_new":     last_scan["files_new"]   if last_scan else 0,
                "last_mount":    last_scan["local_path"].split('/')[-1] if last_scan else None,
            },
            "analyzer": {
                "running":          running_session is not None,
                "current_folder":   running_session["folder_path"]  if running_session else None,
                "current_done":     running_session["files_done"]   if running_session else 0,
                "current_total":    running_session["files_total"]  if running_session else 0,
                "last_folder":      last_session["folder_path"]     if last_session else None,
                "last_finished":    _fmt(last_session["finished_at"]) if last_session else None,
                "sessions_done":    analyze_stats["done"]    if analyze_stats else 0,
                "sessions_pending": analyze_stats["pending"] if analyze_stats else 0,
            },
            "cataloger": {
                "titles_ok":         catalog_stats["ok"]        if catalog_stats else 0,
                "titles_to_rename":  catalog_stats["to_rename"] if catalog_stats else 0,
                "titles_pending":    catalog_stats["pending"]   if catalog_stats else 0,
                "proposals_pending": proposals_pending,
            },
        })
    except Exception as e:
        logger.error(f"jobs_status: {e}")
        raise HTTPException(500, str(e))
