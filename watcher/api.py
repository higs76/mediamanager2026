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
                where_mf  = "WHERE mf.mount_id IN (SELECT id FROM mounts WHERE category_id = :cat_id)"
                where_vm  = """WHERE vm.file_id IN (
                                SELECT mf.id FROM media_files mf
                                JOIN mounts m ON m.id = mf.mount_id
                                WHERE m.category_id = :cat_id)"""
                params = {"cat_id": cat_id}
            else:
                where_mf = ""
                where_vm = ""
                params   = {}

            # ── Codecs vidéo ──────────────────────────────────────────────
            codecs = conn.execute(text(f"""
                SELECT video_codec, COUNT(*) as cnt
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                {where_mf.replace('WHERE mf.', 'WHERE mf.')}
                {'WHERE' if not where_mf else 'AND'} video_codec IS NOT NULL
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
                {where_mf.replace('WHERE mf.', 'WHERE mf.')}
                {'WHERE' if not where_mf else 'AND'} video_height IS NOT NULL
                GROUP BY label ORDER BY cnt DESC
            """), params).fetchall()

            # ── HDR ───────────────────────────────────────────────────────
            hdr = conn.execute(text(f"""
                SELECT hdr_format, COUNT(*) as cnt
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                {where_mf.replace('WHERE mf.', 'WHERE mf.')}
                {'WHERE' if not where_mf else 'AND'} hdr_format IS NOT NULL
                GROUP BY hdr_format ORDER BY cnt DESC
            """), params).fetchall()

            # Sous-requête de filtre réutilisable
            if cat_id:
                file_filter = """file_id IN (
                    SELECT mf.id FROM media_files mf
                    JOIN mounts m ON m.id = mf.mount_id
                    WHERE m.category_id = :cat_id
                )"""
                path_filter = """mf.mount_id IN (
                    SELECT id FROM mounts WHERE category_id = :cat_id
                )"""
            else:
                file_filter = "1=1"
                path_filter = "1=1"

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
                    COUNT(*)                                           as total,
                    ROUND(SUM(vm.duration_seconds)/3600)               as total_hours,
                    ROUND(AVG(mf.size_bytes)/1073741824::numeric, 2)   as avg_size_gb,
                    ROUND(SUM(mf.size_bytes)/1099511627776::numeric, 2) as total_tb
                FROM video_metadata vm
                JOIN media_files mf ON mf.id = vm.file_id
                WHERE {path_filter.replace('mf.mount_id', 'mf.mount_id')}
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