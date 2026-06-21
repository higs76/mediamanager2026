"""
MediaManager 2026 - Router : Bibliothèque
Routes : /api/admin/library/*
"""

import logging
import time as _time

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import text

from watcher.database import engine
from watcher.utils.perf import record as _perf

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/library/categories")
def library_categories():
    """Catégories avec compteurs pour la bibliothèque utilisateur."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT c.id, c.name, c.has_seasons,
                       COUNT(DISTINCT mt.id) as title_count,
                       COUNT(DISTINCT mi.id) as file_count
                FROM categories c
                LEFT JOIN mounts m   ON m.category_id = c.id
                LEFT JOIN media_titles mt ON mt.mount_id = m.id
                LEFT JOIN media_items  mi ON mi.title_id = mt.id
                GROUP BY c.id, c.name, c.has_seasons
                ORDER BY c.name
            """)).mappings().fetchall()
        return JSONResponse([{
            "id":          r["id"],
            "name":        r["name"],
            "has_seasons": r["has_seasons"],
            "title_count": r["title_count"],
            "file_count":  r["file_count"],
        } for r in rows])
    except Exception as e:
        logger.error(f"library_categories: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/categories/stats")
def library_categories_stats():
    """Stats résolutions + codecs + taille par catégorie pour les cartes bibliothèque."""
    try:
        with engine.connect() as conn:
            cats = conn.execute(text("""
                SELECT c.id, c.name, c.has_seasons,
                       COUNT(DISTINCT mt.id)  as title_count,
                       COUNT(DISTINCT mi.id)  as file_count,
                       ROUND(SUM(mf.size_bytes)/1099511627776::numeric, 2) as total_tb
                FROM categories c
                LEFT JOIN mounts m    ON m.category_id = c.id
                LEFT JOIN media_titles mt ON mt.mount_id = m.id
                LEFT JOIN media_items  mi ON mi.title_id = mt.id
                LEFT JOIN media_files  mf ON mf.id = mi.file_id
                GROUP BY c.id, c.name, c.has_seasons
                ORDER BY c.name
            """)).mappings().fetchall()

            result = []
            for cat in cats:
                cat_id = cat["id"]

                _t = _time.perf_counter()
                res_rows = conn.execute(text("""
                    SELECT
                        CASE
                            WHEN vm.video_width >= 3840 OR vm.video_height >= 2160 THEN '4K'
                            WHEN vm.video_width >= 1920 OR vm.video_height >= 1080 THEN '1080p'
                            WHEN vm.video_width >= 1280 OR vm.video_height >= 720  THEN '720p'
                            ELSE 'SD'
                        END as label,
                        COUNT(*) as cnt
                    FROM video_metadata vm
                    JOIN media_files mf ON mf.id = vm.file_id
                    JOIN mounts m ON m.id = mf.mount_id
                    WHERE m.category_id = :cid
                      AND (vm.video_width IS NOT NULL OR vm.video_height IS NOT NULL)
                    GROUP BY label ORDER BY cnt DESC LIMIT 5
                """), {"cid": cat_id}).mappings().fetchall()
                _perf("categories_stats", "res_per_cat", (_time.perf_counter() - _t) * 1000, len(res_rows))

                total_res  = sum(r["cnt"] for r in res_rows) or 1
                resolutions = [{"label": r["label"], "pct": round(r["cnt"] / total_res * 100)} for r in res_rows]

                _t = _time.perf_counter()
                cod_rows = conn.execute(text("""
                    SELECT vm.video_codec, COUNT(*) as cnt
                    FROM video_metadata vm
                    JOIN media_files mf ON mf.id = vm.file_id
                    JOIN mounts m ON m.id = mf.mount_id
                    WHERE m.category_id = :cid AND vm.video_codec IS NOT NULL
                    GROUP BY vm.video_codec ORDER BY cnt DESC LIMIT 5
                """), {"cid": cat_id}).mappings().fetchall()
                _perf("categories_stats", "cod_per_cat", (_time.perf_counter() - _t) * 1000, len(cod_rows))

                total_cod = sum(r["cnt"] for r in cod_rows) or 1
                codecs    = [{"label": r["video_codec"].upper(), "pct": round(r["cnt"] / total_cod * 100)} for r in cod_rows]

                result.append({
                    "id":          cat["id"],
                    "name":        cat["name"],
                    "has_seasons": cat["has_seasons"],
                    "title_count": cat["title_count"],
                    "file_count":  cat["file_count"],
                    "total_tb":    float(cat["total_tb"] or 0),
                    "resolutions": resolutions,
                    "codecs":      codecs,
                })

        return JSONResponse(result)
    except Exception as e:
        logger.error(f"library_categories_stats: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/titles")
