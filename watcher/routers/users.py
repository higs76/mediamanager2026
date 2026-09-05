"""
MediaManager 2026 — Router Users (admin only)
GET    /api/admin/users          — liste des utilisateurs
POST   /api/admin/users          — créer un utilisateur
PUT    /api/admin/users/{id}/password — changer le mot de passe
DELETE /api/admin/users/{id}     — supprimer un utilisateur
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from watcher.database import engine
from watcher.auth import hash_password, require_admin

router = APIRouter(prefix="/users", tags=["users"])


class CreateUser(BaseModel):
    username: str
    role: str = "viewer"
    password: str


class ChangePassword(BaseModel):
    password: str


@router.get("")
def list_users(admin=Depends(require_admin)):
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, username, role, created_at FROM users ORDER BY created_at"
        )).fetchall()
    return JSONResponse({"users": [
        {
            "id":         r[0],
            "username":   r[1],
            "role":       r[2],
            "created_at": r[3].strftime("%d/%m/%Y") if r[3] else "—",
        }
        for r in rows
    ]})


@router.post("")
def create_user(body: CreateUser, admin=Depends(require_admin)):
    if not body.username.strip():
        return JSONResponse({"detail": "Nom d'utilisateur requis"}, status_code=422)
    if len(body.password) < 6:
        return JSONResponse({"detail": "Mot de passe trop court (6 caractères minimum)"}, status_code=422)
    if body.role not in ("admin", "viewer"):
        return JSONResponse({"detail": "Rôle invalide (admin ou viewer)"}, status_code=422)
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "INSERT INTO users (username, role, password_hash) VALUES (:u, :r, :h) RETURNING id"
            ), {"u": body.username.strip(), "r": body.role, "h": hash_password(body.password)}).fetchone()
            conn.commit()
        return JSONResponse({"id": row[0], "username": body.username.strip(), "role": body.role})
    except Exception:
        return JSONResponse({"detail": "Ce nom d'utilisateur est déjà utilisé"}, status_code=409)


@router.put("/{uid}/password")
def change_password(uid: int, body: ChangePassword, admin=Depends(require_admin)):
    if len(body.password) < 6:
        return JSONResponse({"detail": "Mot de passe trop court (6 caractères minimum)"}, status_code=422)
    with engine.connect() as conn:
        result = conn.execute(text(
            "UPDATE users SET password_hash = :h WHERE id = :id"
        ), {"h": hash_password(body.password), "id": uid})
        conn.commit()
    if result.rowcount == 0:
        return JSONResponse({"detail": "Utilisateur non trouvé"}, status_code=404)
    return JSONResponse({"ok": True})


@router.delete("/{uid}")
def delete_user(uid: int, admin=Depends(require_admin)):
    if admin["uid"] == uid:
        return JSONResponse({"detail": "Impossible de supprimer votre propre compte"}, status_code=400)
    with engine.connect() as conn:
        result = conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": uid})
        conn.commit()
    if result.rowcount == 0:
        return JSONResponse({"detail": "Utilisateur non trouvé"}, status_code=404)
    return JSONResponse({"ok": True})
