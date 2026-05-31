# ==============================================================================
# MediaManager 2026 - Deploy to LXC
# Synchronise les fichiers depuis Windows vers le LXC Proxmox.
#
# CONFIGURATION (une seule fois) :
#   1. Generer une cle SSH :
#      ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\mediamanager_lxc"
#
#   2. Creer ~/.ssh/config sur Windows :
#      Host mm-lxc
#          HostName 192.168.1.XXX
#          User mediamanager
#          IdentityFile ~/.ssh\mediamanager_lxc
#          StrictHostKeyChecking no
#      (Si l'IP change, modifier seulement HostName dans ce fichier)
#
#   3. Lors de la (re)installation du LXC, fournir la cle publique :
#      $key = Get-Content "$env:USERPROFILE\.ssh\mediamanager_lxc.pub"
#      SSH_PUBLIC_KEY="$key" bash proxmox-install.sh
#      (La cle sera automatiquement installee dans le LXC)
#
# Usage VSCode : Ctrl+Shift+P > "Run Task" > "Deployer sur LXC"
# Usage direct : powershell -File deploy-to-lxc.ps1
# ==============================================================================

param(
    [string]$SshHost = "mm-lxc",  # Correspond au "Host" dans ~/.ssh/config
    [switch]$Restart = $false
)

$RemotePath  = "/home/mediamanager/app"
$ProjectRoot = Split-Path $PSScriptRoot -Parent

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Deploy MediaManager --> $SshHost" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# -- Verifier que ~/.ssh/config existe et contient mm-lxc ---------------------
$SshConfig = "$env:USERPROFILE\.ssh\config"
if (-not (Test-Path $SshConfig)) {
    Write-Host ""
    Write-Host "[WARN] ~/.ssh/config non trouve. Creer le fichier avec :" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Host mm-lxc" -ForegroundColor Gray
    Write-Host "      HostName 192.168.1.XXX" -ForegroundColor Gray
    Write-Host "      User mediamanager" -ForegroundColor Gray
    Write-Host "      IdentityFile ~/.ssh\mediamanager_lxc" -ForegroundColor Gray
    Write-Host "      StrictHostKeyChecking no" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Remplacer XXX par les derniers chiffres de l'IP du LXC." -ForegroundColor Gray
    exit 1
}

# -- Test de connexion ---------------------------------------------------------
Write-Host ""
Write-Host "Test de connexion SSH ($SshHost)..." -ForegroundColor Gray
$testResult = & ssh -o BatchMode=yes -o ConnectTimeout=8 "$SshHost" "echo OK" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERR] Connexion SSH impossible vers $SshHost" -ForegroundColor Red
    Write-Host "  Details : $testResult" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Verifier dans ~/.ssh/config :" -ForegroundColor Gray
    Write-Host "    - HostName correct (IP du LXC actuelle) ?" -ForegroundColor Gray
    Write-Host "    - Cle SSH installee sur le LXC ?" -ForegroundColor Gray
    Write-Host "    - Service SSH actif sur le LXC ?" -ForegroundColor Gray
    exit 1
}
Write-Host "[OK] Connexion SSH etablie" -ForegroundColor Green

# -- Fichiers a synchroniser ---------------------------------------------------
$Items = @(
    "watcher",
    "frontend",
    "database\schema.sql",
    "scripts\proxmox-install.sh",
    "scripts\mediamanager-proxmox.sh",
    "scripts\mediamanager-watcher.service",
    "requirements.txt",
    "VERSION",
    "run.py",
    ".env.example"
)

Write-Host ""
Write-Host "Synchronisation des fichiers..." -ForegroundColor Yellow

$allOk = $true

foreach ($item in $Items) {
    $localPath    = Join-Path $ProjectRoot $item
    $remoteSuffix = $item -replace '\\', '/'

    if (-not (Test-Path $localPath)) {
        Write-Host "  [SKIP] $item" -ForegroundColor DarkGray
        continue
    }

    if (Test-Path $localPath -PathType Container) {
        Write-Host "  [DIR]  $item/" -ForegroundColor Gray
        & scp -r -q "$localPath" "${SshHost}:${RemotePath}/"
    } else {
        $parentDir = (Split-Path $remoteSuffix -Parent) -replace '\\', '/'
        if ($parentDir -and $parentDir -ne ".") {
            & ssh "$SshHost" "mkdir -p $RemotePath/$parentDir" 2>$null
        }
        Write-Host "  [FILE] $item" -ForegroundColor Gray
        & scp -q "$localPath" "${SshHost}:${RemotePath}/${remoteSuffix}"
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Host "  [ERR]  Echec sur $item" -ForegroundColor Red
        $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host ""
    Write-Host "[ERREUR] Des fichiers n'ont pas pu etre envoyes." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[OK] Fichiers synchronises" -ForegroundColor Green

# -- Redemarrage du service ----------------------------------------------------
if ($Restart) {
    Write-Host ""
    Write-Host "Redemarrage du service..." -ForegroundColor Yellow
    & ssh "$SshHost" "sudo systemctl restart mediamanager-watcher"

    if ($LASTEXITCODE -eq 0) {
        # Recuperer l'IP reelle depuis ssh config pour afficher l'URL
        $IP = (& ssh "$SshHost" "hostname -I | awk '{print $1}'" 2>$null).Trim()
        Write-Host "[OK] Service redemarre" -ForegroundColor Green
        if ($IP) {
            Write-Host ""
            Write-Host "Admin : http://${IP}:8000/admin/" -ForegroundColor Cyan
        }
    } else {
        Write-Host "[ERR] Echec du redemarrage" -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host ""
    Write-Host "[INFO] Pour redemarrer le service :" -ForegroundColor DarkYellow
    Write-Host "  - Tache VSCode    : 'Deployer + Restart'" -ForegroundColor Gray
    Write-Host "  - Interface admin : bouton Restart dans le Dashboard" -ForegroundColor Gray
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Termine !" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan