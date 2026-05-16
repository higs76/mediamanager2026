"""
MediaManager 2026 - API Admin : Montages & Catégories
Toutes les routes /api/admin/...
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from watcher.database import engine
from watcher.config import MOUNT_BASE_PATH

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin")


# ── Schémas Pydantic ──────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str

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


# ── Catégories ────────────────────────────────────────────────────────────────

@router.get("/categories")
def list_categories():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, name FROM categories ORDER BY name"
            )).fetchall()
        cats = [{"id": r[0], "name": r[1]} for r in rows]
        return JSONResponse({
            "categories": [c["name"] for c in cats],
            "detail":     cats
        })
    except Exception as e:
        err = str(e)
        # Table absente = BDD pas encore initialisée → retourner vide, pas 500
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
            row = conn.execute(
                text("INSERT INTO categories (name) VALUES (:n) RETURNING id, name"),
                {"n": name}
            ).fetchone()
            conn.commit()
        return JSONResponse({"id": row[0], "name": row[1]})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_category: {e}")
        raise HTTPException(500, str(e))


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
        logger.error(f"create_mount: {e}")
        raise HTTPException(500, str(e))


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
        logger.error(f"update_mount: {e}")
        raise HTTPException(500, str(e))


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

def _do_mount(local_path: str, mount_type: str, params: dict) -> tuple:
    """Exécute mount. Retourne (succès, message_erreur)."""
    import os
    os.makedirs(local_path, exist_ok=True)

    if mount_type == "smb":
        options = params.get("mount_options", "")
        if params.get("username"):
            options += f",username={params['username']}"
            if params.get("password"):
                options += f",password={params['password']}"
            options += f",domain={params.get('domain','WORKGROUP')}"
        else:
            options += ",guest"
        options += f",vers={params.get('smb_version','3.0')}"
        remote = f"{params['server']}/{params['share'].lstrip('/')}"
        cmd = ["sudo", "mount", "-t", "cifs", remote, local_path, "-o", options]
    else:
        options = params.get("mount_options", "rw,soft,timeo=30")
        options += f",nfsvers={params.get('nfs_version', 4)}"
        remote = f"{params['server']}:{params['export_path']}"
        cmd = ["sudo", "mount", "-t", "nfs", remote, local_path, "-o", options]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return r.returncode == 0, r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout"
    except Exception as e:
        return False, str(e)


def _do_umount(local_path: str) -> tuple:
    try:
        r = subprocess.run(
            ["sudo", "umount", "-l", local_path],
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
                else:
                    report["errors"].append({"path": local_path, "error": err})
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
        cmd = ["smbclient", "-N", "-L", f"//{server_clean}"]
        if username:
            cmd += ["-U", f"{username}%{password or ''}"]
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
        cmd = ["showmount", "-e", "--no-headers", server_clean]
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
    Lance un git pull + redémarrage du service.
    Endpoint temporaire — sera remplacé par un système de versioning propre.
    """
    import subprocess
    from pathlib import Path
    from watcher.config import PROJECT_ROOT
 
    results = {}
 
    # 1. git pull
    try:
        r = subprocess.run(
            ["git", "pull"],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, timeout=60
        )
        results["git_pull"] = {
            "success":  r.returncode == 0,
            "output":   r.stdout.strip() or r.stderr.strip()
        }
    except Exception as e:
        results["git_pull"] = {"success": False, "output": str(e)}
 
    # 2. Redémarrage du service (le service se relance lui-même)
    # On utilise un thread pour répondre AVANT le redémarrage
    if results["git_pull"]["success"]:
        import threading
        def restart():
            import time, os, signal
            time.sleep(1)   # laisser le temps à la réponse HTTP d'être envoyée
            os.kill(os.getpid(), signal.SIGTERM)
 
        threading.Thread(target=restart, daemon=True).start()
        results["restart"] = "Service redémarrage dans 1 seconde…"
    else:
        results["restart"] = "Redémarrage annulé (git pull échoué)"
 
    return JSONResponse({
        "success": results["git_pull"]["success"],
        "results": results,
        "message": "Mise à jour lancée — l'interface sera disponible dans quelques secondes."
        if results["git_pull"]["success"]
        else f"Échec : {results['git_pull']['output']}"
    })