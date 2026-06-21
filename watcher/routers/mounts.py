"""
MediaManager 2026 - Router : Montages réseau
Routes : /api/admin/mounts/*
"""

import logging
import os
import socket
import subprocess
import tempfile
from typing import Optional

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from watcher.database import engine
from watcher.config import MOUNT_BASE_PATH

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schémas Pydantic ──────────────────────────────────────────────────────────

class MountCreate(BaseModel):
    mount_type:    str
    category_name: str
    active:        bool = True
    server:        Optional[str] = None
    share:         Optional[str] = None
    username:      Optional[str] = None
    password:      Optional[str] = None
    domain:        str = "WORKGROUP"
    smb_version:   str = "3.0"
    smb_options:   str = "uid=1000,gid=1000,file_mode=0644,dir_mode=0755,iocharset=utf8"
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
    return f"{MOUNT_BASE_PATH}/{category_name}/{mount_id}-{category_name}"


def _is_mounted(local_path: str) -> bool:
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
    """), {"id": mount_id}).mappings().fetchone()

    if not row:
        return None

    result = {
        "id":            row["id"],
        "mount_type":    row["mount_type"],
        "category_id":   row["category_id"],
        "category_name": row["category_name"],
        "local_path":    row["local_path"],
        "active":        row["active"],
        "last_mount_at": str(row["last_mount_at"]) if row["last_mount_at"] else None,
        "last_error":    row["last_error"],
        "created_at":    str(row["created_at"]),
        "updated_at":    str(row["updated_at"]),
        "is_mounted":    _is_mounted(row["local_path"]),
    }

    if row["mount_type"] == "smb":
        smb = conn.execute(text("""
            SELECT server, share, username, domain, smb_version, mount_options
            FROM mount_smb WHERE mount_id = :id
        """), {"id": mount_id}).mappings().fetchone()
        if smb:
            result.update({
                "server":      smb["server"],
                "share":       smb["share"],
                "username":    smb["username"],
                "domain":      smb["domain"],
                "smb_version": smb["smb_version"],
                "smb_options": smb["mount_options"],
            })
    elif row["mount_type"] == "nfs":
        nfs = conn.execute(text("""
            SELECT server, export_path, nfs_version, mount_options
            FROM mount_nfs WHERE mount_id = :id
        """), {"id": mount_id}).mappings().fetchone()
        if nfs:
            result.update({
                "server":      nfs["server"],
                "export_path": nfs["export_path"],
                "nfs_version": nfs["nfs_version"],
                "nfs_options": nfs["mount_options"],
            })

    return result


def _write_creds_file(username: str, password: str, domain: str) -> str:
    """Écrit un fichier de credentials temporaire pour éviter les problèmes
    avec les caractères spéciaux (#, !, $...) dans les mots de passe."""
    fd, path = tempfile.mkstemp(prefix="mm_creds_", suffix=".tmp")
    try:
        content = f"username={username}\npassword={password}\ndomain={domain}\n"
        os.write(fd, content.encode("utf-8"))
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    return path


def _resolve_server(server: str) -> tuple:
    name = server.lstrip("/").split("/")[0]
    try:
        ip = socket.gethostbyname(name)
        return name, ip
    except Exception:
        return name, None


def _do_mount(local_path: str, mount_type: str, params: dict) -> tuple:
    """Exécute mount. Retourne (succès, message_erreur)."""
    os.makedirs(local_path, exist_ok=True)
    creds_file = None
    try:
        if mount_type == "smb":
            base_options = params.get("mount_options", "")
            smb_version  = params.get("smb_version", "3.0")
            if params.get("username"):
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
            server_name, server_ip = _resolve_server(params.get("server", ""))
            dns_info = (
                f"Nom interrogé : {server_name} -> IP résolue : {server_ip}"
                if server_ip
                else f"Nom interrogé : {server_name} -> résolution DNS échouée"
            )
            if "Permission denied" in err or "error(13)" in err:
                err = (
                    f"Accès refusé par le serveur (Permission denied). {dns_info}. "
                    "Vérifier : 1) les identifiants 2) que l'IP résolue correspond "
                    "au bon serveur 3) les droits d'accès sur le partage."
                )
            elif "Operation not permitted" in err or "not permitted" in err.lower():
                err = (
                    "Montage bloqué par le LXC. "
                    "Sur le host Proxmox, ajouter dans /etc/pve/lxc/<id>.conf : "
                    "lxc.apparmor.profile: unconfined et lxc.cap.drop: "
                    "puis redémarrer le LXC."
                )
            elif "No such host" in err or "Name or service not known" in err:
                err = f"Serveur introuvable. {dns_info}. Vérifier le nom ou utiliser l'IP directe."
            else:
                err = f"{err} | {dns_info}"
            return False, err
        return True, ""
    except subprocess.TimeoutExpired:
        server_name, server_ip = _resolve_server(params.get("server", ""))
        return False, (
            f"Timeout - serveur inaccessible. "
            f"Nom interrogé : {server_name} -> IP résolue : {server_ip or 'inconnue'}"
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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/mounts")
def list_mounts():
    try:
        with engine.connect() as conn:
            rows   = conn.execute(text("SELECT id FROM mounts ORDER BY category_id, id")).fetchall()
            mounts = [_get_mount_full(conn, r[0]) for r in rows]
        return JSONResponse({"mounts": mounts, "count": len(mounts)})
    except Exception as e:
        err = str(e)
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
            """)).mappings().fetchall()
        status  = [{"id": r["id"], "local_path": r["local_path"], "category": r["name"],
                    "is_mounted": _is_mounted(r["local_path"])} for r in rows]
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
            cat = conn.execute(
                text("SELECT id, name FROM categories WHERE name = :n"), {"n": cat_name}
            ).mappings().fetchone()
            if not cat:
                cat = conn.execute(
                    text("INSERT INTO categories (name) VALUES (:n) RETURNING id, name"),
                    {"n": cat_name}
                ).mappings().fetchone()
                logger.info(f"Catégorie créée automatiquement : {cat_name}")

            category_id   = cat["id"]
            category_name = cat["name"]

            row = conn.execute(text("""
                INSERT INTO mounts (mount_type, category_id, local_path, active)
                VALUES (:type, :cat, '', :active)
                RETURNING id
            """), {"type": payload.mount_type, "cat": category_id,
                   "active": payload.active}).mappings().fetchone()
            mount_id = row["id"]

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
            ).mappings().fetchone()
            if not mount:
                raise HTTPException(404, f"Montage {mount_id} introuvable")

            if payload.active is not None:
                conn.execute(
                    text("UPDATE mounts SET active = :a WHERE id = :id"),
                    {"a": payload.active, "id": mount_id}
                )

            if mount["mount_type"] == "smb":
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
                        text(f"UPDATE mount_smb SET {set_clause} WHERE mount_id = :mid"), updates
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
                        text(f"UPDATE mount_nfs SET {set_clause} WHERE mount_id = :mid"), updates
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
            """)).mappings().fetchall()

        desired_paths = {r["local_path"] for r in desired_rows}

        active_paths: set = set()
        try:
            with open("/proc/mounts") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2] in ("cifs", "nfs", "nfs4"):
                        active_paths.add(parts[1])
        except Exception:
            pass

        to_remove = active_paths - desired_paths
        to_add    = [r for r in desired_rows if r["local_path"] not in active_paths]
        report    = {"removed": [], "added": [], "errors": [],
                     "already_mounted": list(active_paths & desired_paths)}

        for path in to_remove:
            ok, err = _do_umount(path)
            (report["removed"] if ok else report["errors"]).append(
                path if ok else {"path": path, "action": "umount", "error": err}
            )

        with engine.connect() as conn:
            for r in to_add:
                mount_id   = r["id"]
                mount_type = r["mount_type"]
                local_path = r["local_path"]
                params = (
                    {"server": r["server"], "share": r["share"], "username": r["username"],
                     "password": r["password"], "domain": r["domain"],
                     "smb_version": r["smb_version"], "mount_options": r["smb_options"]}
                    if mount_type == "smb" else
                    {"server": r["nfs_server"], "export_path": r["export_path"],
                     "nfs_version": r["nfs_version"], "mount_options": r["nfs_options"]}
                )
                ok, err = _do_mount(local_path, mount_type, params)
                if ok:
                    report["added"].append(local_path)
                    conn.execute(text(
                        "UPDATE mounts SET last_mount_at=NOW(), last_error=NULL WHERE id=:id"
                    ), {"id": mount_id})
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


