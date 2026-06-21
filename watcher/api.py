"""
MediaManager 2026 - API Admin : Montages & Catégories
Toutes les routes /api/admin/...
"""

import logging
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from watcher.database import engine
from watcher.config import MOUNT_BASE_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")


# ── Schémas Pydantic ──────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name:        str
    has_seasons: bool = True
    template_id: Optional[int] = None

class MountCreate(BaseModel):
    mount_type:    str            # "smb" ou "nfs"
    category_name: str            # nom — l'API résout ou crée la catégorie
    active:        bool = True
    # Commun
    server:        Optional[str] = None
    # SMB
    share:         Optional[str] = None
    username:      Optional[str] = None
    password:      Optional[str] = None
    domain:        str = "WORKGROUP"
    smb_version:   str = "3.0"
    smb_options:   str = "uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8"
    # NFS
    export_path:   Optional[str] = None
    nfs_version:   int = 4
    nfs_options:   str = "rw,soft,timeo=30"

class MountUpdate(BaseModel):
    active:        Optional[bool] = None
    server:        Optional[str]  = None
    share:         Optional[str]  = None
    username:      Optional[str]  = None
    password:      Optional[str]  = None
    domain:        Optional[str]  = None
    smb_version:   Optional[str]  = None
    smb_options:   Optional[str]  = None
    export_path:   Optional[str]  = None
    nfs_version:   Optional[int]  = None
    nfs_options:   Optional[str]  = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_local_path(mount_id: int, category_name: str) -> str:
    """
    Règle de nommage : {MOUNT_BASE}/{category}/{id}-{category}
    Ex : /home/mediamanager/MediaManagerMnt/series/1-series
    """
    return str(Path(MOUNT_BASE_PATH) / category_name / f"{mount_id}-{category_name}")


def _is_mounted(local_path: str) -> bool:
    """Vérifie si un chemin est monté via /proc/mounts."""
    try:
        with open("/proc/mounts") as f:
            return any(local_path == line.split()[1]
                       for line in f if len(line.split()) >= 2)
    except Exception:
        return False


def _get_mount_full(conn, mount_id: int) -> Optional[dict]:
    """Retourne un montage complet (header + détails type) ou None."""
    row = conn.execute(text("""
        SELECT m.id, m.mount_type, m.category_id, c.name AS category_name,
               m.local_path, m.active, m.last_mount_at, m.last_error,
               m.created_at, m.updated_at
        FROM mounts m
        JOIN categories c ON c.id = m.category_id
        WHERE m.id = :id
    """), {"id": mount_id}).fetchone()

    if not row:
        return None

    result = {
        "id":            row[0],
        "mount_type":    row[1],
        "category_id":   row[2],
        "category_name": row[3],
        "local_path":    row[4],
        "active":        row[5],
        "last_mount_at": str(row[6]) if row[6] else None,
        "last_error":    row[7],
        "created_at":    str(row[8]),
        "updated_at":    str(row[9]),
        "is_mounted":    _is_mounted(row[4]),
    }

    if row[1] == "smb":
        smb = conn.execute(text("""
            SELECT server, share, username, domain, smb_version, mount_options
            FROM mount_smb WHERE mount_id = :id
        """), {"id": mount_id}).fetchone()
        if smb:
            result.update({
                "server": smb[0], "share": smb[1],
                "username": smb[2], "domain": smb[3],
                "smb_version": smb[4], "smb_options": smb[5],
            })
    elif row[1] == "nfs":
        nfs = conn.execute(text("""
            SELECT server, export_path, nfs_version, mount_options
            FROM mount_nfs WHERE mount_id = :id
        """), {"id": mount_id}).fetchone()
        if nfs:
            result.update({
                "server": nfs[0], "export_path": nfs[1],
                "nfs_version": nfs[2], "nfs_options": nfs[3],
            })

    return result


# ── Config ───────────────────────────────────────────────────────────────────

@router.get("/config")
def get_config_all():
    """Retourne toutes les clés de config."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT key, value, description FROM config ORDER BY key"
            )).fetchall()
        return JSONResponse([{
            "key":         r[0],
            "value":       r[1],
            "description": r[2],
        } for r in rows])
    except Exception as e:
        logger.error(f"get_config_all: {e}")
        raise HTTPException(500, str(e))


@router.put("/config/{key}")
def update_config(key: str, data: dict = Body(...)):
    """Met à jour une valeur de config."""
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


# ── Catégories ────────────────────────────────────────────────────────────────

@router.get("/categories")
def list_categories():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, name, has_seasons, template_id
                FROM categories ORDER BY name
            """)).fetchall()
        cats = [{"id": r[0], "name": r[1], "has_seasons": r[2], "template_id": r[3]} for r in rows]
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

            # Si pas de template fourni, prendre le premier par défaut
            # selon le type saisonnable/non
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
            """), {
                "n":   name,
                "hs":  payload.has_seasons,
                "tid": template_id,
            }).fetchone()
            conn.commit()
        return JSONResponse({
            "id":          row[0],
            "name":        row[1],
            "has_seasons": row[2],
            "template_id": row[3],
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_category: {e}")
        raise HTTPException(500, str(e))

@router.get("/naming-templates")
def list_naming_templates(type: str = None):
    """
    Retourne les templates de nommage.
    type : 'seasonal' | 'noseasonal' | None (tous)
    """
    try:
        with engine.connect() as conn:
            if type:
                rows = conn.execute(text("""
                    SELECT id, type, is_default,
                           sep1, sep2, prefix_season, digits_season,
                           sep_se, prefix_episode, digits_episode,
                           folder_prefix, folder_digits, special_folder,
                           sep_year, year_format, bonus_folder
                    FROM naming_templates
                    WHERE type = :t ORDER BY is_default DESC, id
                """), {"t": type}).fetchall()
            else:
                rows = conn.execute(text("""
                    SELECT id, type, is_default,
                           sep1, sep2, prefix_season, digits_season,
                           sep_se, prefix_episode, digits_episode,
                           folder_prefix, folder_digits, special_folder,
                           sep_year, year_format, bonus_folder
                    FROM naming_templates
                    ORDER BY type, is_default DESC, id
                """)).fetchall()

        def _preview(r):
            """Génère un exemple de nom de fichier pour ce template."""
            if r[1] == 'seasonal':
                sep1    = r[3] or ' - '
                sep2    = r[4] or ' - '
                prefS   = r[5] or ''
                digS    = r[6] or 2
                sepSE   = r[7] or 'x'
                prefE   = r[8] or ''
                digE    = r[9] or 2
                s = str(1).zfill(digS)
                e = str(1).zfill(digE)
                return f"Série{sep1}{prefS}{s}{sepSE}{prefE}{e}{sep2}Titre.mkv"
            else:
                sep  = r[13] or ' '
                fmt  = r[14] or 'paren'
                year = '(2010)' if fmt == 'paren' else '2010' if fmt == 'plain' else ''
                return f"Titre{sep}{year}.mkv" if year else "Titre.mkv"

        return JSONResponse([{
            "id":             r[0],
            "type":           r[1],
            "is_default":     r[2],
            "sep1":           r[3],
            "sep2":           r[4],
            "prefix_season":  r[5],
            "digits_season":  r[6],
            "sep_se":         r[7],
            "prefix_episode": r[8],
            "digits_episode": r[9],
            "folder_prefix":  r[10],
            "folder_digits":  r[11],
            "special_folder": r[12],
            "sep_year":       r[13],
            "year_format":    r[14],
            "bonus_folder":   r[15],
            "preview":        _preview(r),
        } for r in rows])
    except Exception as e:
        logger.error(f"list_naming_templates: {e}")
        raise HTTPException(500, str(e))
    
@router.post("/naming-templates", status_code=201)
def create_naming_template(data: dict = Body(...)):
    """Crée un nouveau template de nommage utilisateur."""
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
        if "unique" in err.lower() or "UNIQUE" in err:
            raise HTTPException(400, "Ce template existe déjà")
        logger.error(f"create_naming_template: {e}")
        raise HTTPException(500, err)    


# ── Montages ──────────────────────────────────────────────────────────────────

@router.get("/mounts")
def list_mounts():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id FROM mounts ORDER BY category_id, id"
            )).fetchall()
            mounts = [_get_mount_full(conn, r[0]) for r in rows]
        return JSONResponse({"mounts": mounts, "count": len(mounts)})
    except Exception as e:
        err = str(e)
        # Table absente = BDD pas encore initialisée → retourner vide, pas 500
        if "does not exist" in err or "UndefinedTable" in err:
            logger.warning("mounts: table absente, init BDD en attente")
            return JSONResponse({"mounts": [], "count": 0})
        logger.error(f"list_mounts: {e}")
        raise HTTPException(500, err)


@router.get("/mounts/status")
def mounts_status():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT m.id, m.local_path, c.name
                FROM mounts m JOIN categories c ON c.id = m.category_id
                WHERE m.active = true
            """)).fetchall()
        status  = [{"id": r[0], "local_path": r[1], "category": r[2],
                    "is_mounted": _is_mounted(r[1])} for r in rows]
        mounted = sum(1 for s in status if s["is_mounted"])
        return JSONResponse({
            "total": len(status), "mounted": mounted,
            "missing": len(status) - mounted, "mounts": status
        })
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/mounts", status_code=201)
def create_mount(payload: MountCreate):
    """Crée un montage en BDD. Utiliser /sync ensuite pour monter."""
    if payload.mount_type not in ("smb", "nfs"):
        raise HTTPException(400, "mount_type doit être 'smb' ou 'nfs'")

    cat_name = payload.category_name.strip().lower()
    if not cat_name:
        raise HTTPException(400, "category_name ne peut pas être vide")

    try:
        with engine.connect() as conn:
            # Résoudre la catégorie — la créer si elle n'existe pas
            cat = conn.execute(
                text("SELECT id, name FROM categories WHERE name = :n"),
                {"n": cat_name}
            ).fetchone()
            if not cat:
                cat = conn.execute(
                    text("INSERT INTO categories (name) VALUES (:n) RETURNING id, name"),
                    {"n": cat_name}
                ).fetchone()
                logger.info(f"Catégorie créée automatiquement : {cat_name}")

            category_id   = cat[0]
            category_name = cat[1]

            # Header mounts (local_path provisoire, mis à jour juste après)
            row = conn.execute(text("""
                INSERT INTO mounts (mount_type, category_id, local_path, active)
                VALUES (:type, :cat, '', :active)
                RETURNING id
            """), {"type": payload.mount_type, "cat": category_id,
                   "active": payload.active}).fetchone()
            mount_id = row[0]

            local_path = _build_local_path(mount_id, category_name)
            conn.execute(
                text("UPDATE mounts SET local_path = :p WHERE id = :id"),
                {"p": local_path, "id": mount_id}
            )

            if payload.mount_type == "smb":
                if not payload.server or not payload.share:
                    raise HTTPException(400, "server et share sont requis pour SMB")
                conn.execute(text("""
                    INSERT INTO mount_smb
                        (mount_id, server, share, username, password,
                         domain, smb_version, mount_options)
                    VALUES (:mid, :srv, :shr, :usr, :pwd, :dom, :ver, :opt)
                """), {"mid": mount_id, "srv": payload.server, "shr": payload.share,
                       "usr": payload.username, "pwd": payload.password,
                       "dom": payload.domain, "ver": payload.smb_version,
                       "opt": payload.smb_options})
            else:
                if not payload.server or not payload.export_path:
                    raise HTTPException(400, "server et export_path sont requis pour NFS")
                conn.execute(text("""
                    INSERT INTO mount_nfs
                        (mount_id, server, export_path, nfs_version, mount_options)
                    VALUES (:mid, :srv, :exp, :ver, :opt)
                """), {"mid": mount_id, "srv": payload.server,
                       "exp": payload.export_path,
                       "ver": payload.nfs_version, "opt": payload.nfs_options})

            conn.commit()
            result = _get_mount_full(conn, mount_id)
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        if "uq_smb_source" in err or "uq_nfs_source" in err:
            raise HTTPException(400, "Cette source est déjà utilisée par un autre montage")
        logger.error(f"create_mount: {e}")
        raise HTTPException(500, err)


