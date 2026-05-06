# MediaManager Watcher - Dockerfile
# Build: docker build -t mediamanager:latest .
# Run: docker run -d -p 8000:8000 mediamanager:latest

FROM ubuntu:24.04

# Éviter les prompts interactifs
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Métadonnées
LABEL maintainer="MediaManager"
LABEL description="MediaManager - Watcher Service"

# ==========================================
# Installation des dépendances système
# ==========================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
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
    sudo \
    && rm -rf /var/lib/apt/lists/*

# ==========================================
# Créer l'utilisateur mediamanager
# ==========================================
RUN useradd -m -s /bin/bash mediamanager && \
    usermod -aG sudo mediamanager && \
    echo "mediamanager ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers

# ==========================================
# Créer la structure de répertoires
# ==========================================
RUN mkdir -p /home/mediamanager/app && \
    mkdir -p /home/mediamanager/MediaManagerMnt/{series,films,animes,documentaires} && \
    mkdir -p /home/mediamanager/logs && \
    mkdir -p /home/mediamanager/data && \
    chown -R mediamanager:mediamanager /home/mediamanager

# ==========================================
# Cloner le repo et configurer l'app
# ==========================================
WORKDIR /home/mediamanager/app

# Clone du repo (à adapter avec votre URL)
RUN git clone https://github.com/higs76/mediamanager2026.git . && \
    chown -R mediamanager:mediamanager /home/mediamanager/app

# ==========================================
# Créer l'environnement Python
# ==========================================
RUN python3.12 -m venv /home/mediamanager/app/venv && \
    /home/mediamanager/app/venv/bin/pip install --upgrade pip && \
    /home/mediamanager/app/venv/bin/pip install -r requirements.txt

# ==========================================
# Configurer PostgreSQL
# ==========================================
RUN service postgresql start && \
    sudo -u postgres psql -c "CREATE USER mediamanager WITH PASSWORD 'mediamanager';" || true && \
    sudo -u postgres psql -c "ALTER USER mediamanager CREATEDB;" || true && \
    sudo -u postgres psql -c "CREATE DATABASE mediamanager_db OWNER mediamanager;" || true && \
    service postgresql stop

# ==========================================
# Créer le fichier .env
# ==========================================
RUN cp .env.example .env && \
    sed -i 's/changeme/mediamanager/g' .env && \
    chown mediamanager:mediamanager .env

# ==========================================
# Initialiser la BD (tables)
# ==========================================
RUN service postgresql start && \
    sleep 2 && \
    /home/mediamanager/app/venv/bin/python -c "from watcher.database import engine; engine.dispose()" 2>/dev/null || true && \
    sudo -u postgres psql -U mediamanager -d mediamanager_db -f database/schema.sql 2>/dev/null || true && \
    service postgresql stop

# ==========================================
# Créer le systemd service
# ==========================================
RUN cat > /etc/systemd/system/mediamanager-watcher.service << 'EOF'
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
EOF

# ==========================================
# Permissions finales
# ==========================================
RUN chown -R mediamanager:mediamanager /home/mediamanager && \
    chmod 755 /home/mediamanager

# ==========================================
# Ports
# ==========================================
EXPOSE 8000

# ==========================================
# Healthcheck
# ==========================================
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# ==========================================
# Point d'entrée
# ==========================================
COPY docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["start"]