@router.get("/mounts/browse")
def browse_network(
    type: str,
    server: str,
    username: Optional[str] = None,
    password: Optional[str] = None
):
    """Liste les partages/exports disponibles sur un serveur (SMB/NFS)."""
    if type not in ("smb", "nfs"):
        raise HTTPException(400, "type doit être 'smb' ou 'nfs'")

    server_clean = server.lstrip("/")
    shares, error = [], None

    if type == "smb":
        if username:
            cmd = ["/usr/bin/smbclient", "-L", f"//{server_clean}",
                   "-U", f"{username}%{password or ''}"]
        else:
            cmd = ["/usr/bin/smbclient", "-N", "-L", f"//{server_clean}"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            for line in r.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[1] == "Disk":
                    shares.append("/" + parts[0])
            if r.returncode != 0 and not shares:
                error = r.stderr.strip() or r.stdout.strip()
        except FileNotFoundError:
            error = "Outil SMB non disponible — relancer le service pour l'installer automatiquement"
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
            error = "Outil NFS non disponible — relancer le service pour l'installer automatiquement"
        except subprocess.TimeoutExpired:
            error = "Timeout — serveur inaccessible ou NFS non activé"
        except Exception as e:
            error = str(e)

    return JSONResponse({"server": server, "type": type, "shares": shares, "error": error})


@router.get("/mounts/known-servers")
def get_known_servers():
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, server, mount_type, username, domain,
                       smb_version, nfs_version, note
                FROM known_servers
                ORDER BY server
            """)).mappings().fetchall()
        return JSONResponse([dict(r) for r in rows])
    except Exception as e:
        logger.error(f"get_known_servers: {e}")
        raise HTTPException(500, str(e))


@router.post("/mounts/known-servers")
def upsert_known_server(data: dict = Body(...)):
    """Crée ou met à jour un serveur connu (upsert sur le champ server)."""
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
            ), {"s": server}).mappings().fetchone()
        return JSONResponse({"success": True, "id": row["id"]})
    except Exception as e:
        logger.error(f"upsert_known_server: {e}")
        raise HTTPException(500, str(e))


@router.post("/mounts/batch")
def create_mounts_batch(data: dict = Body(...)):
    """Crée plusieurs montages en une seule requête depuis un même serveur."""
    server_info = data.get("server_info", {})
    mounts_in   = data.get("mounts", [])

    server     = (server_info.get("server") or "").strip()
    mount_type = (server_info.get("mount_type") or "smb").strip()

    if not server:
        raise HTTPException(400, "server_info.server obligatoire")
    if not mounts_in:
        raise HTTPException(400, "La liste mounts est vide")

    created: list = []
    errors:  list = []

    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO known_servers
                    (server, mount_type, username, password, domain, smb_version, nfs_version)
                VALUES
                    (:server, :mount_type, :username, :password, :domain, :smb_version, :nfs_version)
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

            for m in mounts_in:
                share = (m.get("share") or "").strip()
                if not share:
                    errors.append({"share": share, "error": "share vide"})
                    continue

                cat_id   = m.get("category_id")
                cat_name = (m.get("category_name") or "").strip().lower()

                if not cat_id and cat_name:
                    conn.execute(text("""
                        INSERT INTO categories (name)
                        VALUES (:name)
                        ON CONFLICT (name) DO NOTHING
                    """), {"name": cat_name})
                    row = conn.execute(text(
                        "SELECT id FROM categories WHERE name = :name"
                    ), {"name": cat_name}).mappings().fetchone()
                    cat_id = row["id"] if row else None

                if not cat_id:
                    errors.append({"share": share, "error": "catégorie introuvable"})
                    continue

                row_cat = conn.execute(text(
                    "SELECT name FROM categories WHERE id = :id"
                ), {"id": cat_id}).mappings().fetchone()
                if not row_cat:
                    errors.append({"share": share, "error": f"catégorie {cat_id} introuvable"})
                    continue

                try:
                    row_m = conn.execute(text("""
                        INSERT INTO mounts (mount_type, category_id, local_path, active)
                        VALUES (:mt, :cat, 'PLACEHOLDER', true)
                        RETURNING id
                    """), {"mt": mount_type, "cat": cat_id}).mappings().fetchone()
                    mount_id   = row_m["id"]
                    cat_name_v = row_cat["name"]
                    local_path = f"{MOUNT_BASE_PATH}/{cat_name_v}/{mount_id}-{cat_name_v}"

                    conn.execute(text(
                        "UPDATE mounts SET local_path = :lp WHERE id = :id"
                    ), {"lp": local_path, "id": mount_id})

                    if mount_type == "smb":
                        conn.execute(text("""
                            INSERT INTO mount_smb
                                (mount_id, server, share, username, password, domain, smb_version)
                            VALUES (:mid, :srv, :share, :user, :pwd, :dom, :ver)
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
                            "mid": mount_id,
                            "srv": server,
                            "share": share,
                            "ver": server_info.get("nfs_version", 4),
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

            from watcher.scanner import scan_queue
            for c in created:
                scan_queue.enqueue_priority(c["mount_id"])

        return JSONResponse({"success": True, "created": created, "errors": errors})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_mounts_batch: {e}")
        raise HTTPException(500, str(e))
