"""
MediaManager 2026 - Router : Catégories & Templates de nommage
Routes : /api/admin/categories, /api/admin/naming-templates
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from watcher.database import engine

logger = logging.getLogger(__name__)

router = APIRouter()


class CategoryCreate(BaseModel):
    name:        str
    has_seasons: bool = True
    template_id: Optional[int] = None


@router.get("/categories")
def list_categories():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, name, has_seasons, template_id
                FROM categories ORDER BY name
            """)).mappings().fetchall()
        cats = [dict(r) for r in rows]
        return JSONResponse({
            "categories": [c["name"] for c in cats],
            "detail":     cats
        })
    except Exception as e:
        err = str(e)
        if "does not exist" in err or "UndefinedTable" in err:
            logger.warning("categories: table absente, init BDD en attente")
            return JSONResponse({"categories": [], "detail": []})
        logger.error(f"list_categories: {e}")
        raise HTTPException(500, err)


@router.post("/categories", status_code=201)
def create_category(payload: CategoryCreate):
    name = payload.name.strip().lower()
    if not name:
        raise HTTPException(400, "Le nom ne peut pas être vide")
    try:
        with engine.connect() as conn:
            existing = conn.execute(
                text("SELECT id FROM categories WHERE name = :n"), {"n": name}
            ).fetchone()
            if existing:
                raise HTTPException(400, f"La catégorie '{name}' existe déjà")

            template_id = payload.template_id
            if not template_id:
                tpl_type = 'seasonal' if payload.has_seasons else 'noseasonal'
                tpl_row = conn.execute(text("""
                    SELECT id FROM naming_templates
                    WHERE type = :t AND is_default = true
                    ORDER BY id LIMIT 1
                """), {"t": tpl_type}).fetchone()
                if tpl_row:
                    template_id = tpl_row[0]

            row = conn.execute(text("""
                INSERT INTO categories (name, has_seasons, template_id)
                VALUES (:n, :hs, :tid)
                RETURNING id, name, has_seasons, template_id
            """), {"n": name, "hs": payload.has_seasons, "tid": template_id}).mappings().fetchone()
            conn.commit()
        return JSONResponse(dict(row))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_category: {e}")
        raise HTTPException(500, str(e))


@router.get("/naming-templates")
def list_naming_templates(type: str = None):
    """type : 'seasonal' | 'noseasonal' | None (tous)"""
    _COLS = """
        id, type, is_default,
        sep1, sep2, prefix_season, digits_season,
        sep_se, prefix_episode, digits_episode,
        folder_prefix, folder_digits, special_folder,
        sep_year, year_format, bonus_folder
    """
    try:
        with engine.connect() as conn:
            if type:
                rows = conn.execute(text(f"""
                    SELECT {_COLS} FROM naming_templates
                    WHERE type = :t ORDER BY is_default DESC, id
                """), {"t": type}).mappings().fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT {_COLS} FROM naming_templates
                    ORDER BY type, is_default DESC, id
                """)).mappings().fetchall()

        def _preview(r):
            if r["type"] == 'seasonal':
                sep1  = r["sep1"]  or ' - '
                sep2  = r["sep2"]  or ' - '
                prefS = r["prefix_season"]  or ''
                digS  = r["digits_season"]  or 2
                sepSE = r["sep_se"]         or 'x'
                prefE = r["prefix_episode"] or ''
                digE  = r["digits_episode"] or 2
                s = str(1).zfill(digS)
                e = str(1).zfill(digE)
                return f"Série{sep1}{prefS}{s}{sepSE}{prefE}{e}{sep2}Titre.mkv"
            else:
                sep  = r["sep_year"]    or ' '
                fmt  = r["year_format"] or 'paren'
                year = '(2010)' if fmt == 'paren' else '2010' if fmt == 'plain' else ''
                return f"Titre{sep}{year}.mkv" if year else "Titre.mkv"

        return JSONResponse([{**dict(r), "preview": _preview(r)} for r in rows])
    except Exception as e:
        logger.error(f"list_naming_templates: {e}")
        raise HTTPException(500, str(e))


@router.post("/naming-templates", status_code=201)
def create_naming_template(data: dict = Body(...)):
    tpl_type = (data.get("type") or "").strip()
    if tpl_type not in ("seasonal", "noseasonal"):
        raise HTTPException(400, "type doit être 'seasonal' ou 'noseasonal'")
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                INSERT INTO naming_templates (
                    type, is_default,
                    sep1, sep2, prefix_season, digits_season,
                    sep_se, prefix_episode, digits_episode,
                    folder_prefix, folder_digits, special_folder,
                    sep_year, year_format, bonus_folder
                ) VALUES (
                    :type, false,
                    :sep1, :sep2, :prefix_season, :digits_season,
                    :sep_se, :prefix_episode, :digits_episode,
                    :folder_prefix, :folder_digits, :special_folder,
                    :sep_year, :year_format, :bonus_folder
                )
                RETURNING id
            """), {
                "type":           tpl_type,
                "sep1":           data.get("sep1"),
                "sep2":           data.get("sep2"),
                "prefix_season":  data.get("prefix_season"),
                "digits_season":  data.get("digits_season"),
                "sep_se":         data.get("sep_se"),
                "prefix_episode": data.get("prefix_episode"),
                "digits_episode": data.get("digits_episode"),
                "folder_prefix":  data.get("folder_prefix"),
                "folder_digits":  data.get("folder_digits"),
                "special_folder": data.get("special_folder"),
                "sep_year":       data.get("sep_year"),
                "year_format":    data.get("year_format"),
                "bonus_folder":   data.get("bonus_folder"),
            }).fetchone()
            conn.commit()
        return JSONResponse({"id": row[0]})
    except Exception as e:
        err = str(e)
        if "unique" in err.lower():
            raise HTTPException(400, "Ce template existe déjà")
        logger.error(f"create_naming_template: {e}")
        raise HTTPException(500, err)
