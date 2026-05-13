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
echo "  CPU Cores: $VCPU"
echo "  Memory: ${MEMORY}MB"
echo "  Storage Template: $TEMPLATE_STORAGE"
echo "  Storage Container: $STORAGE"
echo "  Storage Container Disk: ${DISK_SIZE}GB"
echo "  Bridge: $BRG"
echo "  IP: $DISPLAY_IP"
echo "=========================================="
echo ""

read -p "Continue? (y/n): " -n1
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log_error "Cancelled"
fi

# 1. Récupérer dynamiquement le nom du dernier template Ubuntu 24.04 disponible
log_info "Updating Proxmox templates..."
pveam update >/dev/null
TEMPLATE=$(pveam available -section system | grep "ubuntu-24.04-standard" | head -n1 | awk '{print $2}')

if [ -z "$TEMPLATE" ]; then
    log_error "No Ubuntu 24.04 template found in Proxmox repository"
    exit 1
fi
log_success "Found template: $TEMPLATE"
 
# 2. Télécharger uniquement si pas déjà présent
if pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
    log_success "Template already downloaded, skipping"
else
    log_info "Downloading template: $TEMPLATE"
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

# Créer le LXC
log_info "Creating LXC container $CTID..."

pct create $CTID "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
  --hostname "$HOSTNAME" \
  --cores "$VCPU" \
  --memory "$MEMORY" \
  --net0 "name=eth0,bridge=${BRG},ip=${NET}" \
  --rootfs "${STORAGE}:${DISK_SIZE}" \
  --unprivileged 1 \
  --features nesting=1 \
  --onboot 1 \
  --start 1 \
  --ostype ubuntu

log_success "LXC created"

# Attendre le démarrage
log_info "Waiting for container..."
READY=0

for i in {1..30}; do
    if pct exec "$CTID" -- test -S /run/dbus/system_bus_socket >/dev/null 2>&1; then
        READY=1
        break
    fi

    sleep 2
done

if [ "$READY" -ne 1 ]; then
    log_error "Container failed to start correctly"
    pct status "$CTID"
    exit 1
fi

# Installer MediaManager en appelant proxmox-install.sh depuis le repo
# Pas de duplication : toute la logique d'installation est dans ce seul fichier.
# Si proxmox-install.sh est corrigé, le fix s'applique automatiquement ici.
log_info "Installing MediaManager inside container $CTID..."
pct exec $CTID -- bash -c \
    "curl -fsSL https://raw.githubusercontent.com/higs76/mediamanager2026/main/scripts/proxmox-install.sh | bash"
 
log_success "Installation complete!"

CT_IP=""

for i in {1..30}; do
    CT_IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}')

    if [ -n "$CT_IP" ]; then
        break
    fi
    sleep 2
done


echo ""
echo "=========================================="
echo -e "${GREEN}  Done!${NC}"
echo "=========================================="
echo ""
echo "Container: $CTID ($HOSTNAME)"
echo ""
echo "Get the IP: pct exec $CTID -- hostname -I"
if [ -n "$CT_IP" ]; then
    echo "Access: http://$CT_IP:8000/admin/"
else
    echo "Access: http://<container-ip>:8000/admin/ (IP not detected, check with 'pct exec $CTID -- hostname -I')"
fi
echo ""