def library_titles(category_id: int, limit: int = 50, offset: int = 0, search: str = None):
    """Titres d'une catégorie avec stats résolutions/codecs/poids/vu. Paginé."""
    try:
        with engine.connect() as conn:
            params        = {"cat": category_id, "limit": limit, "offset": offset}
            search_clause = ""
            if search:
                search_clause    = "AND mt.display_name ILIKE :search"
                params["search"] = f"%{search}%"

            _t = _time.perf_counter()
            rows = conn.execute(text(f"""
                WITH pending_proposals AS (
                    SELECT COALESCE(rp.title_id, mi2.title_id) AS title_id,
                           COUNT(DISTINCT rp.id) AS cnt
                    FROM rename_proposals rp
                    LEFT JOIN media_items mi2 ON mi2.id = rp.item_id
                    WHERE rp.status = 'pending'
                    GROUP BY COALESCE(rp.title_id, mi2.title_id)
                )
                SELECT mt.id, mt.folder_name, mt.display_name,
                       mt.year, mt.folder_status,
                       COUNT(DISTINCT mi.id)                     AS file_count,
                       COUNT(DISTINCT mi.season)                 AS season_count,
                       COALESCE(pp.cnt, 0)                       AS proposals,
                       COUNT(DISTINCT mi.id)
                           FILTER (WHERE mi.watched = true)      AS watched_count,
                       ROUND(SUM(mf.size_bytes)/1073741824::numeric, 2) AS size_gb,
                       COUNT(*) OVER()                           AS total_count
                FROM media_titles mt
                LEFT JOIN media_items mi ON mi.title_id = mt.id
                LEFT JOIN media_files  mf ON mf.id = mi.file_id
                LEFT JOIN pending_proposals pp ON pp.title_id = mt.id
                WHERE mt.category_id = :cat {search_clause}
                GROUP BY mt.id, mt.folder_name, mt.display_name,
                         mt.year, mt.folder_status, pp.cnt
                ORDER BY mt.display_name
                LIMIT :limit OFFSET :offset
            """), params).mappings().fetchall()
            _perf("library_titles", "main", (_time.perf_counter() - _t) * 1000, len(rows))

            total_count = rows[0]["total_count"] if rows else 0

            if not rows:
                return JSONResponse({"items": [], "total": 0, "offset": offset, "limit": limit})

            # IDs de la page courante — utilisés pour la requête batch résolutions+codecs
            page_ids = [r["id"] for r in rows]

            # Résolutions ET codecs en une seule passe sur video_metadata
            _t = _time.perf_counter()
            vm_rows = conn.execute(text("""
                SELECT mi.title_id,
                    CASE
                        WHEN vm.video_width >= 3840 OR vm.video_height >= 2160 THEN '4K'
                        WHEN vm.video_width >= 1920 OR vm.video_height >= 1080 THEN '1080p'
                        WHEN vm.video_width >= 1280 OR vm.video_height >= 720  THEN '720p'
                        WHEN vm.video_width IS NOT NULL OR vm.video_height IS NOT NULL THEN 'SD'
                        ELSE NULL
                    END as res_label,
                    vm.video_codec,
                    COUNT(*) as cnt
                FROM media_items mi
                JOIN media_files mf ON mf.id = mi.file_id
                JOIN video_metadata vm ON vm.file_id = mf.id
                WHERE mi.title_id = ANY(:ids)
                  AND (vm.video_width IS NOT NULL OR vm.video_height IS NOT NULL OR vm.video_codec IS NOT NULL)
                GROUP BY mi.title_id, res_label, vm.video_codec
            """), {"ids": page_ids}).mappings().fetchall()
            _perf("library_titles", "vm_stats", (_time.perf_counter() - _t) * 1000, len(vm_rows))

            res_by_title: dict = {}
            cod_by_title: dict = {}
            for r in vm_rows:
                tid = r["title_id"]
                if r["res_label"]:
                    entry = res_by_title.setdefault(tid, {})
                    entry[r["res_label"]] = entry.get(r["res_label"], 0) + r["cnt"]
                if r["video_codec"]:
                    entry = cod_by_title.setdefault(tid, {})
                    entry[r["video_codec"]] = entry.get(r["video_codec"], 0) + r["cnt"]

            # Convertir en listes de tuples pour le traitement aval
            res_by_title = {tid: list(d.items()) for tid, d in res_by_title.items()}
            cod_by_title = {tid: list(d.items()) for tid, d in cod_by_title.items()}

        titles_out = []
        for r in rows:
            title_id      = r["id"]
            file_count    = r["file_count"] or 0
            watched_count = r["watched_count"] or 0
            watched_pct   = round(watched_count / file_count * 100) if file_count else 0

            res_list  = sorted(res_by_title.get(title_id, []), key=lambda x: -x[1])[:4]
            total_res = sum(x[1] for x in res_list) or 1
            resolutions = [{"label": l, "pct": round(c / total_res * 100)} for l, c in res_list]

            cod_list  = sorted(cod_by_title.get(title_id, []), key=lambda x: -x[1])[:4]
            total_cod = sum(x[1] for x in cod_list) or 1
            codecs    = [{"label": l.upper(), "pct": round(c / total_cod * 100)} for l, c in cod_list]

            titles_out.append({
                "id":            r["id"],
                "folder_name":   r["folder_name"],
                "display_name":  r["display_name"] or r["folder_name"],
                "year":          r["year"],
                "folder_status": r["folder_status"],
                "file_count":    file_count,
                "season_count":  r["season_count"],
                "proposals":     r["proposals"] or 0,
                "watched_count": watched_count,
                "watched_pct":   watched_pct,
                "size_gb":       float(r["size_gb"] or 0),
                "resolutions":   resolutions,
                "codecs":        codecs,
            })

        return JSONResponse({"items": titles_out, "total": total_count, "offset": offset, "limit": limit})
    except Exception as e:
        logger.error(f"library_titles: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/titles/{title_id}")
