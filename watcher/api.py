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