@router.put("/mounts/{mount_id}")
def update_mount(mount_id: int, payload: MountUpdate):
    try:
        with engine.connect() as conn:
            mount = conn.execute(
                text("SELECT mount_type FROM mounts WHERE id = :id"), {"id": mount_id}
            ).fetchone()
            if not mount:
                raise HTTPException(404, f"Montage {mount_id} introuvable")

            if payload.active is not None:
                conn.execute(
                    text("UPDATE mounts SET active = :a WHERE id = :id"),
                    {"a": payload.active, "id": mount_id}
                )

            if mount[0] == "smb":
                updates = {k: v for k, v in {
                    "server": payload.server, "share": payload.share,
                    "username": payload.username, "password": payload.password,
                    "domain": payload.domain, "smb_version": payload.smb_version,
                    "mount_options": payload.smb_options,
                }.items() if v is not None}
                if updates:
                    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                    updates["mid"] = mount_id
                    conn.execute(
                        text(f"UPDATE mount_smb SET {set_clause} WHERE mount_id = :mid"),
                        updates
                    )
            else:
                updates = {k: v for k, v in {
                    "server": payload.server, "export_path": payload.export_path,
                    "nfs_version": payload.nfs_version,
                    "mount_options": payload.nfs_options,
                }.items() if v is not None}
                if updates:
                    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
                    updates["mid"] = mount_id
                    conn.execute(
                        text(f"UPDATE mount_nfs SET {set_clause} WHERE mount_id = :mid"),
                        updates
                    )

            conn.commit()
            result = _get_mount_full(conn, mount_id)
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        err = str(e)
        if "uq_smb_source" in err or "uq_nfs_source" in err:
            raise HTTPException(400, "Cette source est déjà utilisée par un autre montage")
        logger.error(f"update_mount: {e}")
        raise HTTPException(500, err)

@router.delete("/mounts/{mount_id}", status_code=204)
def delete_mount(mount_id: int):
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM mounts WHERE id = :id"), {"id": mount_id}
            )
            conn.commit()
            if result.rowcount == 0:
                raise HTTPException(404, f"Montage {mount_id} introuvable")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Synchronisation ───────────────────────────────────────────────────────────

def _write_creds_file(username: str, password: str, domain: str) -> str:
    """
    Ecrit un fichier de credentials temporaire pour SMB.
    Evite les problemes avec les caracteres speciaux dans les mots de passe
    (#, !, $, espaces...) qui sont interpretes par le shell ou le parser d'options CIFS.
    Retourne le chemin du fichier cree.
    """
    import tempfile, os
    fd, path = tempfile.mkstemp(prefix="mm_creds_", suffix=".tmp")
    try:
        content = f"username={username}\npassword={password}\ndomain={domain}\n"
        os.write(fd, content.encode("utf-8"))
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return path

def _resolve_server(server: str) -> tuple:
    """
    Resout le nom de serveur en IP.
    Retourne (nom_saisi, ip_resolue) pour aider au diagnostic DNS.
    """
    import socket
    # Nettoyer le nom : retirer les // et tout ce qui suit le nom
    name = server.lstrip("/").split("/")[0]
    try:
        ip = socket.gethostbyname(name)
        return name, ip
    except Exception:
        return name, None


