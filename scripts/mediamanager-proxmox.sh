#!/usr/bin/env bash

# MediaManager 2026 - Proxmox LXC Installer
# Installation script for Proxmox VE
#
# Usage:
#   bash <(curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/main/scripts/mediamanager-proxmox.sh)
#
# Ou localement:
#   bash mediamanager-proxmox.sh
#
# Ce script crée et configure un LXC Ubuntu 24.04 avec MediaManager

set -e

# ==========================================
# Configuration par défaut
# ==========================================

CTID="auto"                           # Container ID (auto = prochain disponible)
VMBRIDGE="vmbr0"                      # Bridge réseau
STORAGE="local-lvm"                   # Storage principal
HOSTNAME="mediamanager"               # Hostname du LXC
IP="dhcp"                             # IP (dhcp ou format CIDR: 192.168.1.100/24)
GATEWAY=""                            # Gateway (vide = auto-détection)
CORES="2"                             # CPU cores
MEMORY="4096"                         # RAM en MB
DISK="50"                             # Disque en GB
ROOTFS="$STORAGE:$DISK"              # Format rootfs

REPO_URL="https://github.com/higs76/mediamanager2026.git"
REPO_BRANCH="main"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==========================================
# Fonctions
# ==========================================

log_info() {
    echo -e "${BLUE}▶️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

log_error() {
    echo -e "${RED}✗ $1${NC}"
    exit 1
}

log_warn() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# ==========================================
# Vérifier que c'est Proxmox
# ==========================================

check_proxmox() {
    log_info "Checking Proxmox environment..."
    
    if ! command -v pvesh &> /dev/null; then
        log_error "This script must be run on Proxmox VE"
    fi
    
    if ! command -v pct &> /dev/null; then
        log_error "pct command not found. This script requires Proxmox VE."
    fi
    
    log_success "Running on Proxmox VE"
}

# ==========================================
# Parser les arguments
# ==========================================

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --vmid)
                CTID="$2"
                shift 2
                ;;
            --name)
                HOSTNAME="$2"
                shift 2
                ;;
            --ip)
                IP="$2"
                shift 2
                ;;
            --gateway)
                GATEWAY="$2"
                shift 2
                ;;
            --cores)
                CORES="$2"
                shift 2
                ;;
            --memory)
                MEMORY="$2"
                shift 2
                ;;
            --disk)
                DISK="$2"
                ROOTFS="$STORAGE:$DISK"
                shift 2
                ;;
            --storage)
                STORAGE="$2"
                ROOTFS="$STORAGE:$DISK"
                shift 2
                ;;
            --bridge)
                VMBRIDGE="$2"
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                ;;
        esac
    done
}

# ==========================================
# Afficher l'aide
# ==========================================

show_help() {
    cat << EOF
MediaManager 2026 - Proxmox LXC Installer

Usage: bash mediamanager-proxmox.sh [OPTIONS]

Options:
    --vmid ID              Container ID (default: auto)
    --name HOSTNAME        Hostname (default: mediamanager)
    --ip IP/MASK           IP address with CIDR (default: 192.168.1.100/24)
    --gateway IP           Gateway IP (default: 192.168.1.1)
    --cores N              CPU cores (default: 2)
    --memory MB            RAM in MB (default: 4096)
    --disk GB              Disk size in GB (default: 50)
    --storage STORAGE      Storage pool (default: local-lvm)
    --bridge BRIDGE        Network bridge (default: vmbr0)
    --help                 Show this help message

Examples:
    # Default installation
    bash mediamanager-proxmox.sh

    # Custom configuration
    bash mediamanager-proxmox.sh --vmid 200 --name mediamanager-prod --ip 192.168.1.100/24

    # Maximum resources
    bash mediamanager-proxmox.sh --cores 4 --memory 8192 --disk 100

EOF
}

# ==========================================
# Mode interactif
# ==========================================

interactive_mode() {
    log_info "Interactive Configuration Mode"
    echo ""
    
    read -p "Enter Container ID (default: auto): " input
    if [ ! -z "$input" ]; then CTID="$input"; fi
    
    read -p "Enter Hostname (default: mediamanager): " input
    if [ ! -z "$input" ]; then HOSTNAME="$input"; fi
    
    read -p "Enter IP/CIDR or 'dhcp' (default: dhcp): " input
    if [ ! -z "$input" ]; then IP="$input"; fi
    
    read -p "Enter Gateway IP (default: auto-detect): " input
    if [ ! -z "$input" ]; then GATEWAY="$input"; fi
    
    read -p "Enter CPU Cores (default: 2): " input
    if [ ! -z "$input" ]; then CORES="$input"; fi
    
    read -p "Enter Memory in MB (default: 4096): " input
    if [ ! -z "$input" ]; then MEMORY="$input"; fi
    
    read -p "Enter Disk Size in GB (default: 50): " input
    if [ ! -z "$input" ]; then DISK="$input"; ROOTFS="$STORAGE:$DISK"; fi
    
    read -p "Enter Storage Pool (default: local-lvm): " input
    if [ ! -z "$input" ]; then STORAGE="$input"; ROOTFS="$STORAGE:$DISK"; fi
    
    read -p "Enter Network Bridge (default: vmbr0): " input
    if [ ! -z "$input" ]; then VMBRIDGE="$input"; fi
}

