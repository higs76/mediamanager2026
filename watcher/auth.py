"""
MediaManager 2026 — Authentification
Hachage bcrypt, cookies de session signés (itsdangerous), dépendances FastAPI.
"""

import bcrypt as _bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi import Request, HTTPException
from fastapi.responses import Response

from watcher.config import SECRET_KEY

COOKIE_NAME    = "mm_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 jours

_ser = URLSafeTimedSerializer(SECRET_KEY)

# True quand au moins un utilisateur existe en base.
# Initialisé au démarrage par init_setup_flag(), mis à jour par mark_setup_done().
_setup_done: bool = False


# ── Mots de passe ─────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode()[:72], _bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode()[:72], hashed.encode())


# ── Cookie de session ──────────────────────────────────────────────────────────

def create_session(uid: int, role: str) -> str:
    return _ser.dumps({"uid": uid, "role": role})

def decode_session(token: str) -> dict | None:
    try:
        return _ser.loads(token, max_age=COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None

def set_user_cookie(response: Response, uid: int, role: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=create_session(uid, role),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/"
    )

def clear_user_cookie(response: Response) -> None:
    response.delete_cookie(key=COOKIE_NAME, path="/")


# ── Helpers request ───────────────────────────────────────────────────────────

def get_session(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE_NAME)
    return decode_session(token) if token else None

def require_auth(request: Request) -> dict:
    user = get_session(request)
    if not user:
        raise HTTPException(status_code=401, detail="Non authentifié")
    return user

def require_admin(request: Request) -> dict:
    user = require_auth(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Accès réservé à l'administrateur")
    return user


# ── Flag setup ────────────────────────────────────────────────────────────────

def init_setup_flag() -> None:
    """Vérifier en base si des utilisateurs existent. À appeler après init_database_tables()."""
    global _setup_done
    try:
        from watcher.database import engine
        from sqlalchemy import text
        with engine.connect() as conn:
            row = conn.execute(text("SELECT COUNT(*) FROM users")).fetchone()
            _setup_done = bool(row and row[0] > 0)
    except Exception:
        _setup_done = False

def mark_setup_done() -> None:
    global _setup_done
    _setup_done = True

def is_setup_needed() -> bool:
    return not _setup_done