def _do_mount(local_path: str, mount_type: str, params: dict) -> tuple:
    """Exécute mount. Retourne (succès, message_erreur)."""
    import os
    os.makedirs(local_path, exist_ok=True)

    creds_file = None

    try:
        if mount_type == "smb":
            base_options = params.get("mount_options", "")
            smb_version  = params.get("smb_version", "3.0")
 
            if params.get("username"):
                # Fichier credentials : gere tous les caracteres speciaux (#, !, $...)
                # sans risque d'interpretation par le shell ou le parser d'options
                creds_file = _write_creds_file(
                    params["username"],
                    params.get("password") or "",
                    params.get("domain", "WORKGROUP")
                )
                options = f"{base_options},credentials={creds_file},vers={smb_version}"
            else:
                options = f"{base_options},guest,vers={smb_version}"
 
            remote = f"{params['server']}/{params['share'].lstrip('/')}"
            cmd = ["/usr/bin/sudo", "/bin/mount", "-t", "cifs",
                   remote, local_path, "-o", options]
        else:
            options = params.get("mount_options", "rw,soft,timeo=30")
            options += f",nfsvers={params.get('nfs_version', 4)}"
            remote = f"{params['server']}:{params['export_path']}"
            cmd = ["/usr/bin/sudo", "/bin/mount", "-t", "nfs",
                   remote, local_path, "-o", options]
 
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            err = r.stderr.strip()
 
            # Resoudre le nom pour aider au diagnostic
            server_name, server_ip = _resolve_server(params.get("server", ""))
            dns_info = (
                f"Nom interroge : {server_name} -> IP resolue : {server_ip}"
                if server_ip
                else f"Nom interroge : {server_name} -> resolution DNS echouee"
            )
 
            if "Permission denied" in err or "error(13)" in err:
                err = (
                    f"Acces refuse par le serveur (Permission denied). "
                    f"{dns_info}. "
                    "Verifier : 1) les identifiants (utilisateur/mot de passe) "
                    "2) que l'IP resolue correspond bien au bon serveur "
                    "(probleme DNS possible si le nom pointe vers une mauvaise IP) "
                    "3) les droits d'acces sur le partage."
                )
            elif "Operation not permitted" in err or "not permitted" in err.lower():
                err = (
                    "Montage bloque par le LXC. "
                    "Sur le host Proxmox, ajouter dans /etc/pve/lxc/<id>.conf : "
                    "lxc.apparmor.profile: unconfined et lxc.cap.drop: "
                    "puis redemarrer le LXC."
                )
            elif "No such host" in err or "Name or service not known" in err:
                err = (
                    f"Serveur introuvable. {dns_info}. "
                    "Verifier le nom ou utiliser l'IP directe."
                )
            else:
                err = f"{err} | {dns_info}"
 
            return False, err
        return True, ""
    except subprocess.TimeoutExpired:
        server_name, server_ip = _resolve_server(params.get("server", ""))
        return False, (
            f"Timeout - serveur inaccessible. "
            f"Nom interroge : {server_name} -> IP resolue : {server_ip or 'inconnue'}"
        )
    except Exception as e:
        return False, str(e)
    finally:
        if creds_file:
            try:
                os.unlink(creds_file)
            except Exception:
                pass


def _do_umount(local_path: str) -> tuple:
    try:
        r = subprocess.run(
            ["/usr/bin/sudo", "umount", "-l", local_path],
            capture_output=True, text=True, timeout=30
        )
        return r.returncode == 0, r.stderr.strip()
    except Exception as e:
        return False, str(e)


@router.post("/mounts/sync")
def sync_mounts():
    """Synchronise BDD ↔ OS. Supprime d'abord, monte ensuite."""
    try:
        with engine.connect() as conn:
            desired_rows = conn.execute(text("""
                SELECT m.id, m.mount_type, m.local_path,
                       s.server, s.share, s.username, s.password,
                       s.domain, s.smb_version, s.mount_options AS smb_options,
                       n.server AS nfs_server, n.export_path,
                       n.nfs_version, n.mount_options AS nfs_options
                FROM mounts m
                LEFT JOIN mount_smb s ON s.mount_id = m.id
                LEFT JOIN mount_nfs n ON n.mount_id = m.id
                WHERE m.active = true
            """)).fetchall()

        desired_paths = {r[2] for r in desired_rows}

        active_paths = set()
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] in ("cifs", "nfs", "nfs4"):
                        active_paths.add(parts[1])
        except Exception:
            pass

        to_remove = active_paths - desired_paths
        to_add    = [r for r in desired_rows if r[2] not in active_paths]
        report    = {"removed": [], "added": [], "errors": [],
                     "already_mounted": list(active_paths & desired_paths)}

        # 1. Démonter d'abord (gère les renommages)
        for path in to_remove:
            ok, err = _do_umount(path)
            (report["removed"] if ok else report["errors"]).append(
                path if ok else {"path": path, "action": "umount", "error": err}
            )

        # 2. Monter ensuite
        with engine.connect() as conn:
            for r in to_add:
                mount_id, mount_type, local_path = r[0], r[1], r[2]
                params = (
                    {"server": r[3], "share": r[4], "username": r[5],
                     "password": r[6], "domain": r[7], "smb_version": r[8],
                     "mount_options": r[9]}
                    if mount_type == "smb" else
                    {"server": r[10], "export_path": r[11],
                     "nfs_version": r[12], "mount_options": r[13]}
                )
                ok, err = _do_mount(local_path, mount_type, params)
                if ok:
                    report["added"].append(local_path)
                    conn.execute(text(
                        "UPDATE mounts SET last_mount_at=NOW(), last_error=NULL WHERE id=:id"
                    ), {"id": mount_id})
                    # Scan prioritaire : le disque est maintenant disponible
                    from watcher.scanner import scan_queue
                    scan_queue.enqueue_priority(mount_id)
                else:
                    report["errors"].append({"path": local_path, "error": err})
                    logger.error(f"sync: échec montage {local_path} : {err}")
                    conn.execute(text(
                        "UPDATE mounts SET last_error=:e WHERE id=:id"
                    ), {"e": err, "id": mount_id})
            conn.commit()
 
        return JSONResponse({
            "success": len(report["errors"]) == 0,
            "summary": (f"+{len(report['added'])} montés, "
                        f"-{len(report['removed'])} démontés, "
                        f"{len(report['already_mounted'])} déjà actifs, "
                        f"{len(report['errors'])} erreurs"),
            "report": report
        })
    except Exception as e:
        logger.error(f"sync_mounts: {e}")
        raise HTTPException(500, str(e))


# ── Browse réseau ─────────────────────────────────────────────────────────────

