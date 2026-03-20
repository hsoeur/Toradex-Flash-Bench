# FlashBench — Déploiement Docker

## Table des matières

- [Vue d'ensemble](#vue-densemble)
- [Architecture](#architecture)
- [Prérequis](#prérequis)
- [Arborescence des fichiers Docker](#arborescence-des-fichiers-docker)
- [Procédure de déploiement](#procédure-de-déploiement)
- [Commandes utiles](#commandes-utiles)
- [Configuration](#configuration)
- [Ports réseau](#ports-réseau)
- [Dépannage](#dépannage)

---

## Vue d'ensemble

FlashBench est une application de flashage et monitoring de cartes Toradex, composée de :

- **Frontend** — Application React (Vite + TypeScript) servie par Nginx **→ dans Docker**
- **Backend** — Serveur Python Flask-SocketIO **→ directement sur l'hôte**

**Pourquoi le backend ne tourne pas dans Docker ?**
Le backend a besoin d'un accès direct aux ressources système de l'hôte :
- `systemctl` / `journalctl` pour surveiller dnsmasq et nginx
- `tail` pour lire les logs Nginx en temps réel
- Exécution de scripts shell (`recovery-linux.sh`, `wrapup.sh`)
- Communication réseau directe avec les cartes Toradex sur le LAN

Seul le frontend est conteneurisé : Nginx sert le build React et agit comme reverse proxy vers le backend hôte.

---

## Architecture

```
                   ┌─────── port 8080 ───────┐
                   │                          │
              ┌────▼──────────────────────────┴───┐
              │  frontend (Docker — Nginx)         │
              │                                    │
              │  /              → React SPA         │
              │  /api/*         → hôte:5001        │
              │  /socket.io/*   → hôte:5001 WS     │
              │  /vnc/*         → hôte:6080 WS     │
              └────┬───────────────────────────────┘
                   │ host.docker.internal
   ┌───────────────▼──────────────────────────────────────┐
   │  backend (natif sur l'hôte — python main.py)          │
   │                                                       │
   │  Flask-SocketIO  ─── port 5001 (API + WebSocket)     │
   │  Serial TCP      ─── port 5000 (cartes LAN)          │
   │  VNC Proxy       ─── port 6080 (websockify)           │
   │                                                       │
   │  Accès système :                                      │
   │    systemctl / journalctl    (dnsmasq, nginx)         │
   │    tail /var/log/nginx       (progression flash)      │
   │    bash recovery-linux.sh    (Toradex Easy Installer) │
   │    scripts/*.sh, wrapup.sh   (post-flash)             │
   └───────────────────────────────────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │  Réseau LAN        │
         │  Cartes Toradex    │
         │  (TCP + VNC 5900)  │
         └────────────────────┘
```

---

## Prérequis

| Composant       | Version minimum | Vérification              |
|-----------------|-----------------|---------------------------|
| Docker          | 20.10+          | `docker --version`        |
| Docker Compose  | 2.0+ (plugin)   | `docker compose version`  |
| Python          | 3.10+           | `python3 --version`       |
| pip             | -               | `pip --version`           |
| Nginx (hôte)    | -               | `systemctl status nginx`  |
| dnsmasq (hôte)  | -               | `systemctl status dnsmasq`|

---

## Arborescence des fichiers Docker

```
Toradex-Flash-Bench/
├── Dockerfile              ← Frontend (multi-stage : Node build + Nginx)
├── .dockerignore           ← Exclusions pour le build frontend
├── nginx.conf              ← Config Nginx du conteneur (reverse proxy)
├── docker-compose.yml      ← Orchestration du frontend uniquement
├── .env.development        ← Variables Vite pour le dev local
│
├── backend/                ← Tourne directement sur l'hôte (pas dans Docker)
│   ├── main.py
│   ├── config.py
│   ├── requirements.txt
│   └── ...
│
└── logs/                   ← Logs applicatifs
```

---

## Procédure de déploiement

### Étape 1 — Cloner le dépôt

```bash
git clone <url-du-repo> /opt/flashbench
cd /opt/flashbench
```

### Étape 2 — Vérifier les prérequis

```bash
# Docker
docker --version
docker compose version

# Python
python3 --version

# Services hôte (doivent tourner)
systemctl status nginx
systemctl status dnsmasq
```

### Étape 3 — Installer et lancer le backend (sur l'hôte)

```bash
# Créer l'environnement virtuel Python
cd backend
python3 -m venv .venv
source .venv/bin/activate

# Installer les dépendances
pip install -r requirements.txt

# Vérifier la configuration
nano config.py
```

Points de configuration clés dans `backend/config.py` :
- `EXTERNAL_API_URL` — URL de l'API de traçabilité externe
- `RECOVERY_SCRIPT_DIR` — Chemin vers Toradex Easy Installer
- `IMAGE_ROOT` — Répertoire des images Tezi (par défaut `/var/www/html`)

Lancer le backend :

```bash
# Option A — en premier plan
python main.py

# Option B — en service systemd (recommandé en production)
sudo cp flashbench.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now flashbench
```

### Étape 4 — Builder et lancer le frontend (Docker)

```bash
cd /opt/flashbench
mkdir -p logs
docker compose up -d --build
```

### Étape 5 — Vérifier le déploiement

```bash
# Vérifier le conteneur frontend
docker compose ps

# Vérifier le backend
curl http://localhost:5001/api/status

# Tester le frontend
curl -I http://localhost:8080
```

### Étape 6 — Accéder à l'application

Ouvrir un navigateur à l'adresse :

```
http://<ip-du-serveur>:8080
```

---

## Commandes utiles

### Frontend (Docker)

| Action                          | Commande                                 |
|---------------------------------|------------------------------------------|
| Démarrer le frontend            | `docker compose up -d`                   |
| Démarrer avec rebuild           | `docker compose up -d --build`           |
| Arrêter le frontend             | `docker compose down`                    |
| Voir les logs Nginx             | `docker compose logs -f`                 |
| Reconstruire l'image            | `docker compose build --no-cache`        |
| État du conteneur               | `docker compose ps`                      |
| Ouvrir un shell dans Nginx      | `docker compose exec frontend sh`        |
| Supprimer image et volumes      | `docker compose down --rmi all -v`       |

### Backend (hôte natif)

| Action                          | Commande                                        |
|---------------------------------|-------------------------------------------------|
| Lancer en premier plan          | `cd backend && .venv/bin/python main.py`        |
| Lancer via systemd              | `sudo systemctl start flashbench`               |
| Arrêter via systemd             | `sudo systemctl stop flashbench`                |
| Voir les logs backend           | `journalctl -u flashbench -f`                   |
| Vérifier le statut              | `sudo systemctl status flashbench`              |

---

## Configuration

### Variables d'environnement

| Variable           | Cible    | Description                           | Défaut                     |
|--------------------|----------|---------------------------------------|----------------------------|
| `VITE_BACKEND_URL` | frontend | URL du backend (build time Vite)      | `""` (= même origine)     |

> En production (Docker), `VITE_BACKEND_URL` reste vide : Nginx proxifie `/api/` et `/socket.io/` vers le backend hôte. En développement, `.env.development` le définit à `http://localhost:5001`.

### Changer le port d'accès du frontend

Modifier `docker-compose.yml` :

```yaml
frontend:
  ports:
    - "3000:80"   # ← remplacer 8080 par le port souhaité
```

---

## Ports réseau

| Port | Composant   | Protocole     | Description                          |
|------|-------------|---------------|--------------------------------------|
| 8080 | frontend    | HTTP          | Interface web (Nginx dans Docker)    |
| 5001 | backend     | HTTP/WS       | API REST + Socket.IO (hôte)          |
| 5000 | backend     | TCP           | Listener série cartes → backend      |
| 6080 | backend     | WebSocket     | Proxy VNC websockify (hôte)          |

---

## Dépannage

### Le frontend ne se connecte pas au backend

1. Vérifier que le backend tourne sur l'hôte :
   ```bash
   curl http://localhost:5001/api/status
   ss -tlnp | grep 5001
   ```
2. Vérifier que `host.docker.internal` est résolu dans le conteneur :
   ```bash
   docker compose exec frontend ping host.docker.internal
   ```
3. Vérifier les logs Nginx du conteneur :
   ```bash
   docker compose logs -f
   ```

### Les cartes ne sont pas détectées

1. Le backend tourne sur l'hôte donc il a accès direct au LAN
2. Vérifier que le port 5000 écoute : `ss -tlnp | grep 5000`
3. Tester la connectivité : `ping <ip-carte>` depuis l'hôte

### Erreur de build Docker (frontend)

```bash
# Nettoyer le cache et reconstruire
docker compose build --no-cache

# Vérifier l'espace disque
df -h
docker system prune -a
```

### Le backend ne démarre pas

1. Vérifier les dépendances Python :
   ```bash
   cd backend && source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Vérifier les logs :
   ```bash
   python main.py   # lire la sortie d'erreur
   # ou
   journalctl -u flashbench -n 50 --no-pager
   ```
3. Vérifier que les ports ne sont pas déjà utilisés :
   ```bash
   ss -tlnp | grep -E '5000|5001|6080'
   ```
