"""
Gestion de la connexion à la base de données PostgreSQL
"""

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import NullPool

from watcher.config import DATABASE_URL

logger = logging.getLogger(__name__)

# Créer le moteur de BD
# NullPool = pas de pool de connexions (utile pour dev/test)
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Met à True pour voir les requêtes SQL
    poolclass=NullPool
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
    Teste si la connexion à la BD fonctionne
    Retourne True si OK, False sinon
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            logger.info("✓ Connexion BD OK")
            return True
    except Exception as e:
        logger.error(f"✗ Erreur connexion BD : {e}")
        return False