@router.get("/mounts/browse")
def browse_network(
    type: str,
    server: str,
    username: Optional[str] = None,
    password: Optional[str] = None
):
    """
    Liste les partages/exports disponibles sur un serveur.
    SMB  → smbclient -N -L //server
    NFS  → showmount -e server
    """
    if type not in ("smb", "nfs"):
        raise HTTPException(400, "type doit être 'smb' ou 'nfs'")
 
    server_clean = server.lstrip("/")
    shares, error = [], None
 
    if type == "smb":
        cmd = ["/usr/bin/smbclient", "-N", "-L", f"//{server_clean}"]
        if username:
            # Avec credentials : pas de -N (anonyme), on passe -U user%password
            cmd = ["/usr/bin/smbclient", "-L", f"//{server_clean}",
                   "-U", f"{username}%{password or ''}"]
        else:
            # Sans credentials : accès anonyme avec -N
            cmd = ["/usr/bin/smbclient", "-N", "-L", f"//{server_clean}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in r.stdout.splitlines():
                line = line.strip()
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "Disk":
                    shares.append("/" + parts[0])
            if r.returncode != 0 and not shares:
                error = r.stderr.strip() or r.stdout.strip()
        except FileNotFoundError:
            error = "Outil de navigation SMB non disponible — relancer le service pour l'installer automatiquement"
        except subprocess.TimeoutExpired:
            error = "Timeout — serveur inaccessible ou pare-feu"
        except Exception as e:
            error = str(e)
    else:
        cmd = ["/usr/bin/showmount", "-e", "--no-headers", server_clean]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in r.stdout.splitlines():
                parts = line.split()
                if parts:
                    shares.append(parts[0])
            if r.returncode != 0 and not shares:
                error = r.stderr.strip() or r.stdout.strip()
        except FileNotFoundError:
            error = "Outil de navigation NFS non disponible — relancer le service pour l'installer automatiquement"
        except subprocess.TimeoutExpired:
            error = "Timeout — serveur inaccessible ou NFS non activé"
        except Exception as e:
            error = str(e)
 
    return JSONResponse({"server": server, "type": type, "shares": shares, "error": error})


# ── Mise à jour application ───────────────────────────────────────────────────
 
@router.post("/update")
def trigger_update():
    """
    Lance un git pull + redemarrage du service.
    Invalide le cache de version pour forcer une nouvelle verification au redemarrage.
    """    
    from watcher.config import PROJECT_ROOT
 
    results = {}
 
    # 1. git pull
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
        # Encoder en ASCII pour eviter les erreurs de codec dans les logs
        output = (r.stdout.strip() or r.stderr.strip()).encode("ascii", "replace").decode("ascii")
        results["git_pull"] = {
            "success": r.returncode == 0,
            "output":  output
        }
    except Exception as e:
        results["git_pull"] = {"success": False, "output": str(e)}
 
    if results["git_pull"]["success"]:
        # Lire la nouvelle version depuis VERSION mis a jour par git pull
        new_version = None
        try:
            version_file = PROJECT_ROOT / "VERSION"
            if version_file.exists():
                new_version = version_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
 
        # Mettre a jour le fichier service systemd depuis le repo
        # Necessaire car proxmox-install.sh cree le service a l'installation
        # et git pull ne met pas a jour /etc/systemd/system/
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
                    logger.info("Fichier service systemd mis a jour")
        except Exception as e:
            logger.warning(f"Impossible de mettre a jour le service systemd : {e}")
            results["service_updated"] = False
 
        # Invalider le cache de version GitHub
        try:
            from watcher.app import get_latest_github_version
            if hasattr(get_latest_github_version, "_cache"):
                del get_latest_github_version._cache
        except Exception:
            pass
 
        def restart():
            time.sleep(0.8)
            os.kill(os.getpid(), signal.SIGTERM)
 
        threading.Thread(target=restart, daemon=True).start()
        results["restart"] = "Redemarrage dans 1 seconde"
        results["new_version"] = new_version
        message = (f"Mise a jour vers {new_version} - interface disponible dans quelques secondes"
                   if new_version else "Mise a jour lancee - interface disponible dans quelques secondes")
    else:
        results["restart"] = "Redemarrage annule (git pull echoue)"
        results["new_version"] = None
        message = f"Echec git pull : {results['git_pull']['output']}"
 
    return JSONResponse({
        "success":     results["git_pull"]["success"],
        "results":     results,
        "new_version": results.get("new_version"),
        "message":     message
    })

# ── Force check version ───────────────────────────────────────────────────────
 
@router.get("/version/check")
def force_version_check():
    """
    Force une nouvelle verification de version en vidant le cache.
    Utile en developpement pour ne pas attendre les 30 minutes.
    Appele quand l'utilisateur clique sur le numero de version dans le header.
    """
    try:
        from watcher.app import get_latest_github_version
        # Vider le cache pour forcer un appel GitHub immediat
        if hasattr(get_latest_github_version, "_cache"):
            del get_latest_github_version._cache
            logger.info("Cache de version invalide (force check)")
        return JSONResponse({"success": True, "message": "Cache vide - prochain appel dashboard retournera la version fraiche"})
    except Exception as e:
        logger.error(f"force_version_check: {e}")
        raise HTTPException(500, str(e))

# ── Serveurs connus ───────────────────────────────────────────────────────────

@router.get("/mounts/known-servers")
def get_known_servers():
    """Liste des serveurs réseau connus avec leurs credentials."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, server, mount_type, username, domain,
                       smb_version, nfs_version, note
                FROM known_servers
                ORDER BY server
            """)).fetchall()
        return JSONResponse([{
            "id":          r[0],
            "server":      r[1],
            "mount_type":  r[2],
            "username":    r[3],
            "domain":      r[4],
            "smb_version": r[5],
            "nfs_version": r[6],
            "note":        r[7],
        } for r in rows])
    except Exception as e:
        logger.error(f"get_known_servers: {e}")
        raise HTTPException(500, str(e))


@router.post("/mounts/known-servers")
def upsert_known_server(data: dict = Body(...)):
    """
    Crée ou met à jour un serveur connu.
    Upsert sur le champ server (UNIQUE).
    """
    server     = (data.get("server") or "").strip()
    mount_type = (data.get("mount_type") or "smb").strip()
    if not server:
        raise HTTPException(400, "Champ 'server' obligatoire")
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO known_servers
                    (server, mount_type, username, password, domain,
                     smb_version, nfs_version, note)
                VALUES
                    (:server, :mount_type, :username, :password, :domain,
                     :smb_version, :nfs_version, :note)
                ON CONFLICT (server) DO UPDATE SET
                    mount_type  = EXCLUDED.mount_type,
                    username    = EXCLUDED.username,
                    password    = EXCLUDED.password,
                    domain      = EXCLUDED.domain,
                    smb_version = EXCLUDED.smb_version,
                    nfs_version = EXCLUDED.nfs_version,
                    note        = EXCLUDED.note,
                    updated_at  = NOW()
            """), {
                "server":      server,
                "mount_type":  mount_type,
                "username":    data.get("username"),
                "password":    data.get("password"),
                "domain":      data.get("domain", "WORKGROUP"),
                "smb_version": data.get("smb_version", "3.0"),
                "nfs_version": data.get("nfs_version", 4),
                "note":        data.get("note"),
            })
            conn.commit()
            row = conn.execute(text(
                "SELECT id FROM known_servers WHERE server = :s"
            ), {"s": server}).fetchone()
        return JSONResponse({"success": True, "id": row[0]})
    except Exception as e:
        logger.error(f"upsert_known_server: {e}")
        raise HTTPException(500, str(e))


@router.post("/mounts/batch")
def create_mounts_batch(data: dict = Body(...)):
    """
    Crée plusieurs montages en une seule requête.

    Body attendu :
    {
      "server_info": {
        "server": "//DS1821",
        "mount_type": "smb",
        "username": "user",
        "password": "pwd",
        "domain": "WORKGROUP",
        "smb_version": "3.0"
      },
      "mounts": [
        { "share": "/Series",  "category_id": 1 },
        { "share": "/Films",   "category_id": 2 },
        { "share": "/Animes",  "category_name": "animes" }
      ]
    }

    Si category_name est fourni au lieu de category_id,
    la catégorie est créée automatiquement si elle n'existe pas.
    """
    server_info = data.get("server_info", {})
    mounts_in   = data.get("mounts", [])

    server     = (server_info.get("server") or "").strip()
    mount_type = (server_info.get("mount_type") or "smb").strip()

    if not server:
        raise HTTPException(400, "server_info.server obligatoire")
    if not mounts_in:
        raise HTTPException(400, "La liste mounts est vide")

    created = []
    errors  = []

    try:
        with engine.connect() as conn:

            # ── Sauvegarder / mettre à jour le serveur connu ──────────────
            conn.execute(text("""
                INSERT INTO known_servers
                    (server, mount_type, username, password, domain,
                     smb_version, nfs_version)
                VALUES
                    (:server, :mount_type, :username, :password, :domain,
                     :smb_version, :nfs_version)
                ON CONFLICT (server) DO UPDATE SET
                    mount_type  = EXCLUDED.mount_type,
                    username    = EXCLUDED.username,
                    password    = EXCLUDED.password,
                    domain      = EXCLUDED.domain,
                    smb_version = EXCLUDED.smb_version,
                    updated_at  = NOW()
            """), {
                "server":      server,
                "mount_type":  mount_type,
                "username":    server_info.get("username"),
                "password":    server_info.get("password"),
                "domain":      server_info.get("domain", "WORKGROUP"),
                "smb_version": server_info.get("smb_version", "3.0"),
                "nfs_version": server_info.get("nfs_version", 4),
            })

            # ── Traiter chaque montage demandé ────────────────────────────
            for m in mounts_in:
                share = (m.get("share") or "").strip()
                if not share:
                    errors.append({"share": share, "error": "share vide"})
                    continue

                # Résoudre la catégorie
                cat_id   = m.get("category_id")
                cat_name = (m.get("category_name") or "").strip().lower()

                if not cat_id and cat_name:
                    # Créer la catégorie si elle n'existe pas
                    conn.execute(text("""
                        INSERT INTO categories (name)
                        VALUES (:name)
                        ON CONFLICT (name) DO NOTHING
                    """), {"name": cat_name})
                    row = conn.execute(text(
                        "SELECT id FROM categories WHERE name = :name"
                    ), {"name": cat_name}).fetchone()
                    cat_id = row[0] if row else None

                if not cat_id:
                    errors.append({"share": share, "error": "catégorie introuvable"})
                    continue

                # Construire le local_path
                row_cat = conn.execute(text(
                    "SELECT name FROM categories WHERE id = :id"
                ), {"id": cat_id}).fetchone()
                if not row_cat:
                    errors.append({"share": share, "error": f"catégorie {cat_id} introuvable"})
                    continue

                # Compter les montages existants pour cet catégorie
                # pour générer l'id après insert
                try:
                    # INSERT mounts
                    row_m = conn.execute(text("""
                        INSERT INTO mounts (mount_type, category_id, local_path, active)
                        VALUES (:mt, :cat, 'PLACEHOLDER', true)
                        RETURNING id
                    """), {"mt": mount_type, "cat": cat_id}).fetchone()
                    mount_id   = row_m[0]
                    cat_name_v = row_cat[0]
                    local_path = f"{MOUNT_BASE_PATH}/{cat_name_v}/{mount_id}-{cat_name_v}"

                    conn.execute(text(
                        "UPDATE mounts SET local_path = :lp WHERE id = :id"
                    ), {"lp": local_path, "id": mount_id})

                    # INSERT mount_smb ou mount_nfs
                    if mount_type == "smb":
                        conn.execute(text("""
                            INSERT INTO mount_smb
                                (mount_id, server, share, username, password,
                                 domain, smb_version)
                            VALUES
                                (:mid, :srv, :share, :user, :pwd, :dom, :ver)
                        """), {
                            "mid":   mount_id,
                            "srv":   server,
                            "share": share,
                            "user":  server_info.get("username"),
                            "pwd":   server_info.get("password"),
                            "dom":   server_info.get("domain", "WORKGROUP"),
                            "ver":   server_info.get("smb_version", "3.0"),
                        })
                    else:
                        conn.execute(text("""
                            INSERT INTO mount_nfs
                                (mount_id, server, export_path, nfs_version)
                            VALUES (:mid, :srv, :share, :ver)
                        """), {
                            "mid":   mount_id,
                            "srv":   server,
                            "share": share,
                            "ver":   server_info.get("nfs_version", 4),
                        })

                    created.append({
                        "mount_id":    mount_id,
                        "share":       share,
                        "local_path":  local_path,
                        "category_id": cat_id,
                    })

                except Exception as e_inner:
                    err = str(e_inner)
                    if "uq_smb_source" in err or "uq_nfs_source" in err:
                        errors.append({"share": share, "error": "source déjà configurée"})
                    else:
                        errors.append({"share": share, "error": err})

            conn.commit()

            # ── Déclencher les scans pour les montages créés ──────────────
            from watcher.scanner import scan_queue
            for c in created:
                scan_queue.enqueue_priority(c["mount_id"])

        return JSONResponse({
            "success": True,
            "created": created,
            "errors":  errors,
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_mounts_batch: {e}")
        raise HTTPException(500, str(e))




    
# ── Purge (développement) ─────────────────────────────────────────────────────

@router.delete("/purge")
def purge_scan_data():
    """
    Supprime tous les fichiers détectés et l'historique des scans.
    Bouton de développement — l'action sera affinée au fil des avancées.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE media_files, scan_jobs RESTART IDENTITY CASCADE"))
            conn.commit()
        logger.info("Purge effectuée : media_files + scan_jobs vidés")
        return JSONResponse({"success": True, "message": "Données de scan supprimées"})
    except Exception as e:
        logger.error(f"purge: {e}")
        raise HTTPException(500, str(e))    
    
