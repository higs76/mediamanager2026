#!/usr/bin/env bash

# MediaManager 2026 - Proxmox LXC Installation Script
# 
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/main/scripts/proxmox-install.sh)
#
# Ou localement:
#   bash proxmox-install.sh
#
# Ce script configure un LXC Ubuntu 24.04 avec MediaManager

set -e

# ==========================================
# Configuration (à adapter selon vos besoins)
# ==========================================

REPO_URL="${REPO_URL:-https://github.com/higs76/mediamanager2026.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
APP_DIR="/home/mediamanager/app"
PYTHON_VERSION="3.12"

# Couleurs pour les logs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ==========================================
# Fonctions utilitaires
# ==========================================

log_info() {
    echo -e "${BLUE}▶️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

log_error() {
    echo -e "${RED}✗ $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# ==========================================
# Vérifier que c'est un LXC Ubuntu
# ==========================================

check_environment() {
    log_info "Checking environment..."
    
    if [ ! -f /etc/os-release ]; then
        log_error "Not running on Linux"
        exit 1
    fi
    
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        log_warn "Not running on Ubuntu (found: $ID). This might not work."
    fi
    
    if [[ "$VERSION_ID" != "24.04" ]]; then
        log_warn "Not running Ubuntu 24.04 (found: $VERSION_ID). This might not work."
    fi
    
    log_success "Environment check passed"
}

# ==========================================
# Mettre à jour le système
# ==========================================

update_system() {
    log_info "Updating system packages..."
    
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get upgrade -y
    
    log_success "System updated"
}

# ==========================================
# Installer les dépendances
# ==========================================

install_dependencies() {
    log_info "Installing dependencies..."
    
    apt-get install -y --no-install-recommends \
        python${PYTHON_VERSION} \
        python${PYTHON_VERSION}-venv \
        python3-pip \
        postgresql \
        postgresql-contrib \
        git \
        cifs-utils \
        ffmpeg \
        mediainfo \
        curl \
        wget \
        nano \
        sudo
    
    log_success "Dependencies installed"
}

# ==========================================
# Créer l'utilisateur mediamanager
# ==========================================

create_user() {
    log_info "Creating mediamanager user..."


    if id "mediamanager" &>/dev/null; then
        log_warn "User mediamanager already exists"
    else
        useradd -m -s /bin/bash mediamanager
        echo "mediamanager:mediamanager" | chpasswd
        log_success "User mediamanager created (password: mediamanager)"
    fi

    # Droits sudo limités : uniquement mount/umount (montages SMB)
    # et redémarrage du service watcher.
    # Fichier dédié dans sudoers.d → pas de doublon si le script est relancé.
    cat > /etc/sudoers.d/mediamanager << 'SUDOEOF'
mediamanager ALL=(ALL) NOPASSWD: /bin/mount, /bin/umount, /usr/bin/systemctl restart mediamanager-watcher
SUDOEOF
    chmod 440 /etc/sudoers.d/mediamanager
    log_success "Sudoers configured (mount/umount/restart only)"

    # Activer l'authentification SSH par mot de passe.
    # Ubuntu 24.04 la désactive par défaut, ce qui empêche de se connecter
    # en SSH avec user/password depuis VSCode ou un terminal.
    if grep -q "^PasswordAuthentication" /etc/ssh/sshd_config 2>/dev/null; then
        sed -i 's/^PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
    else
        echo "PasswordAuthentication yes" >> /etc/ssh/sshd_config
    fi
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
    log_success "SSH password authentication enabled"

}

# ==========================================
# Créer la structure de répertoires
# ==========================================

create_directories() {
    log_info "Creating directories..."
    
    mkdir -p ${APP_DIR}
    mkdir -p /home/mediamanager/MediaManagerMnt
    mkdir -p /home/mediamanager/logs
    mkdir -p /home/mediamanager/data

    # Les sous-dossiers de MediaManagerMnt (series, films, etc.) sont créés
    # par l'application au démarrage, selon la configuration en base de données.
    chown -R mediamanager:mediamanager /home/mediamanager
    
    log_success "Directories created"
}

# ==========================================
# Cloner le repository
# ==========================================

clone_repository() {
    log_info "Cloning repository from ${REPO_URL}..."
    
    cd /home/mediamanager
    
    if [ -d "${APP_DIR}/.git" ]; then
        log_warn "Repository already exists, pulling latest changes..."
        cd ${APP_DIR}
        git pull origin ${REPO_BRANCH}
    else
        git clone -b ${REPO_BRANCH} ${REPO_URL} app
    fi
    
    chown -R mediamanager:mediamanager ${APP_DIR}
    
    log_success "Repository cloned"
}

# ==========================================
# Configurer Python et dépendances
# ==========================================

setup_python() {
    log_info "Setting up Python environment..."
    
    cd ${APP_DIR}
    
    # Créer le venv directement en tant que mediamanager
    # (si on le crée en root puis chown, certains chemins internes du venv
    # peuvent garder des références au home de root et poser des problèmes)
    sudo -u mediamanager python${PYTHON_VERSION} -m venv venv
    
    sudo -u mediamanager ./venv/bin/pip install --upgrade pip
    sudo -u mediamanager ./venv/bin/pip install -r requirements.txt
    
    # Créer .env uniquement s'il n'existe pas déjà
    # (évite d'écraser la config si on relance le script après une modif manuelle)
    if [ ! -f .env ]; then
        cp .env.example .env
        sed -i 's/changeme/mediamanager/g' .env
        chown mediamanager:mediamanager .env
        chmod 600 .env
    else
        log_warn ".env already exists, not overwritten"
    fi
    
    log_success "Python environment configured"
}

# ==========================================
# Configurer PostgreSQL
# ==========================================

setup_postgresql() {
    log_info "Setting up PostgreSQL..."
    
    # Démarrer PostgreSQL
    systemctl start postgresql
    systemctl enable postgresql
    sleep 2
    
    # Attendre que PostgreSQL soit prêt
    for i in {1..30}; do
        if sudo -u postgres psql -c "SELECT 1" > /dev/null 2>&1; then
            log_success "PostgreSQL is ready"
            break
        fi
        if [ $i -eq 30 ]; then
            log_error "PostgreSQL failed to start"
            exit 1
        fi
        sleep 1
    done
    
    # Créer utilisateur et BD
    log_info "Creating database user and schema..."

    sudo -u postgres psql -c "CREATE USER mediamanager WITH PASSWORD 'mediamanager';" 2>/dev/null || log_warn "User already exists"
    sudo -u postgres psql -c "ALTER USER mediamanager CREATEDB;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE mediamanager_db OWNER mediamanager;" 2>/dev/null || log_warn "Database already exists"
    
    
    
    # Initialiser les tables.
    # On reste avec l'utilisateur postgres (superuser Linux) pour exécuter le SQL.
    # PostgreSQL utilise l'auth "peer" par défaut : l'user Linux doit correspondre
    # à l'user PostgreSQL. On ne peut pas faire "sudo -u postgres psql -U mediamanager".
    log_info "Initializing database schema..."
    sudo -u postgres psql -d mediamanager_db -f ${APP_DIR}/database/schema.sql 2>/dev/null || log_warn "Schema might already exist"
    
    log_success "PostgreSQL configured"
}

# ==========================================
# Créer le systemd service
# ==========================================

setup_systemd_service() {
    log_info "Creating systemd service..."
    
    cat > /etc/systemd/system/mediamanager-watcher.service << 'SVCEOF'
[Unit]
Description=MediaManager Watcher Service
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=mediamanager
WorkingDirectory=/home/mediamanager/app
EnvironmentFile=/home/mediamanager/app/.env
Environment="PATH=/home/mediamanager/app/venv/bin"
ExecStart=/home/mediamanager/app/venv/bin/python run.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SVCEOF

    systemctl daemon-reload
    systemctl enable mediamanager-watcher.service
    
    log_success "Systemd service created"
}

# ==========================================
# Démarrer les services
# ==========================================

start_services() {
    log_info "Starting services..."
    
    systemctl start mediamanager-watcher.service
    sleep 3
    
    if systemctl is-active --quiet mediamanager-watcher.service; then
        log_success "MediaManager Watcher is running"
    else
        log_error "Failed to start MediaManager Watcher"
        systemctl status mediamanager-watcher.service
        exit 1
    fi
}

# ==========================================
# Afficher le résumé
# ==========================================

print_summary() {
    echo ""
    echo "=========================================="
    echo -e "${GREEN}  MediaManager Installation Complete${NC}"
    echo "=========================================="
    echo ""
    log_success "Installation finished successfully!"
    echo ""
    echo "📊 Admin Panel:"
    echo "   http://$(hostname -I | awk '{print $1}'):8000/admin/"
    echo ""
    echo "📚 API Documentation:"
    echo "   http://$(hostname -I | awk '{print $1}'):8000/docs"
    echo ""
    echo "📝 Default Credentials:"
    echo "   PostgreSQL User: mediamanager"
    echo "   PostgreSQL Password: mediamanager"
    echo "   Database: mediamanager_db"
    echo ""
    echo "📂 Directories:"
    echo "   App: ${APP_DIR}"
    echo "   Mounts: /home/mediamanager/MediaManagerMnt"
    echo "   Logs: /home/mediamanager/logs"
    echo ""
    echo "🔧 Useful Commands:"
    echo "   systemctl status mediamanager-watcher     # Check status"
    echo "   systemctl restart mediamanager-watcher    # Restart service"
    echo "   journalctl -u mediamanager-watcher -f     # View logs (Ctrl+C to exit)"
    echo ""
    echo "=========================================="
    echo ""
}

# ==========================================
# Main
# ==========================================

main() {
    echo ""
    echo "=========================================="
    echo "  MediaManager 2026 Installation"
    echo "=========================================="
    echo ""
    
    # Vérifier que root
    if [ "$EUID" -ne 0 ]; then 
        log_error "This script must be run as root"
        exit 1
    fi
    
    check_environment
    update_system
    install_dependencies
    create_user
    create_directories
    clone_repository
    setup_python
    setup_postgresql
    setup_systemd_service
    start_services
    print_summary
}

# Lancer l'installation
main