def library_title_detail(title_id: int):
    """Détail d'un titre — saisons et épisodes avec stats."""
    try:
        with engine.connect() as conn:
            title = conn.execute(text("""
                SELECT mt.id, mt.folder_name, mt.display_name,
                       mt.year, mt.folder_status, c.name, c.has_seasons
                FROM media_titles mt
                JOIN mounts m ON m.id = mt.mount_id
                JOIN categories c ON c.id = m.category_id
                WHERE mt.id = :id
            """), {"id": title_id}).mappings().fetchone()

            if not title:
                raise HTTPException(404, "Titre introuvable")

            items = conn.execute(text("""
                SELECT mi.id, mi.season, mi.episode, mi.episode_title,
                       mi.file_status, mi.watched,
                       mf.filename, mf.size_bytes,
                       vm.video_codec, vm.video_width, vm.video_height, vm.hdr_format,
                       vm.duration_seconds,
                       rp.proposed_name, rp.status as prop_status, rp.id as prop_id
                FROM media_items mi
                JOIN media_files mf ON mf.id = mi.file_id
                LEFT JOIN video_metadata vm ON vm.file_id = mf.id
                LEFT JOIN rename_proposals rp ON rp.item_id = mi.id
                    AND rp.status = 'pending'
                WHERE mi.title_id = :tid
                ORDER BY mi.season NULLS LAST, mi.episode NULLS LAST
            """), {"tid": title_id}).mappings().fetchall()

        # Grouper par saison + calculer stats par saison
        seasons: dict = {}
        for r in items:
            s = r["season"]
            if s not in seasons:
                seasons[s] = {"items": [], "res": {}, "cod": {}, "size": 0, "watched": 0}

            seasons[s]["items"].append({
                "item_id":       r["id"],
                "season":        r["season"],
                "episode":       r["episode"],
                "episode_title": r["episode_title"],
                "file_status":   r["file_status"],
                "watched":       r["watched"],
                "filename":      r["filename"],
                "size_bytes":    r["size_bytes"],
                "codec":         r["video_codec"],
                "height":        r["video_height"],
                "hdr":           r["hdr_format"],
                "duration":      r["duration_seconds"],
                "proposed_name": r["proposed_name"],
                "prop_status":   r["prop_status"],
                "prop_id":       r["prop_id"],
            })
            seasons[s]["size"] += (r["size_bytes"] or 0)
            if r["watched"]:
                seasons[s]["watched"] += 1
            if r["video_width"] or r["video_height"]:
                w, h = r["video_width"] or 0, r["video_height"] or 0
                label = (
                    '4K'    if w >= 3840 or h >= 2160 else
                    '1080p' if w >= 1920 or h >= 1080 else
                    '720p'  if w >= 1280 or h >= 720  else 'SD'
                )
                seasons[s]["res"][label] = seasons[s]["res"].get(label, 0) + 1
            if r["video_codec"]:
                seasons[s]["cod"][r["video_codec"]] = seasons[s]["cod"].get(r["video_codec"], 0) + 1

        def _pct_list(d: dict, limit: int = 4) -> list:
            total = sum(d.values()) or 1
            top   = sorted(d.items(), key=lambda x: -x[1])[:limit]
            return [{"label": k, "pct": round(v / total * 100)} for k, v in top]

        seasons_out:   dict = {}
        all_res:       dict = {}
        all_cod:       dict = {}
        total_size     = 0
        total_watched  = 0
        total_items    = 0

        for s, data in sorted(seasons.items(), key=lambda x: (x[0] is None, x[0])):
            n = len(data["items"])
            seasons_out[str(s)] = {
                "items":       data["items"],
                "file_count":  n,
                "watched_pct": round(data["watched"] / n * 100) if n else 0,
                "size_gb":     round(data["size"] / 1073741824, 2),
                "resolutions": _pct_list(data["res"]),
                "codecs":      _pct_list(data["cod"]),
            }
            for k, v in data["res"].items():
                all_res[k] = all_res.get(k, 0) + v
            for k, v in data["cod"].items():
                all_cod[k] = all_cod.get(k, 0) + v
            total_size    += data["size"]
            total_watched += data["watched"]
            total_items   += n

        return JSONResponse({
            "id":              title["id"],
            "folder_name":     title["folder_name"],
            "display_name":    title["display_name"] or title["folder_name"],
            "year":            title["year"],
            "folder_status":   title["folder_status"],
            "category":        title["name"],
            "has_seasons":     title["has_seasons"],
            "file_count":      total_items,
            "proposals_total": sum(1 for it in items if it["prop_id"]),
            "watched_pct":     round(total_watched / total_items * 100) if total_items else 0,
            "size_gb":         round(total_size / 1073741824, 2),
            "resolutions":     _pct_list(all_res),
            "codecs":          _pct_list(all_cod),
            "seasons":         seasons_out,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"library_title_detail: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/proposals")
def library_proposals(category_id: int = None):
    """Titres ayant des propositions de renommage en attente."""
    try:
        with engine.connect() as conn:
            params     = {}
            cat_filter = ""
            if category_id:
                cat_filter     = "AND c.id = :cat_id"
                params["cat_id"] = category_id

            rows = conn.execute(text(f"""
                SELECT
                    mt.id,
                    mt.display_name,
                    mt.folder_name,
                    mt.folder_status,
                    c.name,
                    c.has_seasons,
                    COUNT(rp.id) as proposal_count
                FROM media_titles mt
                JOIN mounts m ON m.id = mt.mount_id
                JOIN categories c ON c.id = m.category_id
                LEFT JOIN media_items mi ON mi.title_id = mt.id
                LEFT JOIN rename_proposals rp ON (
                    rp.title_id = mt.id
                    OR rp.item_id = mi.id
                )
                WHERE rp.status = 'pending'
                {cat_filter}
                GROUP BY mt.id, mt.display_name, mt.folder_name,
                         mt.folder_status, c.name, c.has_seasons
                ORDER BY c.name, mt.display_name
            """), params).mappings().fetchall()

        return JSONResponse([{
            "title_id":       r["id"],
            "display_name":   r["display_name"] or r["folder_name"],
            "folder_name":    r["folder_name"],
            "folder_status":  r["folder_status"],
            "category":       r["name"],
            "has_seasons":    r["has_seasons"],
            "proposal_count": r["proposal_count"],
        } for r in rows])
    except Exception as e:
        logger.error(f"library_proposals: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/proposals/{title_id}")
def library_proposals_detail(title_id: int):
    """Détail des propositions pour un titre — dossier + fichiers par saison."""
    try:
        with engine.connect() as conn:
            title = conn.execute(text("""
                SELECT mt.id, mt.display_name, mt.folder_name,
                       mt.folder_status, c.name, c.has_seasons,
                       nt.sep1, nt.sep2, nt.prefix_season, nt.digits_season,
                       nt.sep_se, nt.prefix_episode, nt.digits_episode,
                       nt.sep_year, nt.year_format, mt.year
                FROM media_titles mt
                JOIN mounts m ON m.id = mt.mount_id
                JOIN categories c ON c.id = m.category_id
                LEFT JOIN naming_templates nt ON nt.id = c.template_id
                WHERE mt.id = :tid
            """), {"tid": title_id}).mappings().fetchone()

            if not title:
                raise HTTPException(404, "Titre introuvable")

            title_prop = conn.execute(text("""
                SELECT id, current_name, proposed_name, status
                FROM rename_proposals
                WHERE title_id = :tid AND item_id IS NULL
                ORDER BY created_at DESC LIMIT 1
            """), {"tid": title_id}).mappings().fetchone()

            item_props = conn.execute(text("""
                SELECT rp.id, rp.current_name, rp.proposed_name, rp.status,
                       mi.season, mi.episode, mi.episode_title, mi.id as item_id,
                       mf.filename, mf.size_bytes,
                       vm.video_codec, vm.video_height, vm.hdr_format
                FROM media_items mi
                JOIN rename_proposals rp ON rp.item_id = mi.id
                    AND rp.status = 'pending'
                JOIN media_files mf ON mf.id = mi.file_id
                LEFT JOIN video_metadata vm ON vm.file_id = mf.id
                WHERE mi.title_id = :tid
                ORDER BY mi.season NULLS LAST, mi.episode NULLS LAST
            """), {"tid": title_id}).mappings().fetchall()

        seasons: dict = {}
        for r in item_props:
            s = r["season"]
            if s not in seasons:
                seasons[s] = []
            seasons[s].append({
                "prop_id":       r["id"],
                "current_name":  r["current_name"],
                "proposed_name": r["proposed_name"],
                "status":        r["status"],
                "season":        r["season"],
                "episode":       r["episode"],
                "episode_title": r["episode_title"],
                "item_id":       r["item_id"],
                "filename":      r["filename"],
                "size_bytes":    r["size_bytes"],
                "codec":         r["video_codec"],
                "height":        r["video_height"],
                "hdr":           r["hdr_format"],
            })

        tpl = {
            "sep1":           title["sep1"],
            "sep2":           title["sep2"],
            "prefix_season":  title["prefix_season"],
            "digits_season":  title["digits_season"],
            "sep_se":         title["sep_se"],
            "prefix_episode": title["prefix_episode"],
            "digits_episode": title["digits_episode"],
            "sep_year":       title["sep_year"],
            "year_format":    title["year_format"],
        }

        return JSONResponse({
            "title_id":      title["id"],
            "display_name":  title["display_name"] or title["folder_name"],
            "folder_name":   title["folder_name"],
            "folder_status": title["folder_status"],
            "category":      title["name"],
            "has_seasons":   title["has_seasons"],
            "year":          title["year"],
            "template":      tpl,
            "title_proposal": {
                "prop_id":       title_prop["id"],
                "current_name":  title_prop["current_name"],
                "proposed_name": title_prop["proposed_name"],
                "status":        title_prop["status"],
            } if title_prop else None,
            "seasons": {
                str(k): v for k, v in sorted(
                    seasons.items(),
                    key=lambda x: (x[0] is None, x[0])
                )
            },
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"library_proposals_detail: {e}")
        raise HTTPException(500, str(e))


@router.post("/library/proposals/{prop_id}/accept")
def accept_proposal(prop_id: int, data: dict = Body(...)):
    """Accepte une proposition avec le nom final choisi par l'utilisateur.

    update_mkv : bool — mettre à jour le tag title dans le fichier MKV
    """
    final_name = (data.get("final_name") or "").strip()
    update_mkv = data.get("update_mkv", False)

    if not final_name:
        raise HTTPException(400, "final_name obligatoire")
    try:
        with engine.connect() as conn:
            rp = conn.execute(text(
                "SELECT id, status FROM rename_proposals WHERE id = :id"
            ), {"id": prop_id}).mappings().fetchone()
            if not rp:
                raise HTTPException(404, "Proposition introuvable")
            if rp["status"] != 'pending':
                raise HTTPException(400, f"Proposition déjà traitée : {rp['status']}")

            conn.execute(text("""
                UPDATE rename_proposals
                SET status = 'accepted',
                    custom_name = :name,
                    resolved_at = NOW()
                WHERE id = :id
            """), {"name": final_name, "id": prop_id})
            conn.commit()

        return JSONResponse({
            "success":    True,
            "prop_id":    prop_id,
            "final_name": final_name,
            "update_mkv": update_mkv,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"accept_proposal: {e}")
        raise HTTPException(500, str(e))


@router.post("/library/proposals/{prop_id}/reject")
def reject_proposal(prop_id: int):
    """Rejette une proposition — ne sera plus reproposée."""
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE rename_proposals
                SET status = 'rejected', resolved_at = NOW()
                WHERE id = :id AND status = 'pending'
            """), {"id": prop_id})
            conn.commit()
        return JSONResponse({"success": True, "prop_id": prop_id})
    except Exception as e:
        logger.error(f"reject_proposal: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/items/{item_id}")
def library_item_detail(item_id: int):
    """Fiche détail complète d'un fichier média."""
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT
                    mi.id            AS item_id,
                    mi.season        AS season,
                    mi.episode       AS episode,
                    mi.episode_title AS episode_title,
                    mi.watched       AS watched,
                    mi.watched_at    AS watched_at,
                    mi.file_status   AS file_status,
                    mt.id            AS title_id,
                    mt.display_name  AS title_name,
                    mt.folder_name   AS folder_name,
                    c.name           AS category,
                    c.has_seasons    AS has_seasons,
                    mf.id            AS file_id,
                    mf.filename      AS filename,
                    mf.path_relative AS path_relative,
                    mf.size_bytes    AS size_bytes,
                    mf.extension     AS extension,
                    mf.disk_status   AS disk_status,
                    vm.duration_seconds AS duration_seconds,
                    vm.video_codec      AS video_codec,
                    vm.video_bitrate    AS video_bitrate,
                    vm.video_width      AS video_width,
                    vm.video_height     AS video_height,
                    vm.video_fps        AS video_fps,
                    vm.audio_codecs           AS audio_codecs,
                    vm.audio_bitrates         AS audio_bitrates,
                    vm.audio_profiles         AS audio_profiles,
                    vm.audio_languages        AS audio_languages,
                    vm.audio_channels         AS audio_channels,
                    vm.audio_channel_layouts  AS audio_channel_layouts,
                    vm.subtitle_languages     AS subtitle_languages,
                    vm.subtitle_count         AS subtitle_count,
                    vm.container_format       AS container_format,
                    vm.hdr_format             AS hdr_format,
                    vm.color_space            AS color_space,
                    rp.id            AS prop_id,
                    rp.proposed_name AS proposed_name,
                    rp.status        AS prop_status
                FROM media_items mi
                JOIN media_titles mt ON mt.id = mi.title_id
                JOIN mounts m ON m.id = mt.mount_id
                JOIN categories c ON c.id = m.category_id
                JOIN media_files mf ON mf.id = mi.file_id
                LEFT JOIN video_metadata vm ON vm.file_id = mf.id
                LEFT JOIN rename_proposals rp ON rp.item_id = mi.id
                    AND rp.status = 'pending'
                WHERE mi.id = :id
            """), {"id": item_id}).mappings().fetchone()

            if not row:
                raise HTTPException(404, "Fichier introuvable")

        def split_semi(val):
            return [x for x in (val or "").split(";") if x]

        def audio_format_label(codec: str, profile: str) -> str:
            c = (codec or "").lower()
            p = (profile or "").lower()
            if c == "truehd":
                return "TrueHD Atmos" if "atmos" in p else "TrueHD"
            if c == "eac3":
                return "Dolby Atmos" if "atmos" in p else "Dolby Digital+"
            if c == "ac3":
                return "Dolby Digital"
            if c == "dts":
                if "ma" in p or "master" in p:  return "DTS-HD MA"
                if ":x" in p or "hra" in p:     return "DTS:X"
                if "express" in p:               return "DTS Express"
                if "es" in p:                    return "DTS-ES"
                if "hd" in p:                    return "DTS-HD"
                return "DTS"
            if c == "aac":   return "AAC"
            if c == "mp3":   return "MP3"
            if c == "flac":  return "FLAC"
            if c == "opus":  return "Opus"
            if c.startswith("pcm"): return "PCM"
            return c.upper()

        codecs   = split_semi(row["audio_codecs"])
        bitrates = split_semi(row["audio_bitrates"])
        profiles = split_semi(row["audio_profiles"])
        formats  = [
            audio_format_label(codecs[i] if i < len(codecs) else "",
                               profiles[i] if i < len(profiles) else "")
            for i in range(len(codecs))
        ]

        return JSONResponse({
            "item_id":       row["item_id"],
            "season":        row["season"],
            "episode":       row["episode"],
            "episode_title": row["episode_title"],
            "watched":       row["watched"],
            "watched_at":    str(row["watched_at"]) if row["watched_at"] else None,
            "file_status":   row["file_status"],
            "title_id":      row["title_id"],
            "title_name":    row["title_name"],
            "folder_name":   row["folder_name"],
            "category":      row["category"],
            "has_seasons":   row["has_seasons"],
            "file_id":       row["file_id"],
            "filename":      row["filename"],
            "path_relative": row["path_relative"],
            "size_bytes":    row["size_bytes"],
            "extension":     row["extension"],
            "disk_status":   row["disk_status"],
            "video": {
                "duration_seconds": row["duration_seconds"],
                "codec":            row["video_codec"],
                "bitrate":          row["video_bitrate"],
                "width":            row["video_width"],
                "height":           row["video_height"],
                "fps":              row["video_fps"],
                "container":        row["container_format"],
                "hdr_format":       row["hdr_format"],
                "color_space":      row["color_space"],
            },
            "audio": {
                "codecs":    codecs,
                "formats":   formats,
                "bitrates":  [int(b) if b else None for b in bitrates],
                "languages": split_semi(row["audio_languages"]),
                "channels":  split_semi(row["audio_channels"]),
                "layouts":   split_semi(row["audio_channel_layouts"]),
            },
            "subtitles": {
                "languages": split_semi(row["subtitle_languages"]),
                "count":     row["subtitle_count"] or 0,
            },
            "proposal": {
                "prop_id":       row["prop_id"],
                "proposed_name": row["proposed_name"],
                "status":        row["prop_status"],
            } if row["prop_id"] else None,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"library_item_detail: {e}")
        raise HTTPException(500, str(e))


@router.post("/library/items/{item_id}/watched")
def toggle_watched(item_id: int, data: dict = Body(...)):
    """Bascule le statut vu/non vu d'un fichier."""
    watched = data.get("watched", True)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("""
                UPDATE media_items
                SET watched = :w,
                    watched_at = CASE WHEN :w THEN NOW() ELSE NULL END
                WHERE id = :id
                RETURNING id
            """), {"w": watched, "id": item_id}).fetchone()
            conn.commit()
        if not result:
            raise HTTPException(404, "Fichier introuvable")
        return JSONResponse({"success": True, "item_id": item_id, "watched": watched})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"toggle_watched: {e}")
        raise HTTPException(500, str(e))