# ── Fichiers & Stats ──────────────────────────────────────────────────────────

@router.get("/files/stats")
def files_stats():
    """
    Retourne les compteurs de fichiers pour le dashboard.
    - Par statut global (new, known, missing, duplicate)
    - Par catégorie avec leur nombre de fichiers
    - Historique du dernier scan par montage
    """
    try:
        with engine.connect() as conn:

            # Compteurs globaux par statut
            rows = conn.execute(text("""
                SELECT status, COUNT(*) as cnt
                FROM media_files
                GROUP BY status
            """)).fetchall()
            by_status = {r[0]: r[1] for r in rows}
            total     = sum(by_status.values())
            # "traités" = known, "en attente" = new
            analyzed  = by_status.get("analyzed",  0)
            discovered= by_status.get("discovered", 0)
            analyzing = by_status.get("analyzing",  0)

            # Compteurs disk_status
            disk_rows = conn.execute(text("""
                SELECT disk_status, COUNT(*) as cnt
                FROM media_files
                GROUP BY disk_status
            """)).fetchall()
            by_disk = {r[0]: r[1] for r in disk_rows}
            missing   = by_disk.get("missing",   0)
            duplicate = by_disk.get("duplicate", 0)

            # Compteurs par catégorie
            cat_rows = conn.execute(text("""
                SELECT c.name, COUNT(f.id) as cnt
                FROM categories c
                LEFT JOIN mounts m ON m.category_id = c.id
                LEFT JOIN media_files f ON f.mount_id = m.id
                GROUP BY c.name
                ORDER BY c.name
            """)).fetchall()
            by_category = [{"name": r[0], "count": r[1]} for r in cat_rows]

            # Dernier scan job par montage
            last_scans = conn.execute(text("""
                SELECT DISTINCT ON (mount_id)
                    mount_id, status, started_at, finished_at,
                    files_found, files_new, files_updated, files_missing
                FROM scan_jobs
                ORDER BY mount_id, created_at DESC
            """)).fetchall()
            scans = [{
                "mount_id":      r[0],
                "status":        r[1],
                "started_at":    str(r[2]) if r[2] else None,
                "finished_at":   str(r[3]) if r[3] else None,
                "files_found":   r[4],
                "files_new":     r[5],
                "files_updated": r[6],
                "files_missing": r[7],
            } for r in last_scans]

        return JSONResponse({
            "total":      total,
            "analyzed":   analyzed,
            "discovered": discovered,
            "analyzing":  analyzing,
            "missing":    missing,
            "duplicate":  duplicate,
            "by_category": by_category,
            "last_scans":  scans,
        })
    except Exception as e:
        logger.error(f"files_stats: {e}")
        raise HTTPException(500, str(e))



# Dictionnaire ISO 639 → nom lisible
LANG_NAMES = {
    "fra": "Français", "fre": "Français", "fr": "Français",
    "eng": "Anglais",  "en":  "Anglais",
    "jpn": "Japonais", "ja":  "Japonais",
    "ger": "Allemand", "deu": "Allemand", "de": "Allemand",
    "spa": "Espagnol", "es":  "Espagnol",
    "ita": "Italien",  "it":  "Italien",
    "por": "Portugais","pt":  "Portugais",
    "chi": "Chinois",  "zho": "Chinois",  "zh": "Chinois",
    "kor": "Coréen",   "ko":  "Coréen",
    "ara": "Arabe",    "ar":  "Arabe",
    "srp": "Serbe",    "sr":  "Serbe",
    "fin": "Finnois",  "fi":  "Finnois",
    "mis": "Non identifiée",
    "und": "Non définie",
    "":    "Inconnue",
}

def _resolve_lang(code: str) -> str:
    return LANG_NAMES.get(code.strip().lower(), code.strip().upper())


