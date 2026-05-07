#!/usr/bin/env bash

# MediaManager 2026 - Proxmox LXC Installer (Simple Version)
# 
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/raw/main/scripts/mediamanager-proxmox.sh)

set -e

CTID="auto"
HOSTNAME="mediamanager"
CORES="2"
MEMORY="4096"
DISK="50"
STORAGE="local-lvm"
VMBRIDGE="vmbr0"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}▶️  $1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_error() { echo -e "${RED}✗ $1${NC}"; exit 1; }

# Vérifier Proxmox
if ! command -v pct &>/dev/null; then
    log_error "This script must be run on Proxmox VE"
fi

log_info "Checking Proxmox environment..."
log_success "Running on Proxmox VE"

# Obtenir le prochain CTID disponible (LXC ou VM)
log_info "Finding next available Container ID..."
CTID=100
while pct status $CTID 2>/dev/null || qm status $CTID 2>/dev/null; do
    CTID=$((CTID + 1))
done
log_success "Using Container ID: $CTID"

# Vérifier les ressources
log_info "Checking resources..."
pvesh get /storage/$STORAGE &>/dev/null || log_error "Storage '$STORAGE' not found"
ip link show $VMBRIDGE &>/dev/null || log_error "Bridge '$VMBRIDGE' not found"
log_success "Resources available"

# Résumé
echo ""
echo "=========================================="
echo "  Configuration"
echo "=========================================="
echo "  Container ID: $CTID"
echo "  Hostname: $HOSTNAME"
echo "  CPU Cores: $CORES"
echo "  Memory: ${MEMORY}MB"
echo "  Disk: ${DISK}GB"
echo "  Storage: $STORAGE"
echo "  Bridge: $VMBRIDGE"
echo "  IP: DHCP"
echo "=========================================="
echo ""

read -p "Continue? (y/n): " -n1
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_error "Cancelled"
fi

# Créer le LXC
log_info "Creating LXC container $CTID..."
#pct create $CTID ubuntu-24.04-standard_24.04-1_amd64.tar.zst \
pveam update
pveam download local ubuntu-24.04-standard_24.04-1_amd64.tar.zst
pct create $CTID local:vztmpl/ubuntu-24.04-standard_24.04-1_amd64.tar.zst
    --arch amd64 --cores $CORES --memory $MEMORY --swap 0 \
    --storage $STORAGE --rootfs $STORAGE:$DISK \
    --hostname $HOSTNAME --net0 name=eth0,bridge=$VMBRIDGE,type=veth \
    --unprivileged 1 --onboot 1 --start 1
log_success "LXC created"

# Attendre le démarrage
log_info "Waiting for container..."
for i in {1..30}; do
    if pct exec $CTID -- test -f /etc/os-release 2>/dev/null; then
        log_success "Container ready"
        break
    fi
    sleep 1
done

# Installer MediaManager
log_info "Installing MediaManager..."
pct exec $CTID -- bash << 'EOF'
set -e
export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get upgrade -y
apt-get install -y python3.12 python3.12-venv python3-pip postgresql postgresql-contrib git cifs-utils ffmpeg mediainfo curl wget nano sudo

useradd -m -s /bin/bash mediamanager 2>/dev/null || true
usermod -aG sudo mediamanager 2>/dev/null || true
echo "mediamanager ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers 2>/dev/null || true

mkdir -p /home/mediamanager/{app,"MediaManagerMnt/{series,films,animes,documentaires}",logs}
chown -R mediamanager:mediamanager /home/mediamanager

systemctl start postgresql
systemctl enable postgresql
sleep 2

sudo -u postgres psql -c "CREATE USER mediamanager WITH PASSWORD 'mediamanager';" 2>/dev/null || true
sudo -u postgres psql -c "ALTER USER mediamanager CREATEDB;" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE mediamanager_db OWNER mediamanager;" 2>/dev/null || true

cd /home/mediamanager/app
git clone -b main https://github.com/higs76/mediamanager2026.git . || git pull origin main

python3.12 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

cp .env.example .env
sed -i 's/changeme/mediamanager/g' .env

sudo -u postgres psql -U mediamanager -d mediamanager_db -f database/schema.sql 2>/dev/null || true

cat > /etc/systemd/system/mediamanager-watcher.service << 'SYSCTL'
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
EOF

log_success "Installation complete!"

echo ""
echo "=========================================="
echo -e "${GREEN}  Done!${NC}"
echo "=========================================="
echo ""
echo "Container: $CTID ($HOSTNAME)"
echo ""
echo "Get the IP: pct exec $CTID -- hostname -I"
echo "Then visit: http://<ip>:8000/admin/"
echo ""