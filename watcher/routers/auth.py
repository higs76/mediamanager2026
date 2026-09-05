"""
MediaManager 2026 — Router Auth
POST /api/auth/login   — connexion
POST /api/auth/logout  — déconnexion
POST /api/auth/setup   — création du compte admin (1er démarrage)
GET  /api/auth/me      — infos utilisateur courant
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from watcher.database import engine
from watcher.auth import (
    verify_password, hash_password,
    set_user_cookie, clear_user_cookie,
    get_session, is_setup_needed, mark_setup_done,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: Credentials):
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id, role, password_hash FROM users WHERE username = :u"
        ), {"u": body.username.strip()}).fetchone()

    if not row or not verify_password(body.password, row[2]):
        return JSONResponse({"detail": "Identifiants incorrects"}, status_code=401)

    resp = JSONResponse({"role": row[1], "username": body.username.strip()})
    set_user_cookie(resp, uid=row[0], role=row[1])
    return resp


@router.post("/logout")
def logout():
    resp = JSONResponse({"ok": True})
    clear_user_cookie(resp)
    return resp


@router.post("/setup")
def setup(body: Credentials):
    if not is_setup_needed():
        return JSONResponse({"detail": "Compte admin déjà configuré"}, status_code=400)
    if not body.username.strip():
        return JSONResponse({"detail": "Nom d'utilisateur requis"}, status_code=422)
    if len(body.password) < 6:
        return JSONResponse({"detail": "Mot de passe trop court (6 caractères minimum)"}, status_code=422)

    with engine.connect() as conn:
        row = conn.execute(text(
            "INSERT INTO users (username, role, password_hash) VALUES (:u, 'admin', :h) RETURNING id"
        ), {"u": body.username.strip(), "h": hash_password(body.password)}).fetchone()
        conn.commit()

    mark_setup_done()
    resp = JSONResponse({"ok": True})
    set_user_cookie(resp, uid=row[0], role="admin")
    return resp


@router.get("/me")
def me(request: Request):
    user = get_session(request)
    if not user:
        return JSONResponse({"detail": "Non authentifié"}, status_code=401)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT username, role FROM users WHERE id = :id"
        ), {"id": user["uid"]}).fetchone()
    if not row:
        return JSONResponse({"detail": "Utilisateur non trouvé"}, status_code=404)
    return JSONResponse({"uid": user["uid"], "username": row[0], "role": row[1]})