# ==========================================
# Afficher la configuration
# ==========================================

show_configuration() {
    echo ""
    echo "=========================================="
    echo "  Configuration Summary"
    echo "=========================================="
    echo ""
    echo "  Container ID:    $CTID"
    echo "  Hostname:        $HOSTNAME"
    if [ "$IP" = "dhcp" ]; then
        echo "  IP Address:      DHCP"
    else
        echo "  IP Address:      $IP"
    fi
    echo "  Gateway:         $GATEWAY"
    echo "  CPU Cores:       $CORES"
    echo "  Memory:          ${MEMORY}MB"
    echo "  Disk:            ${DISK}GB"
    echo "  Storage:         $STORAGE"
    echo "  Bridge:          $VMBRIDGE"
    echo ""
    echo "=========================================="
    echo ""
    
    read -p "Continue with these settings? (y/n): " -r
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_warn "Installation cancelled"
        exit 0
    fi
}

# ==========================================
# Obtenir le prochain CTID disponible
# ==========================================

get_next_ctid() {
    if [ "$CTID" = "auto" ]; then
        log_info "Finding next available Container ID..."
        
        # Trouver le dernier CTID utilisé
        LAST_CTID=$(pct list 2>/dev/null | tail -n +2 | awk '{print $1}' | sort -n | tail -1)
        
        if [ -z "$LAST_CTID" ]; then
            CTID=100
        else
            CTID=$((LAST_CTID + 1))
        fi
        
        # Vérifier que le CTID est vraiment libre
        while pct status $CTID &>/dev/null; do
            CTID=$((CTID + 1))
        done
        
        log_success "Using Container ID: $CTID"
    fi
}

# ==========================================
# Vérifier que le CTID est disponible
# ==========================================

check_ctid() {
    if pct status $CTID &>/dev/null; then
        log_error "Container ID $CTID already exists"
    fi
    log_success "Container ID $CTID is available"
}

# ==========================================
# Vérifier les ressources disponibles
# ==========================================

check_resources() {
    log_info "Checking available resources..."
    
    # Vérifier le storage
    if ! pvesh get /storage/$STORAGE &>/dev/null; then
        log_error "Storage '$STORAGE' not found"
    fi
    
    # Vérifier le bridge
    if ! ip link show $VMBRIDGE &>/dev/null; then
        log_error "Network bridge '$VMBRIDGE' not found"
    fi
    
    log_success "Resources available"
}

# ==========================================
# Créer le LXC
# ==========================================

create_lxc() {
    log_info "Creating LXC container $CTID..."
    
    # Préparer la configuration réseau
    if [ "$IP" = "dhcp" ]; then
        NET_CONFIG="name=eth0,bridge=$VMBRIDGE,type=veth"
        log_info "Using DHCP for networking"
    else
        NET_CONFIG="name=eth0,bridge=$VMBRIDGE,ip=$IP,gw=$GATEWAY,type=veth"
    fi
    
    pct create $CTID ubuntu-24.04-standard_24.04-1_amd64.tar.zst \
        --arch amd64 \
        --cores $CORES \
        --memory $MEMORY \
        --swap 0 \
        --storage $STORAGE \
        --rootfs $ROOTFS \
        --hostname $HOSTNAME \
        --net0 $NET_CONFIG \
        --unprivileged 1 \
        --onboot 1 \
        --start 1
    
    log_success "LXC container created: $CTID"
}

# ==========================================
# Attendre que le LXC démarre
# ==========================================

wait_for_lxc() {
    log_info "Waiting for container to start..."
    
    for i in {1..30}; do
        if pct exec $CTID -- test -f /etc/os-release 2>/dev/null; then
            log_success "Container is running"
            return 0
        fi
        sleep 1
    done
    
    log_error "Container failed to start"
}

# ==========================================
# Installer MediaManager dans le LXC
# ==========================================