@router.get("/files/quality-stats")
def files_quality_stats(cat_id: int = None):
    """
    Statistiques qualité de la bibliothèque.
    cat_id (optionnel) : filtrer par catégorie.
    """
    try:
        with engine.connect() as conn:

            # ── Filtre catégorie ──────────────────────────────────────────
            if cat_id:
                where_mf    = "JOIN mounts mcat ON mcat.id = mf.mount_id AND mcat.category_id = :cat_id"
                file_filter = """EXISTS (
                    SELECT 1 FROM media_files mf2
                    JOIN mounts mcat2 ON mcat2.id = mf2.mount_id
                    WHERE mf2.id = video_metadata.file_id AND mcat2.category_id = :cat_id
                )"""
                path_filter = """EXISTS (
                    SELECT 1 FROM mounts mcat3
                    WHERE mcat3.id = mf.mount_id AND mcat3.category_id = :cat_id
                )"""
                params = {"cat_id": cat_id}
            else:
                where_mf    = ""
                file_filter = "1=1"
                path_filter = "1=1"
                params      = {}

            # ── Codecs vidéo ──────────────────────────────────────────────
            codecs = conn.execute(text(f"""
                SELECT video_codec, COUNT(*) as cnt
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                {where_mf}
                WHERE video_codec IS NOT NULL
                GROUP BY video_codec ORDER BY cnt DESC
            """), params).fetchall()

            # ── Résolutions ───────────────────────────────────────────────
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
                JOIN media_files mf ON mf.id = vm.file_id
                {where_mf}
                WHERE video_height IS NOT NULL
                GROUP BY label ORDER BY cnt DESC
            """), params).fetchall()

            # ── HDR ───────────────────────────────────────────────────────
            hdr = conn.execute(text(f"""
                SELECT hdr_format, COUNT(*) as cnt
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                {where_mf}
                WHERE hdr_format IS NOT NULL
                GROUP BY hdr_format ORDER BY cnt DESC
            """), params).fetchall()
            

            # ── Codecs audio ──────────────────────────────────────────────
            audio_rows = conn.execute(text(f"""
                SELECT audio_codecs FROM video_metadata
                WHERE {file_filter} AND audio_codecs IS NOT NULL
            """), params).fetchall()

            audio_codec_counts = {}
            for row in audio_rows:
                for codec in row[0].split(";"):
                    c = codec.strip().upper()
                    if c:
                        audio_codec_counts[c] = audio_codec_counts.get(c, 0) + 1
            audio_codecs_out = sorted(
                [{"label": k, "count": v} for k, v in audio_codec_counts.items()],
                key=lambda x: -x["count"]
            )

            # ── Langues audio ─────────────────────────────────────────────
            lang_rows = conn.execute(text(f"""
                SELECT audio_languages FROM video_metadata
                WHERE {file_filter} AND audio_languages IS NOT NULL
            """), params).fetchall()

            audio_lang_counts = {}
            for row in lang_rows:
                for lang in row[0].split(";"):
                    l = lang.strip().lower()
                    if l:
                        name = _resolve_lang(l)
                        audio_lang_counts[name] = audio_lang_counts.get(name, 0) + 1
            audio_langs_out = sorted(
                [{"label": k, "count": v} for k, v in audio_lang_counts.items()],
                key=lambda x: -x["count"]
            )

            # ── Canaux audio ──────────────────────────────────────────────
            chan_rows = conn.execute(text(f"""
                SELECT audio_channel_layouts FROM video_metadata
                WHERE {file_filter} AND audio_channel_layouts IS NOT NULL
            """), params).fetchall()

            chan_counts = {}
            for row in chan_rows:
                for ch in row[0].split(";"):
                    c = ch.strip()
                    if c:
                        chan_counts[c] = chan_counts.get(c, 0) + 1
            channels_out = sorted(
                [{"label": k, "count": v} for k, v in chan_counts.items()],
                key=lambda x: -x["count"]
            )

            # ── Langues sous-titres ───────────────────────────────────────
            sub_rows = conn.execute(text(f"""
                SELECT subtitle_languages FROM video_metadata
                WHERE {file_filter} AND subtitle_languages IS NOT NULL
            """), params).fetchall()

            no_sub = conn.execute(text(f"""
                SELECT COUNT(*) FROM video_metadata
                WHERE {file_filter}
                AND (subtitle_languages IS NULL OR subtitle_languages = '')
            """), params).fetchone()[0]

            sub_lang_counts = {}
            for row in sub_rows:
                for lang in row[0].split(";"):
                    l = lang.strip().lower()
                    if l:
                        name = _resolve_lang(l)
                        sub_lang_counts[name] = sub_lang_counts.get(name, 0) + 1
            sub_langs_out = sorted(
                [{"label": k, "count": v} for k, v in sub_lang_counts.items()],
                key=lambda x: -x["count"]
            )

            # ── Titres détectés (1er niveau de dossier) ───────────────────
            titles_rows = conn.execute(text(f"""
                SELECT
                    SPLIT_PART(mf.path_relative, '/', 1) as title,
                    COUNT(*) as cnt,
                    ROUND(SUM(mf.size_bytes)/1073741824::numeric, 2) as size_gb
                FROM media_files mf
                WHERE {path_filter} AND mf.status = 'analyzed'
                GROUP BY title
                ORDER BY title
            """), params).fetchall()

            titles_out = [{"name": r[0], "count": r[1], "size_gb": float(r[2] or 0)} for r in titles_rows]
            nb_titles = len(titles_out)

            # ── Taille totale ─────────────────────────────────────────────
            totals = conn.execute(text(f"""
                SELECT
                    COUNT(*)                                            as total,
                    ROUND(SUM(vm.duration_seconds)/3600)                as total_hours,
                    ROUND(AVG(mf.size_bytes)/1073741824::numeric, 2)    as avg_size_gb,
                    ROUND(SUM(mf.size_bytes)/1099511627776::numeric, 2) as total_tb
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                {where_mf}
            """), params).fetchone()

            # ── Répartition par catégorie (global seulement) ──────────────
            by_category = []
            if not cat_id:
                cat_rows = conn.execute(text("""
                    SELECT c.id, c.name, COUNT(mf.id) as cnt
                    FROM categories c
                    LEFT JOIN mounts m ON m.category_id = c.id
                    LEFT JOIN media_files mf ON mf.mount_id = m.id
                    GROUP BY c.id, c.name
                    ORDER BY cnt DESC
                """)).fetchall()
                by_category = [
                    {"id": r[0], "name": r[1], "count": r[2]}
                    for r in cat_rows
                ]

        return JSONResponse({
            "cat_id":       cat_id,
            "total":        totals[0] or 0,
            "total_hours":  float(totals[1] or 0),
            "avg_size_gb":  float(totals[2] or 0),
            "total_tb":     float(totals[3] or 0),
            "codecs":       [{"label": r[0], "count": r[1]} for r in codecs],
            "resolutions":  [{"label": r[0], "count": r[1]} for r in resolutions],
            "hdr":          [{"label": r[0], "count": r[1]} for r in hdr],
            "audio_codecs": audio_codecs_out,
            "audio_langs":  audio_langs_out,
            "audio_channels": channels_out,
            "sub_langs":    sub_langs_out,
            "no_sub_count": int(no_sub),
            "titles":       titles_out,
            "nb_titles": nb_titles,
            "by_category":  by_category,
        })

    except Exception as e:
        logger.error(f"files_quality_stats: {e}")
        raise HTTPException(500, str(e))
    
@router.get("/jobs/status")
def jobs_status():
    """Retourne l'état actuel des 3 jobs : scanner, analyser, catalogueur."""
    try:
        with engine.connect() as conn:

            # Dernier scan job
            last_scan = conn.execute(text("""
                SELECT j.status, j.started_at, j.finished_at,
                       j.files_found, j.files_new, m.local_path
                FROM scan_jobs j
                JOIN mounts m ON m.id = j.mount_id
                ORDER BY j.created_at DESC LIMIT 1
            """)).fetchone()

            # Session analyser en cours
            running_session = conn.execute(text("""
                SELECT a.status, a.folder_path, a.files_done,
                       a.files_total, a.started_at
                FROM analyze_sessions a
                WHERE a.status = 'running'
                ORDER BY a.started_at DESC LIMIT 1
            """)).fetchone()

            # Dernière session terminée
            last_session = conn.execute(text("""
                SELECT a.status, a.folder_path, a.files_done,
                       a.files_total, a.finished_at
                FROM analyze_sessions a
                WHERE a.status = 'done'
                ORDER BY a.finished_at DESC LIMIT 1
            """)).fetchone()

            # Stats analyser globales
            analyze_stats = conn.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE status='done')    as done,
                    COUNT(*) FILTER (WHERE status='pending') as pending,
                    COUNT(*) FILTER (WHERE status='running') as running,
                    COUNT(*) FILTER (WHERE status='error')   as error
                FROM analyze_sessions
            """)).fetchone()

            # Stats catalogueur
            catalog_stats = conn.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE folder_status='ok')        as ok,
                    COUNT(*) FILTER (WHERE folder_status='to_rename') as to_rename,
                    COUNT(*) FILTER (WHERE folder_status='pending')   as pending
                FROM media_titles
            """)).fetchone()

            # Propositions en attente
            proposals_pending = conn.execute(text("""
                SELECT COUNT(*) FROM rename_proposals WHERE status='pending'
            """)).fetchone()[0]

        def fmt_dt(dt):
            return str(dt)[:19] if dt else None

        return JSONResponse({
            "scanner": {
                "last_status":   last_scan[0] if last_scan else None,
                "last_started":  fmt_dt(last_scan[1]) if last_scan else None,
                "last_finished": fmt_dt(last_scan[2]) if last_scan else None,
                "files_found":   last_scan[3] if last_scan else 0,
                "files_new":     last_scan[4] if last_scan else 0,
                "last_mount":    last_scan[5].split('/')[-1] if last_scan else None,
            },
            "analyzer": {
                "running":        running_session is not None,
                "current_folder": running_session[1] if running_session else None,
                "current_done":   running_session[2] if running_session else 0,
                "current_total":  running_session[3] if running_session else 0,
                "last_folder":    last_session[1] if last_session else None,
                "last_finished":  fmt_dt(last_session[4]) if last_session else None,
                "sessions_done":  analyze_stats[0] if analyze_stats else 0,
                "sessions_pending": analyze_stats[1] if analyze_stats else 0,
            },
            "cataloger": {
                "titles_ok":        catalog_stats[0] if catalog_stats else 0,
                "titles_to_rename": catalog_stats[1] if catalog_stats else 0,
                "titles_pending":   catalog_stats[2] if catalog_stats else 0,
                "proposals_pending": proposals_pending,
            },
        })
    except Exception as e:
        logger.error(f"jobs_status: {e}")
        raise HTTPException(500, str(e))
    

    # ── Bibliothèque utilisateur ──────────────────────────────────────────────

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
            """)).fetchall()
        return JSONResponse([{
            "id":          r[0],
            "name":        r[1],
            "has_seasons": r[2],
            "title_count": r[3],
            "file_count":  r[4],
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
            """)).fetchall()

            result = []
            for cat in cats:
                cat_id = cat[0]

                # Résolutions top 5
                res_rows = conn.execute(text("""
                    SELECT
                        CASE
                            WHEN vm.video_height >= 2160 THEN '4K'
                            WHEN vm.video_height >= 1080 THEN '1080p'
                            WHEN vm.video_height >= 720  THEN '720p'
                            ELSE 'SD'
                        END as label,
                        COUNT(*) as cnt
                    FROM video_metadata vm
                    JOIN media_files mf ON mf.id = vm.file_id
                    JOIN mounts m ON m.id = mf.mount_id
                    WHERE m.category_id = :cid AND vm.video_height IS NOT NULL
                    GROUP BY label ORDER BY cnt DESC LIMIT 5
                """), {"cid": cat_id}).fetchall()

                total_res = sum(r[1] for r in res_rows) or 1
                resolutions = [{"label": r[0], "pct": round(r[1]/total_res*100)} for r in res_rows]

                # Codecs top 5
                cod_rows = conn.execute(text("""
                    SELECT vm.video_codec, COUNT(*) as cnt
                    FROM video_metadata vm
                    JOIN media_files mf ON mf.id = vm.file_id
                    JOIN mounts m ON m.id = mf.mount_id
                    WHERE m.category_id = :cid AND vm.video_codec IS NOT NULL
                    GROUP BY vm.video_codec ORDER BY cnt DESC LIMIT 5
                """), {"cid": cat_id}).fetchall()

                total_cod = sum(r[1] for r in cod_rows) or 1
                codecs = [{"label": r[0].upper(), "pct": round(r[1]/total_cod*100)} for r in cod_rows]

                result.append({
                    "id":          cat[0],
                    "name":        cat[1],
                    "has_seasons": cat[2],
                    "title_count": cat[3],
                    "file_count":  cat[4],
                    "total_tb":    float(cat[5] or 0),
                    "resolutions": resolutions,
                    "codecs":      codecs,
                })

        return JSONResponse(result)
    except Exception as e:
        logger.error(f"library_categories_stats: {e}")
        raise HTTPException(500, str(e))

