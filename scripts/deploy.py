"""
Script de déploiement et configuration - MediaManager 2026

Usage:
    python scripts/deploy.py --setup              # Setup complet
    python scripts/deploy.py --create-db          # Créer BD uniquement
    python scripts/deploy.py --init-tables        # Initialiser tables
    python scripts/deploy.py --check              # Vérifier installation
    python scripts/deploy.py --backup             # Backup BD
    python scripts/deploy.py --restore <file>    # Restaurer BD

À exécuter sur la VM Linux Proxmox après git clone
"""

import os
import sys
import argparse
import subprocess
import logging
from pathlib import Path
from dotenv import load_dotenv

# Configuration logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Charger .env s'il existe
if Path('.env').exists():
    load_dotenv()
else:
    logger.warning("⚠️  .env non trouvé, utilisation des valeurs par défaut")
    load_dotenv('.env.example')


class MediaManagerDeploy:
    """Classe pour gérer le déploiement de MediaManager"""

    def __init__(self):
        self.project_root = Path(__file__).parent.parent
        self.db_host = os.getenv('DATABASE_URL', '').split('@')[-1].split(':')[0] or 'localhost'
        self.db_name = os.getenv('DATABASE_URL', '').split('/')[-1] or 'mediamanager_db'
        self.db_user = os.getenv('DATABASE_URL', '').split('://')[1].split(':')[0] if '://' in os.getenv('DATABASE_URL', '') else 'mediamanager'
        self.mount_base = os.getenv('MOUNT_BASE_PATH', '/home/mediamanager/MediaManagerMnt')
        
    def log_section(self, title):
        """Affiche un titre de section"""
        logger.info(f"\n{'='*60}")
        logger.info(f"  {title}")
        logger.info(f"{'='*60}\n")

    def run_command(self, cmd, description=""):
        """Exécute une commande shell"""
        if description:
            logger.info(f"▶️  {description}")
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                logger.error(f"✗ Erreur : {result.stderr}")
                return False
            else:
                if result.stdout:
                    logger.info(f"✓ {result.stdout.strip()}")
                return True
        except Exception as e:
            logger.error(f"✗ Exception : {e}")
            return False

    def check_system(self):
        """Vérifie que les dépendances système sont installées"""
        self.log_section("VÉRIFICATION SYSTÈME")
        
        checks = {
            "python3": "python3 --version",
            "pip": "pip --version",
            "psql": "psql --version",
            "git": "git --version",
            "ffprobe": "ffprobe -version 2>/dev/null | head -1",
            "mediainfo": "mediainfo --version 2>/dev/null | head -1",
        }
        
        all_ok = True
        for name, cmd in checks.items():
            if self.run_command(cmd, f"Vérification {name}"):
                logger.info(f"✓ {name} OK")
            else:
                logger.error(f"✗ {name} MANQUANT ou ERREUR")
                all_ok = False
        
        return all_ok

    def create_python_env(self):
        """Crée l'environnement Python virtuel"""
        self.log_section("CRÉATION ENVIRONNEMENT PYTHON")
        
        venv_path = self.project_root / 'venv'
        
        if venv_path.exists():
            logger.info(f"✓ venv existe déjà : {venv_path}")
        else:
            if self.run_command(
                f"python3 -m venv {venv_path}",
                "Création venv"
            ):
                logger.info(f"✓ venv créé : {venv_path}")
            else:
                return False
        
        # Activer et installer dépendances
        activate_cmd = f"source {venv_path}/bin/activate && "
        if self.run_command(
            f"{activate_cmd}pip install --upgrade pip",
            "Upgrade pip"
        ):
            logger.info("✓ pip à jour")
        
        if self.run_command(
            f"{activate_cmd}pip install -r {self.project_root}/requirements.txt",
            "Installation dépendances Python"
        ):
            logger.info("✓ Dépendances Python installées")
            return True
        else:
            logger.error("✗ Erreur installation dépendances")
            return False

    def create_folders(self):
        """Crée les dossiers nécessaires"""
        self.log_section("CRÉATION DOSSIERS")
        
        folders = [
            self.mount_base,
            self.project_root / 'logs',
            self.project_root / 'cache',
            self.mount_base / 'series',
            self.mount_base / 'films',
            self.mount_base / 'animes',
            self.mount_base / 'documentaires',
        ]
        
        for folder in folders:
            folder_path = Path(folder)
            if folder_path.exists():
                logger.info(f"✓ Dossier existe : {folder_path}")
            else:
                try:
                    folder_path.mkdir(parents=True, exist_ok=True)
                    logger.info(f"✓ Dossier créé : {folder_path}")
                except Exception as e:
                    logger.error(f"✗ Erreur création {folder_path} : {e}")
                    return False
        
        return True

    def create_database(self):
        """Crée la base de données PostgreSQL"""
        self.log_section("CRÉATION BASE DE DONNÉES")
        
        # Vérifier connexion PostgreSQL
        logger.info("▶️  Vérification accès PostgreSQL...")
        if not self.run_command(
            f"psql -h {self.db_host} -U postgres -c 'SELECT 1'",
            ""
        ):
            logger.error("✗ Impossible de se connecter à PostgreSQL")
            logger.error("   Assurez-vous que PostgreSQL est démarré et accessible")
            return False
        
        logger.info("✓ Connexion PostgreSQL OK")
        
        # Créer user
        logger.info(f"▶️  Création utilisateur {self.db_user}...")
        self.run_command(
            f"psql -h {self.db_host} -U postgres -c \"CREATE USER {self.db_user} WITH PASSWORD 'changeme'\" 2>/dev/null || true",
            ""
        )
        
        # Créer BD
        logger.info(f"▶️  Création base {self.db_name}...")
        self.run_command(
            f"psql -h {self.db_host} -U postgres -c \"CREATE DATABASE {self.db_name} OWNER {self.db_user}\" 2>/dev/null || true",
            ""
        )
        
        logger.info(f"✓ Base {self.db_name} créée")
        return True

    def init_tables(self):
        """Initialise les tables de la BD"""
        self.log_section("INITIALISATION TABLES")
        
        schema_file = self.project_root / 'database' / 'schema.sql'
        
        if not schema_file.exists():
            logger.error(f"✗ Fichier schema.sql non trouvé : {schema_file}")
            return False
        
        logger.info(f"▶️  Exécution {schema_file}...")
        
        cmd = f"psql -h {self.db_host} -U {self.db_user} -d {self.db_name} -f {schema_file}"
        if self.run_command(cmd, ""):
            logger.info("✓ Tables créées avec succès")
            return True
        else:
            logger.error("✗ Erreur création tables")
            return False

    def verify_installation(self):
        """Vérifie que tout est correctement installé"""
        self.log_section("VÉRIFICATION INSTALLATION")
        
        checks_ok = True
        
        # Vérifier Python
        if self.run_command("python3 -c 'import fastapi'", ""):
            logger.info("✓ FastAPI importable")
        else:
            logger.error("✗ FastAPI non disponible")
            checks_ok = False
        
        # Vérifier BD
        if self.run_command(
            f"psql -h {self.db_host} -U {self.db_user} -d {self.db_name} -c 'SELECT 1'",
            ""
        ):
            logger.info("✓ Connexion BD OK")
        else:
            logger.error("✗ Impossible de se connecter à la BD")
            checks_ok = False
        
        # Vérifier dossiers
        if Path(self.mount_base).exists():
            logger.info(f"✓ Dossier montages existe : {self.mount_base}")
        else:
            logger.error(f"✗ Dossier montages manquant : {self.mount_base}")
            checks_ok = False
        
        return checks_ok

    def full_setup(self):
        """Exécute le setup complet"""
        self.log_section("SETUP COMPLET MEDIAMANAGER 2026")
        
        steps = [
            ("Vérification système", self.check_system),
            ("Création environnement Python", self.create_python_env),
            ("Création dossiers", self.create_folders),
            ("Création base de données", self.create_database),
            ("Initialisation tables", self.init_tables),
            ("Vérification finale", self.verify_installation),
        ]
        
        for step_name, step_func in steps:
            logger.info(f"\n📋 {step_name}...")
            if not step_func():
                logger.error(f"\n❌ ERREUR : {step_name} a échoué")
                return False
        
        self.log_section("✅ SETUP TERMINÉ AVEC SUCCÈS !")
        logger.info("""
Prochaines étapes :
  1. Modifiez .env avec vos paramètres réels
  2. Lancez le watcher : python watcher/app.py
  3. Accédez à l'API : http://localhost:8000/health
  
Documentation : README.md
        """)
        return True

    def backup_database(self):
        """Sauvegarde la base de données"""
        self.log_section("BACKUP BASE DE DONNÉES")
        
        from datetime import datetime
        backup_file = f"backup_mediamanager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        
        logger.info(f"▶️  Sauvegarde dans {backup_file}...")
        
        cmd = f"pg_dump -h {self.db_host} -U {self.db_user} -d {self.db_name} > {backup_file}"
        if self.run_command(cmd, ""):
            logger.info(f"✓ Backup créé : {backup_file}")
            return True
        else:
            logger.error("✗ Erreur backup")
            return False

    def restore_database(self, backup_file):
        """Restaure la base de données"""
        self.log_section("RESTAURATION BASE DE DONNÉES")
        
        if not Path(backup_file).exists():
            logger.error(f"✗ Fichier backup non trouvé : {backup_file}")
            return False
        
        logger.warning(f"⚠️  Cette opération va écraser la BD {self.db_name}")
        confirm = input("Continuez ? (y/N) : ").lower()
        if confirm != 'y':
            logger.info("❌ Restauration annulée")
            return False
        
        logger.info(f"▶️  Restauration depuis {backup_file}...")
        
        cmd = f"psql -h {self.db_host} -U {self.db_user} -d {self.db_name} < {backup_file}"
        if self.run_command(cmd, ""):
            logger.info("✓ Restauration complète")
            return True
        else:
            logger.error("✗ Erreur restauration")
            return False


def main():
    """Point d'entrée du script"""
    parser = argparse.ArgumentParser(
        description='Script de déploiement MediaManager 2026'
    )
    
    parser.add_argument(
        '--setup',
        action='store_true',
        help='Setup complet (par défaut)'
    )
    parser.add_argument(
        '--create-db',
        action='store_true',
        help='Créer la base de données uniquement'
    )
    parser.add_argument(
        '--init-tables',
        action='store_true',
        help='Initialiser les tables'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Vérifier l\'installation'
    )
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Sauvegarder la BD'
    )
    parser.add_argument(
        '--restore',
        type=str,
        help='Restaurer la BD depuis un backup'
    )
    
    args = parser.parse_args()
    
    deployer = MediaManagerDeploy()
    
    if args.restore:
        success = deployer.restore_database(args.restore)
    elif args.backup:
        success = deployer.backup_database()
    elif args.check:
        success = deployer.verify_installation()
    elif args.create_db:
        success = deployer.create_database()
    elif args.init_tables:
        success = deployer.init_tables()
    else:
        # Par défaut : setup complet
        success = deployer.full_setup()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()