install_mediamanager() {
    log_info "Installing MediaManager in container..."
    
    # Script d'installation à exécuter dans le LXC
    INSTALL_SCRIPT='
    #!/bin/bash
    set -e
    
    export DEBIAN_FRONTEND=noninteractive
    
    echo "Updating system..."
    apt-get update
    apt-get upgrade -y
    
    echo "Installing dependencies..."
    apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3-pip \
        postgresql postgresql-contrib \
        git cifs-utils ffmpeg mediainfo curl wget nano sudo
    
    echo "Creating mediamanager user..."
    useradd -m -s /bin/bash mediamanager || true
    usermod -aG sudo mediamanager || true
    echo "mediamanager ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers || true
    
    echo "Creating directories..."
    mkdir -p /home/mediamanager/app
    mkdir -p /home/mediamanager/MediaManagerMnt/{series,films,animes,documentaires}
    mkdir -p /home/mediamanager/logs
    chown -R mediamanager:mediamanager /home/mediamanager
    
    echo "Starting PostgreSQL..."
    systemctl start postgresql
    systemctl enable postgresql
    sleep 2
    
    echo "Configuring PostgreSQL..."
    sudo -u postgres psql -c "CREATE USER mediamanager WITH PASSWORD '"'"'mediamanager'"'"';" 2>/dev/null || true
    sudo -u postgres psql -c "ALTER USER mediamanager CREATEDB;" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE mediamanager_db OWNER mediamanager;" 2>/dev/null || true
    
    echo "Cloning repository..."
    cd /home/mediamanager/app
    git clone -b main '"'"'$REPO_URL'"'"' . 2>/dev/null || git pull origin main
    
    echo "Setting up Python environment..."
    python3.12 -m venv venv
    venv/bin/pip install --upgrade pip
    venv/bin/pip install -r requirements.txt
    
    echo "Creating .env file..."
    cp .env.example .env
    sed -i '"'"'s/changeme/mediamanager/g'"'"' .env
    
    echo "Initializing database..."
    sudo -u postgres psql -U mediamanager -d mediamanager_db -f database/schema.sql 2>/dev/null || true
    
    echo "Creating systemd service..."
    cat > /etc/systemd/system/mediamanager-watcher.service << '"'"'SYSCTL'"'"'
[Unit]
Description=MediaManager Watcher Service
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=mediamanager
WorkingDirectory=/home/mediamanager/app
Environment="PATH=/home/mediamanager/app/venv/bin"
ExecStart=/home/mediamanager/app/venv/bin/python run.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
SYSCTL
    
    systemctl daemon-reload
    systemctl enable mediamanager-watcher.service
    systemctl start mediamanager-watcher.service
    
    echo "Installation complete!"
    '
    
    pct push $CTID - /tmp/install.sh << 'EOFSCRIPT'
$INSTALL_SCRIPT
EOFSCRIPT
    
    pct exec $CTID -- chmod +x /tmp/install.sh
    pct exec $CTID -- bash /tmp/install.sh
    
    log_success "MediaManager installed"
}

# ==========================================
# Afficher le résumé final
# ==========================================

print_summary() {
    echo ""
    echo "=========================================="
    echo -e "${GREEN}  MediaManager Installation Complete${NC}"
    echo "=========================================="
    echo ""
    
    # Obtenir l'IP réelle du container
    CONTAINER_IP=$(pct exec $CTID -- hostname -I | awk '{print $1}')
    
    log_success "LXC Container: $CTID"
    log_success "Hostname: $HOSTNAME"
    log_success "IP Address: $CONTAINER_IP"
    echo ""
    
    echo "📊 Access URLs:"
    echo "   Admin Panel:  http://$CONTAINER_IP:8000/admin/"
    echo "   API Docs:     http://$CONTAINER_IP:8000/docs"
    echo ""
    
    echo "📝 Default Credentials:"
    echo "   PostgreSQL User: mediamanager"
    echo "   PostgreSQL Password: mediamanager"
    echo ""
    
    echo "🔧 Useful Commands:"
    echo "   View status:     pct status $CTID"
    echo "   View console:    pct console $CTID"
    echo "   Execute command: pct exec $CTID -- command"
    echo "   Delete:          pct destroy $CTID"
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
    echo "  MediaManager 2026 - Proxmox Installer"
    echo "=========================================="
    echo ""
    
    check_proxmox
    
    # Mode interactif si pas d'arguments
    if [ $# -eq 0 ]; then
        interactive_mode
    else
        parse_arguments "$@"
    fi
    
    get_next_ctid
    detect_gateway
    check_ctid
    check_resources
    show_configuration
    
    create_lxc
    wait_for_lxc
    install_mediamanager
    print_summary
}

# Lancer l'installation
main "$@"