@router.get("/library/titles")
def library_titles(category_id: int, search: str = None):
    """Titres d'une catégorie avec stats résolutions/codecs/poids/vu."""
    try:
        with engine.connect() as conn:
            params = {"cat": category_id}
            search_clause = ""
            if search:
                search_clause = "AND mt.display_name ILIKE :search"
                params["search"] = f"%{search}%"

            # ── Requête principale : titres + compteurs de base ───────────
            rows = conn.execute(text(f"""
                SELECT mt.id, mt.folder_name, mt.display_name,
                       mt.year, mt.folder_status,
                       COUNT(DISTINCT mi.id)                    as file_count,
                       COUNT(DISTINCT mi.season)                as season_count,
                       COUNT(DISTINCT rp.id)
                           FILTER (WHERE rp.status='pending')   as proposals,
                       COUNT(DISTINCT mi.id)
                           FILTER (WHERE mi.watched = true)     as watched_count,
                       ROUND(SUM(mf.size_bytes)/1073741824::numeric, 2) as size_gb
                FROM media_titles mt
                LEFT JOIN media_items mi ON mi.title_id = mt.id
                LEFT JOIN media_files  mf ON mf.id = mi.file_id
                LEFT JOIN rename_proposals rp ON (
                    rp.title_id = mt.id
                    OR rp.item_id = mi.id
                )
                JOIN mounts m ON m.id = mt.mount_id
                WHERE m.category_id = :cat {search_clause}
                GROUP BY mt.id, mt.folder_name, mt.display_name,
                         mt.year, mt.folder_status
                ORDER BY mt.display_name
            """), params).fetchall()

            title_ids = [r[0] for r in rows]
            if not title_ids:
                return JSONResponse([])

            # ── Résolutions groupées pour TOUS les titres en une requête ──
            res_rows = conn.execute(text("""
                SELECT mi.title_id,
                    CASE
                        WHEN vm.video_height >= 2160 THEN '4K'
                        WHEN vm.video_height >= 1080 THEN '1080p'
                        WHEN vm.video_height >= 720  THEN '720p'
                        ELSE 'SD'
                    END as label,
                    COUNT(*) as cnt
                FROM media_items mi
                JOIN media_files mf ON mf.id = mi.file_id
                JOIN video_metadata vm ON vm.file_id = mf.id
                JOIN mounts m ON m.id = mf.mount_id
                WHERE m.category_id = :cat AND vm.video_height IS NOT NULL
                GROUP BY mi.title_id, label
            """), {"cat": category_id}).fetchall()

            res_by_title = {}
            for tid, label, cnt in res_rows:
                res_by_title.setdefault(tid, []).append((label, cnt))

            # ── Codecs groupés pour TOUS les titres en une requête ────────
            cod_rows = conn.execute(text("""
                SELECT mi.title_id, vm.video_codec, COUNT(*) as cnt
                FROM media_items mi
                JOIN media_files mf ON mf.id = mi.file_id
                JOIN video_metadata vm ON vm.file_id = mf.id
                JOIN mounts m ON m.id = mf.mount_id
                WHERE m.category_id = :cat AND vm.video_codec IS NOT NULL
                GROUP BY mi.title_id, vm.video_codec
            """), {"cat": category_id}).fetchall()

            cod_by_title = {}
            for tid, codec, cnt in cod_rows:
                cod_by_title.setdefault(tid, []).append((codec, cnt))

        # ── Assemblage en Python (rapide, en mémoire) ──────────────────────
        titles_out = []
        for r in rows:
            title_id      = r[0]
            file_count    = r[5] or 0
            watched_count = r[8] or 0
            watched_pct   = round(watched_count / file_count * 100) if file_count else 0

            res_list = sorted(res_by_title.get(title_id, []), key=lambda x: -x[1])[:4]
            total_res = sum(x[1] for x in res_list) or 1
            resolutions = [{"label": l, "pct": round(c/total_res*100)} for l, c in res_list]

            cod_list = sorted(cod_by_title.get(title_id, []), key=lambda x: -x[1])[:4]
            total_cod = sum(x[1] for x in cod_list) or 1
            codecs = [{"label": l.upper(), "pct": round(c/total_cod*100)} for l, c in cod_list]

            titles_out.append({
                "id":            r[0],
                "folder_name":   r[1],
                "display_name":  r[2] or r[1],
                "year":          r[3],
                "folder_status": r[4],
                "file_count":    file_count,
                "season_count":  r[6],
                "proposals":     r[7] or 0,
                "watched_count": watched_count,
                "watched_pct":   watched_pct,
                "size_gb":       float(r[9] or 0),
                "resolutions":   resolutions,
                "codecs":        codecs,
            })

        return JSONResponse(titles_out)
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
            """), {"id": title_id}).fetchone()

            if not title:
                raise HTTPException(404, "Titre introuvable")

            items = conn.execute(text("""
                SELECT mi.id, mi.season, mi.episode, mi.episode_title,
                       mi.file_status, mi.watched,
                       mf.filename, mf.size_bytes,
                       vm.video_codec, vm.video_height, vm.hdr_format,
                       vm.duration_seconds,
                       rp.proposed_name, rp.status as prop_status, rp.id as prop_id
                FROM media_items mi
                JOIN media_files mf ON mf.id = mi.file_id
                LEFT JOIN video_metadata vm ON vm.file_id = mf.id
                LEFT JOIN rename_proposals rp ON rp.item_id = mi.id
                    AND rp.status = 'pending'
                WHERE mi.title_id = :tid
                ORDER BY mi.season NULLS LAST, mi.episode NULLS LAST
            """), {"tid": title_id}).fetchall()

        # Grouper par saison + calculer stats par saison
        seasons = {}
        for r in items:
            s = r[1]
            if s not in seasons:
                seasons[s] = {"items": [], "res": {}, "cod": {},
                              "size": 0, "watched": 0}
            entry = {
                "item_id":       r[0],
                "season":        r[1],
                "episode":       r[2],
                "episode_title": r[3],
                "file_status":   r[4],
                "watched":       r[5],
                "filename":      r[6],
                "size_bytes":    r[7],
                "codec":         r[8],
                "height":        r[9],
                "hdr":           r[10],
                "duration":      r[11],
                "proposed_name": r[12],
                "prop_status":   r[13],
                "prop_id":       r[14],
            }
            seasons[s]["items"].append(entry)
            seasons[s]["size"] += (r[7] or 0)
            if r[5]:
                seasons[s]["watched"] += 1
            if r[9]:
                label = '4K' if r[9] >= 2160 else '1080p' if r[9] >= 1080 \
                        else '720p' if r[9] >= 720 else 'SD'
                seasons[s]["res"][label] = seasons[s]["res"].get(label, 0) + 1
            if r[8]:
                seasons[s]["cod"][r[8]] = seasons[s]["cod"].get(r[8], 0) + 1

        def _pct_list(d, limit=4):
            total = sum(d.values()) or 1
            top = sorted(d.items(), key=lambda x: -x[1])[:limit]
            return [{"label": k, "pct": round(v/total*100)} for k, v in top]

        seasons_out = {}
        all_res, all_cod = {}, {}
        total_size, total_watched, total_items = 0, 0, 0

        for s, data in sorted(seasons.items(), key=lambda x: (x[0] is None, x[0])):
            n = len(data["items"])
            seasons_out[str(s)] = {
                "items":       data["items"],
                "file_count":  n,
                "watched_pct": round(data["watched"]/n*100) if n else 0,
                "size_gb":     round(data["size"]/1073741824, 2),
                "resolutions": _pct_list(data["res"]),
                "codecs":      _pct_list(data["cod"]),
            }
            for k, v in data["res"].items(): all_res[k] = all_res.get(k,0)+v
            for k, v in data["cod"].items(): all_cod[k] = all_cod.get(k,0)+v
            total_size    += data["size"]
            total_watched += data["watched"]
            total_items   += n

        return JSONResponse({
            "id":           title[0],
            "folder_name":  title[1],
            "display_name": title[2] or title[1],
            "year":         title[3],
            "folder_status":title[4],
            "category":     title[5],
            "has_seasons":  title[6],
            "file_count":   total_items,
            "proposals_total": sum(1 for it in items if it[14]),
            "watched_pct":  round(total_watched/total_items*100) if total_items else 0,
            "size_gb":      round(total_size/1073741824, 2),
            "resolutions":  _pct_list(all_res),
            "codecs":       _pct_list(all_cod),
            "seasons":      seasons_out,
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"library_title_detail: {e}")
        raise HTTPException(500, str(e))
    
    # ── Renommage utilisateur ─────────────────────────────────────────────────────

@router.get("/library/proposals")
def library_proposals(category_id: int = None):
    try:
        with engine.connect() as conn:
            params = {}
            cat_filter = ""
            if category_id:
                cat_filter = "AND c.id = :cat_id"
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
            """), params).fetchall()

        return JSONResponse([{
            "title_id":       r[0],
            "display_name":   r[1] or r[2],
            "folder_name":    r[2],
            "folder_status":  r[3],
            "category":       r[4],
            "has_seasons":    r[5],
            "proposal_count": r[6],
        } for r in rows])
    except Exception as e:
        logger.error(f"library_proposals: {e}")
        raise HTTPException(500, str(e))


