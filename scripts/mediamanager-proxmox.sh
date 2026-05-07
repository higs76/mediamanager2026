#!/usr/bin/env bash

# MediaManager 2026 - Proxmox LXC Installer (Simple Version)
# 
# Usage: bash <(curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/raw/main/scripts/mediamanager-proxmox.sh)

set -e

# --- 1. RÉCUPÉRATION DES VARIABLES (Paramètres ou Défaut) ---
# La syntaxe ${var:-defaut} permet d'utiliser la variable fournie 
# par l'utilisateur, ou une valeur de secours si c'est vide.
APP="Media manager"
CTID=${var_ctid:-"auto"}
HOSTNAME=$(echo "${var_hostname:-mediamanager}" | tr ' ' '-')
STORAGE=${var_container_storage:-"local-lvm"}
TEMPLATE_STORAGE=${var_template_storage:-"local"}
MEMORY=${var_ram:-"4096"}
VCPU=${var_cpu:-"2"}
DISK_SIZE=${var_disk:-"20"}
BRG=${var_brg:-"vmbr0"}
NET=${var_net:-"dhcp"}

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



#check container ID

if [ "$CTID" = "auto" ]; then
    log_info "Finding next available Container ID..."
    CTID=$(pvesh get /cluster/nextid)    
else
    # On entre dans la boucle si l'utilisateur a saisi un ID manuellement
    log_info "Verifying Container ID..."
    while true; do
        if [[ "$CTID" =~ ^[0-9]+$ ]]; then
            # Vérification globale (VM + CT)            
            if pvesh get /cluster/resources --output-format text 2>/dev/null | awk '{print $2}' | grep -qw "$CTID"; then
                echo "Erreur : L'ID $CTID est déjà utilisé."
            else
                break # L'ID est libre !
            fi
        else
            echo "Erreur : '$CTID' n'est pas un nombre valide."
        fi
        
        read -p "Veuillez saisir un autre ID (ou 'auto') : " CTID        
        if [ "$CTID" = "auto" ]; then
            CTID=$(pvesh get /cluster/nextid)
            break
        fi
    done
fi
log_success "Using Container ID: $CTID"

# Vérifier les ressources
log_info "Checking resources..."

# --- Fonction de vérification simplifiée ---
check_storage_capability() {
    local store=$1
    local cap=$2
    # On demande le format 'text' mais sans les bordures de tableau si possible, 
    # ou on nettoie la sortie avec grep.
    pvesh get /storage/$store --output-format text 2>/dev/null | grep -w "content" | grep -q "$cap"
}

# --- Vérification du stockage des CONTENEURS ---
# --- Vérification du stockage Container ---
log_info "Vérification du stockage de destination ($STORAGE)..."
if check_storage_capability "$STORAGE" "rootdir"; then
    log_success "Destination validée."
else
    log_error "Le stockage '$STORAGE' est introuvable ou n'accepte pas les containers (rootdir)."
    exit 1
fi

# --- Vérification du stockage Source ---
log_info "Vérification du stockage source (Images/Modèles) ($TEMPLATE_STORAGE)..."
if check_storage_capability "$TEMPLATE_STORAGE" "vztmpl"; then
    log_success "Source validée."
else
    log_error "Le stockage '$TEMPLATE_STORAGE' est introuvable ou n'accepte pas les templates (vztmpl)."
    exit 1
fi

# On nettoie le hostname au cas où (remplace les espaces par des tirets)


ip link show $BRG &>/dev/null || log_error "Bridge '$BRG' not found"
log_success "Resources available"

# On prépare le texte pour l'IP
if [ -z "$NET" ] || [ "$NET" = "dhcp" ]; then
    DISPLAY_IP="DHCP"
else
    DISPLAY_IP="$IP"
fi

# Résumé
echo ""
echo "=========================================="
echo "  Configuration"
echo "=========================================="
echo "  Container ID: $CTID"
echo "  Hostname: $HOSTNAME"
echo "  CPU Cores: $VCPU"
echo "  Memory: ${MEMORY}MB"
echo "  Storage Template: $TEMPLATE_STORAGE"
echo "  Storage Container: $STORAGE"
echo "  Storage Container Disk: ${DISK_SIZE}GB"
echo "  Bridge: $BRG"
echo "  IP: $DISPLAY_IP"
echo "=========================================="
echo ""

echo "========================================================="
echo "FIN DU TEST DE VALIDATION"
exit 0  # Arrête le script ici avec succès

read -p "Continue? (y/n): " -n1
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_error "Cancelled"
fi

# Créer le LXC
# 1. Récupérer dynamiquement le nom du dernier template Ubuntu 24.04 disponible
log_info "Updating Proxmox templates..."
pveam update >/dev/null
TEMPLATE=$(pveam available -section system | grep "ubuntu-24.04-standard" | head -n1 | awk '{print $2}')

# 2. Télécharger ce template spécifique
log_info "Downloading template: $TEMPLATE"
pveam download local $TEMPLATE

log_info "Creating LXC container $CTID..."

pct create $CTID local:vztmpl/$TEMPLATE
    --arch amd64 --cores $CORES --memory $MEMORY --swap 0 \
    --storage $STORAGE --rootfs $STORAGE:$DISK \
    --hostname $HOSTNAME --net0 name=eth0,bridge=$VMBRIDGE,type=veth \
    --ostype ubuntu --description "MediaManager 2026" \
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
