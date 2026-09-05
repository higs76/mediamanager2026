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
            error      = sum(r[2] for r in status_rows if r[0] == 'error')
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
            "error":      error,
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
            params = {"cat_id": cat_id} if cat_id else {}

            # Joins de filtrage par catégorie — construits selon le contexte de chaque requête
            # Pour video_metadata : media_files est joint conditionnellement
            vm_cat  = (
                "JOIN media_files mf ON mf.id = vm.file_id "
                "JOIN mounts mcat ON mcat.id = mf.mount_id AND mcat.category_id = :cat_id"
            ) if cat_id else ""
            # Pour totals : media_files toujours joint (SUM sur mf.size_bytes), mounts conditionnel
            tot_cat = "JOIN mounts mcat ON mcat.id = mf.mount_id AND mcat.category_id = :cat_id" if cat_id else ""

            def _trk_join(alias: str) -> str:
                """Join media_files+mounts pour filtrer par catégorie, omis entièrement sans filtre
                (évite un hash join de ~40k lignes inutile sur la vue 'toutes catégories')."""
                if not cat_id:
                    return ""
                return (
                    f"JOIN media_files mf ON mf.id = {alias}.file_id "
                    "JOIN mounts mcat ON mcat.id = mf.mount_id AND mcat.category_id = :cat_id"
                )
            # Pour les titres (basé sur media_files)
            path_filter = (
                "EXISTS (SELECT 1 FROM mounts mcat3 "
                "WHERE mcat3.id = mf.mount_id AND mcat3.category_id = :cat_id)"
            ) if cat_id else "1=1"

            _t = _time.perf_counter()
            codecs = conn.execute(text(f"""
                SELECT c.name as video_codec, COUNT(*) as cnt
                FROM video_metadata vm
                JOIN codecs c ON c.id = vm.video_codec_id
                {vm_cat}
                WHERE vm.video_codec_id IS NOT NULL
                GROUP BY c.name ORDER BY cnt DESC
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
                {vm_cat}
                WHERE video_height IS NOT NULL
                GROUP BY label ORDER BY cnt DESC
            """), params).mappings().fetchall()
            _perf("quality_stats", "resolutions", (_time.perf_counter() - _t) * 1000, len(resolutions))

            _t = _time.perf_counter()
            hdr = conn.execute(text(f"""
                SELECT hf.name as hdr_format, COUNT(DISTINCT fhf.file_id) as cnt
                FROM file_hdr_formats fhf
                JOIN hdr_formats hf ON hf.id = fhf.hdr_format_id
                {_trk_join('fhf')}
                GROUP BY hf.name ORDER BY cnt DESC
            """), params).mappings().fetchall()
            _perf("quality_stats", "hdr", (_time.perf_counter() - _t) * 1000, len(hdr))

            _t = _time.perf_counter()
            audio_codecs_rows = conn.execute(text(f"""
                SELECT c.name as codec_name, COUNT(*) as cnt
                FROM audio_tracks at
                JOIN codecs c ON c.id = at.codec_id
                {_trk_join('at')}
                GROUP BY c.name ORDER BY cnt DESC
            """), params).mappings().fetchall()

            audio_langs_rows = conn.execute(text(f"""
                SELECT l.label as lang_label, COUNT(DISTINCT at.file_id) as cnt
                FROM audio_tracks at
                JOIN languages l ON l.id = at.language_id
                {_trk_join('at')}
                GROUP BY l.label ORDER BY cnt DESC
            """), params).mappings().fetchall()

            audio_chan_rows = conn.execute(text(f"""
                SELECT
                    CASE at.channels
                        WHEN 1 THEN 'Mono'
                        WHEN 2 THEN 'Stéréo'
                        WHEN 6 THEN '5.1'
                        WHEN 8 THEN '7.1'
                        ELSE at.channels::text || ' ch'
                    END as label,
                    COUNT(*) as cnt
                FROM audio_tracks at
                {_trk_join('at')}
                WHERE at.channels IS NOT NULL
                GROUP BY at.channels ORDER BY cnt DESC
            """), params).mappings().fetchall()
            _perf("quality_stats", "audio", (_time.perf_counter() - _t) * 1000,
                  len(audio_codecs_rows))

            _t = _time.perf_counter()
            sub_langs_rows = conn.execute(text(f"""
                SELECT l.label as lang_label, COUNT(DISTINCT st.file_id) as cnt
                FROM subtitle_tracks st
                JOIN languages l ON l.id = st.language_id
                {_trk_join('st')}
                GROUP BY l.label ORDER BY cnt DESC
            """), params).mappings().fetchall()

            no_sub = conn.execute(text(f"""
                SELECT COUNT(DISTINCT vm.file_id)
                FROM video_metadata vm
                {_trk_join('vm')}
                WHERE NOT EXISTS (
                    SELECT 1 FROM subtitle_tracks st WHERE st.file_id = vm.file_id
                )
            """), params).fetchone()[0]
            _perf("quality_stats", "subtitles", (_time.perf_counter() - _t) * 1000,
                  len(sub_langs_rows))

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
                {tot_cat}
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

        return JSONResponse({
            "cat_id":         cat_id,
            "total":          totals["total"] or 0,
            "total_seconds":  int(totals["total_seconds"] or 0),
            "avg_size_gb":    float(totals["avg_size_gb"] or 0),
            "total_tb":       float(totals["total_tb"] or 0),
            "codecs":         [{"label": r["video_codec"],  "count": r["cnt"]} for r in codecs],
            "resolutions":    [{"label": r["label"],        "count": r["cnt"]} for r in resolutions],
            "hdr":            [{"label": r["hdr_format"],   "count": r["cnt"]} for r in hdr],
            "audio_codecs":   [{"label": r["codec_name"].upper(), "count": r["cnt"]} for r in audio_codecs_rows],
            "audio_langs":    [{"label": r["lang_label"],   "count": r["cnt"]} for r in audio_langs_rows],
            "audio_channels": [{"label": r["label"],        "count": r["cnt"]} for r in audio_chan_rows],
            "sub_langs":      [{"label": r["lang_label"],   "count": r["cnt"]} for r in sub_langs_rows],
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