@router.get("/library/proposals/{title_id}")
def library_proposals_detail(title_id: int):
    """
    Détail des propositions pour un titre — dossier + fichiers par saison.
    """
    try:
        with engine.connect() as conn:
            # Info du titre
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
            """), {"tid": title_id}).fetchone()

            if not title:
                raise HTTPException(404, "Titre introuvable")

            # Proposition sur le dossier titre
            title_prop = conn.execute(text("""
                SELECT id, current_name, proposed_name, status
                FROM rename_proposals
                WHERE title_id = :tid AND item_id IS NULL
                ORDER BY created_at DESC LIMIT 1
            """), {"tid": title_id}).fetchone()

            # Propositions sur les fichiers
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
            """), {"tid": title_id}).fetchall()

        # Grouper par saison
        seasons = {}
        for r in item_props:
            s = r[4]
            if s not in seasons:
                seasons[s] = []
            seasons[s].append({
                "prop_id":       r[0],
                "current_name":  r[1],
                "proposed_name": r[2],
                "status":        r[3],
                "season":        r[4],
                "episode":       r[5],
                "episode_title": r[6],
                "item_id":       r[7],
                "filename":      r[8],
                "size_bytes":    r[9],
                "codec":         r[10],
                "height":        r[11],
                "hdr":           r[12],
            })

        tpl = {
            "sep1":           title[6],
            "sep2":           title[7],
            "prefix_season":  title[8],
            "digits_season":  title[9],
            "sep_se":         title[10],
            "prefix_episode": title[11],
            "digits_episode": title[12],
            "sep_year":       title[13],
            "year_format":    title[14],
        }

        return JSONResponse({
            "title_id":      title[0],
            "display_name":  title[1] or title[2],
            "folder_name":   title[2],
            "folder_status": title[3],
            "category":      title[4],
            "has_seasons":   title[5],
            "year":          title[15],
            "template":      tpl,
            "title_proposal": {
                "prop_id":       title_prop[0],
                "current_name":  title_prop[1],
                "proposed_name": title_prop[2],
                "status":        title_prop[3],
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
    """
    Accepte une proposition avec le nom final choisi par l'utilisateur.
    update_mkv : bool — mettre à jour le tag title dans le fichier MKV
    """
    final_name  = (data.get("final_name") or "").strip()
    update_mkv  = data.get("update_mkv", False)

    if not final_name:
        raise HTTPException(400, "final_name obligatoire")
    try:
        with engine.connect() as conn:
            rp = conn.execute(text(
                "SELECT id, status FROM rename_proposals WHERE id = :id"
            ), {"id": prop_id}).fetchone()
            if not rp:
                raise HTTPException(404, "Proposition introuvable")
            if rp[1] != 'pending':
                raise HTTPException(400, f"Proposition déjà traitée : {rp[1]}")

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
                "codecs":    split_semi(row["audio_codecs"]),
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