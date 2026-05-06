#!/bin/bash

# MediaManager Docker Entrypoint Script
# Lance les services et démarre l'application

set -e

echo "=========================================="
echo "  MediaManager Watcher - Starting"
echo "=========================================="

# ==========================================
# Démarrer PostgreSQL
# ==========================================
echo "▶️  Starting PostgreSQL..."
service postgresql start
sleep 2

# Attendre que PostgreSQL soit prêt
for i in {1..30}; do
    if sudo -u postgres psql -c "SELECT 1" > /dev/null 2>&1; then
        echo "✓ PostgreSQL is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "✗ PostgreSQL failed to start"
        exit 1
    fi
    sleep 1
done

# ==========================================
# Vérifier/créer la BD
# ==========================================
echo "▶️  Checking database..."

DB_EXISTS=$(sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -w mediamanager_db | wc -l)

if [ $DB_EXISTS -eq 0 ]; then
    echo "▶️  Creating database..."
    sudo -u postgres psql -c "CREATE USER mediamanager WITH PASSWORD 'mediamanager';" 2>/dev/null || true
    sudo -u postgres psql -c "ALTER USER mediamanager CREATEDB;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE mediamanager_db OWNER mediamanager;" 2>/dev/null || true
    
    echo "▶️  Initializing database schema..."
    sudo -u postgres psql -U mediamanager -d mediamanager_db -f /home/mediamanager/app/database/schema.sql
    echo "✓ Database created and initialized"
else
    echo "✓ Database already exists"
fi

# ==========================================
# Démarrer le watcher
# ==========================================
echo "▶️  Starting Watcher Service..."

cd /home/mediamanager/app

case "$1" in
    start)
        # Mode production (détaché)
        systemctl daemon-reload
        systemctl enable mediamanager-watcher.service
        systemctl start mediamanager-watcher.service
        echo "✓ Watcher started"
        echo "▶️  API available at http://0.0.0.0:8000"
        echo "▶️  Admin Panel at http://0.0.0.0:8000/admin/"
        echo "▶️  API Docs at http://0.0.0.0:8000/docs"
        
        # Garder le conteneur actif
        echo "▶️  Keeping container alive..."
        tail -f /var/log/syslog
        ;;
    
    dev)
        # Mode développement (foreground)
        echo "✓ Running in development mode"
        source venv/bin/activate
        python run.py
        ;;
    
    shell)
        # Shell interactif
        /bin/bash
        ;;
    
    *)
        echo "Usage: $0 {start|dev|shell}"
        exit 1
        ;;
esac