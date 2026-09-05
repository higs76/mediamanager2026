"""
Gestion de la connexion à la base de données PostgreSQL
"""

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

from watcher.config import DATABASE_URL

logger = logging.getLogger(__name__)

# État connu de la connexion — None = jamais testé
_db_state: bool | None = None

# Créer le moteur de BD
# NullPool = pas de pool de connexions (utile pour dev/test)
engine = create_engine(
    DATABASE_URL,
    echo=False,
    poolclass=NullPool,
    connect_args={"client_encoding": "utf8"}
)

# Créer une session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

def get_db_session() -> Session:
    """
    Récupère une session BD.
    À utiliser avec un context manager.
    
    Exemple :
        session = get_db_session()
        try:
            # utiliser session
        finally:
            session.close()
    """
    return SessionLocal()

def test_db_connection() -> bool:
    """
    Teste si la connexion à la BD fonctionne.
    Ne loggue que sur changement d'état (évite le spam en état stable).
    """
    global _db_state
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        if _db_state is not True:
            logger.info("✓ Connexion BD OK")
            _db_state = True
        return True
    except Exception as e:
        if _db_state is not False:
            logger.error(f"✗ Erreur connexion BD : {e}")
            _db_state = False
        return False