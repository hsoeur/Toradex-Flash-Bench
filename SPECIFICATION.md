# Spécification Technique Détaillée — Toradex Flash Bench

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Architecture Générale](#2-architecture-générale)
3. [Cartographie des Ports Réseau](#3-cartographie-des-ports-réseau)
4. [Frontend — React + TypeScript + Vite](#4-frontend--react--typescript--vite)
   - [Stack Technique](#41-stack-technique)
   - [Modèle de Données Frontend](#42-modèle-de-données-frontend)
   - [Flux Applicatif — 3 Écrans](#43-flux-applicatif--3-écrans)
   - [Composants Détaillés](#44-composants-détaillés)
   - [Styles CSS](#45-styles-css)
5. [Backend — Flask-SocketIO (Python)](#5-backend--flask-socketio-python)
   - [Stack Technique](#51-stack-technique)
   - [Configuration](#52-configuration)
   - [Factory & Point d'Entrée](#53-factory--point-dentrée)
   - [Logique Métier Principale](#54-logique-métier-principale)
   - [Services Supports](#55-services-supports)
   - [Infrastructure de Logging](#56-infrastructure-de-logging)
   - [API REST — Blueprints Flask](#57-api-rest--blueprints-flask)
   - [Événements Socket.IO](#58-événements-socketio)
6. [Modèles de Données — API Externe (.NET)](#6-modèles-de-données--api-externe-net)
7. [Scripts Embarqués](#7-scripts-embarqués)
8. [Infrastructure & Déploiement](#8-infrastructure--déploiement)
9. [Cycle de Vie Complet d'un Flashage](#9-cycle-de-vie-complet-dun-flashage)
10. [Patterns de Gestion d'Erreur](#10-patterns-de-gestion-derreur)

---

## 1. Vue d'ensemble

**Toradex Flash Bench** est une station industrielle de flashage et de supervision pour cartes embarquées **Toradex Verdin AM62**. L'application automatise l'installation d'images firmware via Toradex Easy Installer (Tezi), l'injection d'adresses MAC, et l'enregistrement de la traçabilité de production.

L'interface, entièrement localisée en français, permet à un opérateur de flasher simultanément jusqu'à **5 cartes**, de suivre la progression en temps réel via des flux VNC, et de gérer la traçabilité.

---

## 2. Architecture Générale

```
┌──────────────────────────────────────────────────────────────────┐
│  Navigateur (React SPA)                                         │
│  ├─ Socket.IO (WS)  ───────────► Flask-SocketIO (port 5001)    │
│  ├─ REST (HTTP)      ───────────► Flask-SocketIO (port 5001)    │
│  └─ noVNC (WS)       ───────────► websockify    (port 6080)    │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  Backend Flask-SocketIO (port 5001)                             │
│  ├─ SerialListener   ◄── TCP :5000 ── Carte Toradex            │
│  ├─ NginxMonitor     ◄── tail access.log ── Nginx              │
│  ├─ VncProxyManager  ── websockify :6080 ── Carte VNC :5900    │
│  ├─ ServicesManager  ── polling DB/dnsmasq/nginx                │
│  └─ RecoveryRunner   ── recovery-linux.sh                       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  API externe (port 10000)                                       │
│  ├─ Users, ManufacturingOrder                                   │
│  ├─ MacAddresses                                                │
│  ├─ MeasurementTraceability                                     │
│  └─ ProgrammedBoards                                            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Cartographie des Ports Réseau

| Port  | Service            | Protocole  | Rôle                                              |
|-------|--------------------|------------|---------------------------------------------------|
| 3306  | MySQL              | TCP        | Base de données de production                     |
| 5000  | SerialListener     | TCP brut   | Réception des annonces série + événements cartes  |
| 5001  | Flask-SocketIO     | HTTP/WS    | API REST + communication temps réel Socket.IO     |
| 5900  | VNC (par carte)    | TCP        | Serveur VNC Tezi sur chaque carte                 |
| 6080  | websockify         | WebSocket  | Proxy VNC (navigateur → carte)                    |
| 8080  | Docker Nginx       | HTTP       | Frontend de production (conteneur)                |
| 10000 | API externe        | HTTP       | Traçabilité, utilisateurs, adresses MAC, ProgrammedBoards |

---

## 4. Frontend — React + TypeScript + Vite

### 4.1 Stack Technique

| Technologie        | Version  | Rôle                            |
|--------------------|----------|----------------------------------|
| React              | 19.2     | Framework UI                    |
| TypeScript         | 5.9      | Typage statique                 |
| Vite               | 7.3      | Bundler + dev server            |
| socket.io-client   | 4.8      | Communication temps réel        |
| noVNC (vendor)     | —        | Client VNC embarqué             |

**Configuration Vite** (`vite.config.ts`) : plugin React, alias `novnc` → `vendor/novnc`.

**Variable d'environnement** : `VITE_BACKEND_URL` — vide en production (proxy nginx), `http://localhost:5001` en développement.

### 4.2 Modèle de Données Frontend

Défini dans `src/types/board.ts` :

| Type            | Champs                                                                 |
|-----------------|------------------------------------------------------------------------|
| `BoardStatus`   | `'waiting' \| 'flashing' \| 'done' \| 'error'`                       |
| `BoardModule`   | `serial, status, startTime, errorMessage`                     |
| `ModulesMap`    | `Record<string, BoardModule>` (clé = adresse IP)                      |
| `SlotState`     | `'empty' \| 'awaiting_card' \| 'awaiting_boot' \| 'flashing' \| 'done' \| 'error'` |
| `PositionSlot`  | `state, boardIp, boardData, scannedAt`                                |
| `NUM_POSITIONS` | `5` (constante)                                                        |

Déclarations noVNC dans `src/types/novnc.d.ts` : typage du constructeur RFB, propriétés (`viewOnly`, `scaleViewport`), méthodes (`disconnect`, `sendKey`), événements (`connect`, `disconnect`, `securityfailure`, `clipboard`).

### 4.3 Flux Applicatif — 3 Écrans

```
LoginScreen → ScanOrderScreen → FlashDashboard
```

Géré par `src/App.tsx` :

- **État** : `operatorId`, `operatorName`, `orderNumber`, `theme` (dark/light)
- **Persistance** : `sessionStorage` pour opérateur et OF, `localStorage` pour le thème
- **Transitions** : `handleSelectOperator()` → `handleConfirmOrder()` → dashboard ; `handleLogout()` retour au login

### 4.4 Composants Détaillés

#### 4.4.1 LoginScreen (`src/components/LoginScreen.tsx`) — 119 lignes

- **Source de données** : `GET http://localhost:10000/api/Users/current`
- **Interface** : `Operator = { userUid, lastName, firstName, department }`
- **Affichage** : liste d'opérateurs sous forme de boutons cliquables avec initiale, nom formaté "Prénom NOM", département
- **États** : chargement, erreur, liste vide

#### 4.4.2 ScanOrderScreen (`src/components/ScanOrderScreen.tsx`) — 182 lignes

- **Auto-focus** sur le champ de saisie pour scanner de code-barres
- **Parsing** : accepte `OF25000` ou `25000` via `parseOfInput()`
- **Validation** : `GET /api/manufacturing-order/<uid>` → vérifie que le statut est `ACTIVE`
- **Navigation** : bouton retour vers l'écran opérateur

#### 4.4.3 FlashDashboard (`src/components/FlashDashboard.tsx`) — 355 lignes

Composant principal — orchestre tout le workflow de flashage.

**Props** : `operatorId`, `operatorName`, `orderNumber`, `onLogout`, `theme`, `onToggleTheme`

**État interne** :

| Variable           | Type                                | Rôle                                         |
|--------------------|-------------------------------------|----------------------------------------------|
| `connectionStatus` | `connecting/connected/disconnected` | État Socket.IO                               |
| `slots`            | `PositionSlot[5]`                   | Les 5 positions physiques                    |
| `pendingQueue`     | `number[]`                          | File FIFO des slots en attente de détection  |
| `scanFeedback`     | `string`                            | Message temporaire pour l'opérateur          |
| `consoleOpen`      | `boolean`                           | Panneau console ouvert/fermé                 |
| `servicesOpen`     | `boolean`                           | Panneau services ouvert/fermé                |
| `traceOpen`        | `boolean`                           | Panneau traçabilité ouvert/fermé             |
| `imageSelectorOpen`| `boolean`                           | Panneau sélection image ouvert/fermé         |
| `servicesStatus`   | `ServicesStatus`                    | État des services systèmes                   |
| `monitorStatus`    | `MonitorStatus`                     | État du SerialListener                       |
| `vncWsPort`        | `number`                            | Port websockify (défaut 6080)                |

**Connexion Socket.IO** (au montage) :

- Transport : `['websocket', 'polling']`
- Événement `connect` → émet `set_session_context` avec opérateur + OF
- Écoute : `services_status`, `monitor_status`, `vnc_config`, `modules_update`

**Intégration scanner code-barres** :

- Listener `keydown` en phase capture sur `window`
- Accumulation dans `scanBufferRef`, reset automatique après 500ms d'inactivité
- Sur `Enter` : traitement du buffer comme scan (regex `POS[1-5]`) ou confirmation d'insertion (Enter seul)
- `blur()` sur l'élément focalisé pour éviter les clics accidentels

**Workflow de scan** :

1. Scan `POS1`-`POS5` → slot passe en `awaiting_card`
2. Insertion carte + Enter → slot passe en `awaiting_boot`, ajout à `pendingQueue`
3. Carte détectée via `modules_update` → matching FIFO → slot passe en `flashing`
4. Événements backend → mise à jour `flashing`/`done`/`error`
5. Re-scan d'un slot `done`/`error` → reset (émet `reset_board`)

**Mapping cartes→slots** (`mapModulesToSlots()`) :

- Identifie les nouvelles IPs non assignées dans le snapshot modules
- Déqueue de `pendingQueue` en ordre FIFO
- Émet `board_position_assigned` vers le backend pour journalisation

#### 4.4.4 PositionSlot (`src/components/PositionSlot.tsx`) — 131 lignes

Conteneur visuel pour une position physique parmi 5. Contenu dynamique selon `SlotState` :

| État             | Affichage                                                        |
|------------------|------------------------------------------------------------------|
| `empty`          | Placeholder "Scannez POS{n}"                                    |
| `awaiting_card`  | Icône animée d'insertion + "Insérez la carte"                   |
| `awaiting_boot`  | Icône alimentation + "Lancez manuellement l'alimentation"       |
| `flashing`       | VncViewer (ou spinner si `waiting`)                             |
| `done`           | Overlay vert ✓ + indice de re-scan                              |
| `error`          | Overlay rouge ✗ + message d'erreur + indice de re-scan          |

#### 4.4.5 BoardCard (`src/components/BoardCard.tsx`)

Affiche les informations d'une carte individuelle : numéro de série, IP, heure de début, temps écoulé, statut.

#### 4.4.6 VncViewer (`src/components/VncViewer.tsx`) — 286 lignes

**Connexion** : `ws://{hostname}:{wsPort}/?token={ip}` vers websockify.

**Configuration noVNC** : `scaleViewport=true`, `viewOnly=true`, `focusOnClick=false`.

**Logique de retry** :

- Jusqu'à 30 tentatives, délai de 3s entre chaque, timeout de 10s par tentative
- Arrêt des retries quand la carte atteint `done` ou `error`

**Overlays visuels** :

- Succès : checkmark vert + "Flashage Terminé"
- Erreur : croix rouge + "Erreur de Programmation" avec détail

**Compteur** : temps écoulé affiché en continu depuis `startTime`.

#### 4.4.7 ConsolePanel (`src/components/ConsolePanel.tsx`) — 156 lignes

Panneau glissant depuis le bas. Écoute les événements Socket.IO `log_history` et `log_line`.

**Fonctionnalités** :

- Filtre texte
- Défilement automatique (toggle)
- Nettoyage
- Compteur de lignes
- Maximum 500 lignes en mémoire
- Chaque entrée affiche timestamp, niveau (coloré), message

#### 4.4.8 ImageSelectorPanel (`src/components/ImageSelectorPanel.tsx`) — 176 lignes

Panneau glissant depuis la droite. Récupère la liste d'images via `GET /api/images`. Écoute `images_update` Socket.IO.

**Type `TeziImage`** : `path, folder, name, description, version, release_date, autoinstall`

Chaque image affiche : nom, dossier, version, date de release, description, statut autoinstall. Sélection par radio button → `POST /api/images/autoinstall` avec `{ path }`.

#### 4.4.9 ServicesPanel (`src/components/ServicesPanel.tsx`) — 363 lignes

Panneau glissant depuis la droite avec 4 onglets : **DHCP**, **NGINX**, **Base de données**, **Récupération**.

**Événements Socket.IO écoutés** :

- `service_log_history` : historique initial par source
- `service_log` : entrées de log en temps réel avec champ `source`
- `recovery_status` : état du script de récupération
- `recovery_log` : lignes de sortie du script de récupération

**Onglet Récupération** : boutons Start/Stop appelant `POST /api/recovery/start` et `POST /api/recovery/stop`.

**Sous-composant** `ServiceLogPane` : visualiseur de logs filtré réutilisable par onglet.

#### 4.4.10 TraceabilityPanel (`src/components/TraceabilityPanel.tsx`) — 195 lignes

Panneau glissant depuis la droite. Récupère les données depuis `GET http://localhost:8000/programmed-boards/today` (le service FastAPI).

**Colonnes affichées** : Heure, Numéro de série, Produit, OF, Opérateur, MAC Client, Statut.

**Filtrage** : par n'importe quel champ affiché.

**Type `ProgrammedBoard`** :

```typescript
{
  Id: number
  SerialNumber: string
  ProductId: string
  BoardRevision: string
  FactoryMac: string
  ClientMac: string
  ProductionOrder: string
  OperatorId: string
  ImageFolder: string
  IpBeforeReboot: string
  ProgrammingStatus: string
  ProgrammedAt: string
}
```

### 4.5 Styles CSS

`src/App.css` — 2738 lignes, avec support complet dark/light via CSS custom properties et attribut `[data-theme]` sur `<html>`.

Inclut :

- Layout dashboard (header sticky, grille, panneaux)
- Cartes avec bordure colorée par statut
- Système de slots avec animations par état
- Panneau console (slide-in bas)
- Panneaux services/images/traçabilité (slide-in droite)
- Écrans login et scan
- Viewer VNC avec overlays done/error
- Grille responsive
- Animations (pulse, blink, spin)
- Bouton toggle de thème

---

## 5. Backend — Flask-SocketIO (Python)

### 5.1 Stack Technique

| Dépendance       | Version   | Rôle                                       |
|-------------------|-----------|--------------------------------------------|
| Flask             | ≥3.0      | Framework web                              |
| Flask-SocketIO    | ≥5.3      | Communication temps réel                   |
| Flask-CORS        | ≥4.0      | Cross-origin requests                      |
| python-socketio   | ≥5.10     | Moteur Socket.IO                           |
| websockify        | ≥0.11     | Proxy VNC WebSocket                        |
| requests          | ≥2.31     | Client HTTP pour API externe               |

**Mode async** : `threading` (pas d'eventlet/gevent).

### 5.2 Configuration

Fichier : `backend/config.py`

| Paramètre               | Valeur                     | Description                               |
|--------------------------|----------------------------|-------------------------------------------|
| `FLASK_HOST`             | `0.0.0.0`                  | Adresse d'écoute                          |
| `FLASK_PORT`             | `5001`                     | Port HTTP+WS                              |
| `SECRET_KEY`             | `flashbench-secret`        | Clé de session Flask                      |
| `SERIAL_TCP_HOST/PORT`   | `0.0.0.0:5000`             | Écoute TCP annonces cartes                |
| `EXTERNAL_API_URL`       | `http://192.168.10.1:10000`| URL API externe de traçabilité            |
| `PRODUCT_UID`            | `04IN00145`                | Identifiant produit                       |
| `MACHINE_UID`            | `MO03B`                    | Identifiant machine                       |
| `OPERATION_NUMBER`       | `30`                       | Numéro d'opération traçabilité            |
| `UNIT_UID`               | `STR`                      | Identifiant unité                         |
| `TRACE_LABEL`            | `PROG_TORADEX`             | Libellé de traçabilité                    |
| `IMAGE_ROOT`             | `/var/www/html`             | Répertoire images Tezi servies par Nginx  |
| `IMAGE_LIST_FILE`        | `/var/www/html/image_list.json` | Registre des images disponibles       |
| `LOG_DIR`                | `../logs`                  | Répertoire des logs applicatifs           |
| `LOG_RETENTION_DAYS`     | `30`                       | Rétention des fichiers de log             |
| `LOG_BUFFER_MAXLEN`      | `500`                      | Taille du buffer de log en mémoire        |
| `RECOVERY_SCRIPT_DIR/PATH` | `recovery-linux.sh`      | Script de récupération Toradex            |

### 5.3 Factory & Point d'Entrée

**`backend/app_factory.py`** : crée l'application Flask + SocketIO avec CORS `*` et `async_mode="threading"`.

**`backend/main.py`** — Séquence de démarrage (221 lignes) :

1. Initialise le logging (`init_logging()`)
2. Crée l'app Flask+SocketIO (`create_app()`)
3. Branche `SocketIOLogHandler` et `ServiceLogBuffer` sur SocketIO
4. Crée `ModuleStore` — registre central d'état des cartes
5. Crée `VncProxyManager` — souscrit au ModuleStore **en premier** (écrit le fichier de tokens avant la notification frontend)
6. Souscrit `_on_modules_changed` au ModuleStore (émet `modules_update`)
7. Crée `RecoveryRunner`, `SerialListener`, `ServicesManager`
8. Enregistre les événements Socket.IO via `sio_events.register()`
9. Enregistre les blueprints REST : traceability, recovery, images, status, manufacturing_order
10. Tue les processus résiduels sur les ports 5000/6080/5001 (`fuser`)
11. Démarre tous les workers en arrière-plan
12. Lance Flask-SocketIO (bloquant, `allow_unsafe_werkzeug=True`)

**Arrêt** : handler `atexit` arrête le proxy VNC.

### 5.4 Logique Métier Principale

#### 5.4.1 ModuleStore — Registre Central (`backend/monitor.py`)

Thread-safe. Pattern Observer avec `subscribe(cb)` / `_notify()`.

**`BoardModule`** (dataclass) :

| Champ             | Type        | Description                               |
|-------------------|-------------|-------------------------------------------|
| `serial`          | `str`       | Numéro de série de la carte               |
| `status`          | `BoardStatus` | État courant                            |
| `start_time`      | `float`     | Timestamp Unix (secondes)                 |
| `error_message`   | `str`       | Message d'erreur (si applicable)          |

Méthodes : `reset()` (réinitialise pour reconnexion), `to_dict()` (sérialisation camelCase).

**Méthodes clés** :

- `register_board(ip, serial)` : enregistre ou reset une carte
- `handle_event(ip, raw_data)` : traite les événements pipe-délimités (`ERROR` → état erreur, `TRACEABILITY_OK`/`END...Rebooting` → done)
- `mark_done(ip)`, `mark_error(ip, msg)` : transitions d'état explicites
- `clear_done()`, `clear_one(ip)`, `clear_all()` : suppression
- `snapshot()` : copie sérialisable de l'état

#### 5.4.2 SerialListener — Serveur TCP (`backend/monitor.py`)

Écoute sur le port 5000. Accepte les connexions dans des threads dédiés.

**Traitement des messages** :

- Données brutes → `register_board()`
- Données avec pipe `|` → `handle_event()`

**Watchdog** : back-off exponentiel (2s → 60s cap). Suivi d'état : `starting`, `running`, `error`, `restarting`.

### 5.5 Services Supports

#### 5.5.1 ServicesManager (`backend/services.py`)

Monitoring passif (lecture seule, toutes les 10s) :

- **DB** : connexion TCP vers `127.0.0.1:3306` → états `connected`/`disconnected`/`checking`
- **dnsmasq** : `systemctl is-active dnsmasq` → états `active`/`inactive`/`unknown`
- **nginx** : `systemctl is-active nginx` → états `active`/`inactive`/`unknown`

**Streaming de logs** :

- dnsmasq : `sudo journalctl -u dnsmasq -f --no-pager -n 50`
- nginx : `sudo tail -n 50 -f /var/log/nginx/access.log`
- Redémarrage automatique après 5s en cas d'arrêt du processus

#### 5.5.2 VncProxyManager (`backend/vnc_proxy.py`)

Gère un unique processus `websockify` sur le port 6080 avec le plugin `TokenFile`.

- Fichier de tokens : `/tmp/flashbench_vnc_tokens.cfg` au format `<ip>: <ip>:5900`
- `on_modules_changed(snapshot)` : met à jour le fichier de tokens avec toutes les IPs des cartes (tous statuts)
- Redémarrage automatique de websockify en cas d'arrêt inattendu
- Souscrit au `ModuleStore` **avant** l'émetteur principal `modules_update` pour éviter les race conditions

#### 5.5.3 RecoveryRunner (`backend/recovery.py`)

Exécute `recovery-linux.sh` (Toradex Easy Installer) dans un thread d'arrière-plan. Diffuse stdout ligne par ligne via les événements Socket.IO `recovery_log`. États : `idle`/`running`/`success`/`error`.

#### 5.5.4 Session Context (`backend/session.py`)

Dictionnaire global thread-safe stockant `operatorId` et `orderNumber`. Mis à jour par l'événement Socket.IO `set_session_context`. Lu par l'endpoint de traçabilité.

#### 5.5.5 ImageService (`backend/image_service.py`)

Lit `/var/www/html/image_list.json` contenant les chemins relatifs vers les fichiers `image.json`. Chaque `image.json` contient les métadonnées d'une image Tezi.

`set_autoinstall(target_path)` : active `autoinstall=true` sur une image et `false` sur toutes les autres (écriture sur disque).

### 5.6 Infrastructure de Logging

#### 5.6.1 Initialisation (`backend/logging_setup.py`)

Crée :

- Logger racine `FlashBench` avec console (INFO+) et fichier rotatif quotidien (DEBUG+)
- Sous-logger `FlashBench.Monitor` avec fichier dédié `flash_events` quotidien
- `SocketIOLogHandler` pour push temps réel vers le frontend
- `ServiceLogBuffer` pour les panneaux de logs par service

Nommage des fichiers : `YYYY-MM-DD_<stem>.log` avec rotation à minuit.

#### 5.6.2 Handlers (`backend/log_handler.py`)

**`SocketIOLogHandler`** (sous-classe `logging.Handler`) :

- Buffer circulaire (500 entrées), émet des événements `log_line`
- `on_client_connect(sid)` : rejoue `log_history` au nouveau client

**`ServiceLogBuffer`** :

- Buffers par source (dhcp, nginx, mac_api, docker)
- Émet des événements `service_log`
- `on_client_connect(sid)` : rejoue `service_log_history`

### 5.7 API REST — Blueprints Flask

#### `GET /api/status` (`backend/routes/status.py`)

Retourne l'état combiné : snapshot des modules, état des services, état du SerialListener, port WS VNC.

#### Images (`backend/routes/images.py`)

| Endpoint              | Méthode | Description                                                    |
|-----------------------|---------|----------------------------------------------------------------|
| `/api/images`         | GET     | Liste toutes les images Tezi avec statut autoinstall           |
| `/api/images/autoinstall` | POST | Active autoinstall pour une image. Body : `{ path: string }`. Broadcast `images_update` via Socket.IO |

#### Ordre de fabrication (`backend/routes/manufacturing_order.py`)

`GET /api/manufacturing-order/<int:uid>` — Proxy de validation vers l'API externe `{EXTERNAL_API_URL}/api/ManufacturingOrder/by-manufacturing-order-uid?manufacturingOrderUid=<uid>`. Retourne les données de l'ordre ou erreurs 404/502/504.

#### Récupération (`backend/routes/recovery_routes.py`)

| Endpoint               | Méthode | Description                                      |
|-------------------------|---------|--------------------------------------------------|
| `/api/recovery/start`  | POST    | Démarre recovery-linux.sh (409 si déjà en cours) |
| `/api/recovery/stop`   | POST    | Arrête le script en cours                        |
| `/api/recovery/status`  | GET     | État courant                                     |

#### Traçabilité (`backend/routes/traceability.py`)

`POST /api/traceability/notify` — Appelé par le script embarqué après injection MAC.

**Body requis** :

| Champ          | Type   | Description                    |
|----------------|--------|--------------------------------|
| `serialNumber` | string | Numéro de série de la carte    |
| `macId`        | string | ID de la MAC attribuée         |
| `clientMac`    | string | Adresse MAC client injectée    |
| `factoryMac`   | string | Adresse MAC usine d'origine    |

**Body optionnel** : `ipBeforeReboot`, `boardRevision`, `productId`, `imageFolder`

Enrichit avec le contexte de session (opérateur/OF) et transmet à l'API externe `{EXTERNAL_API_URL}/api/MeasurementTraceability/create-with-mac` avec payload incluant :

- `productUid`, `label`, `classification`, `creationDate`
- `operationNumber`, `unitUid`, `userUid`, `machineUid`
- `manufacturingOrderUid`

En cas de succès, appelle `module_store.mark_done(board_ip)`.

### 5.8 Événements Socket.IO

#### Serveur → Client

| Événement             | Données                          | Déclencheur                          |
|-----------------------|----------------------------------|--------------------------------------|
| `modules_update`      | `ModulesMap`                     | Tout changement d'état d'une carte   |
| `services_status`     | `ServicesStatus`                 | Changement santé services, connexion |
| `monitor_status`      | `MonitorStatus`                  | Changement état SerialListener       |
| `vnc_config`          | `{ ws_port: number }`           | Connexion client                     |
| `log_history`         | `LogEntry[]`                    | Connexion client (replay)            |
| `log_line`            | `LogEntry`                      | Chaque nouveau record de log         |
| `service_log_history` | `Record<source, entries[]>`     | Connexion client (replay)            |
| `service_log`         | `ServiceLogEntry`               | Chaque nouveau log de service        |
| `recovery_status`     | `{ status: string }`            | Changement d'état récupération       |
| `recovery_log`        | `RecoveryLogEntry`              | Chaque ligne du script               |
| `images_update`       | `{ images: TeziImage[] }`       | Connexion, changement autoinstall    |

#### Client → Serveur

| Événement                  | Données                       | Rôle                                    |
|----------------------------|-------------------------------|-----------------------------------------|
| `set_session_context`      | `{ operatorId, orderNumber }` | Définir opérateur/OF pour traçabilité   |
| `reset_boards`             | `{ mode: 'done' \| 'all' }`  | Effacer les cartes terminées ou toutes  |
| `reset_board`              | `{ ip: string }`             | Effacer une carte spécifique            |
| `board_position_assigned`  | `{ ip, position }`           | Journaliser le mapping carte↔position   |

---

## 6. Modèles de Données — API Externe (.NET)

L'API externe (port 10000) est une application ASP.NET utilisant le namespace `DataLib`. Voici les entités du domaine utilisées par le système FlashBench.

### 6.1 MeasurementTraceability — Traçabilité des Mesures

Enregistre chaque action de programmation comme une mesure traçable.


| Champ                        | Type             | Description                                          |
|------------------------------|------------------|------------------------------------------------------|
| `MeasurementTraceabilityUid` | `string` (PK)    | Identifiant unique de la mesure                      |
| `ProductUid`                 | `string` (FK)    | Identifiant du produit mesuré                        |
| `SerialNumber`               | `int`            | Numéro de série du produit                           |
| `Label`                      | `string`         | Libellé de la mesure (ex: `PROG_TORADEX`)            |
| `Value`                      | `string`         | Valeur mesurée                                       |
| `Classification`             | `string`         | Classification (ex: OK, NOK, Alerte)                 |
| `CreationDate`               | `DateTimeOffset` | Date/heure d'enregistrement                          |
| `OperationNumber`            | `int`            | Numéro d'opération dans la gamme (ex: 30)            |
| `UnitUid`                    | `string`         | Identifiant unité de mesure (ex: STR)                |
| `UserUid`                    | `string` (FK)    | Opérateur ayant effectué la mesure                   |
| `MachineUid`                 | `string` (FK)    | Machine utilisée (ex: MO03B)                         |
| `ManufacturingOrderUid`      | `int?` (FK)      | Ordre de fabrication associé (nullable)              |

### 6.2 MacAddress — Gestion des Adresses MAC


| Colonne          | Type                             | Description                                   |
|------------------|----------------------------------|-----------------------------------------------|
| `Id`             | `int` (PK, auto-incrémenté)      | Identifiant unique                            |
| `MacAddressValue`| `char(17)`                        | Adresse MAC au format `00:1A:2B:00:00:01`     |
| `Status`         | `enum('AVAILABLE','RESERVED','USED')` | Statut de disponibilité                  |
| `ReservedAt`     | `DateTime?`                       | Date de réservation (nullable)                |
| `UsedAt`         | `DateTime?`                       | Date d'utilisation effective (nullable)       |
| `CreatedAt`      | `DateTime`                        | Date de création de l'enregistrement          |

**Cycle de vie d'une MAC** : `AVAILABLE` → `RESERVED` (lors du `GET /next-mac`) → `USED` (après confirmation de programmation).

### 6.3 User — Opérateur


| Champ        | Type             | Description                                   |
|--------------|------------------|-----------------------------------------------|
| `UserUid`    | `string` (PK)    | Identifiant unique de l'opérateur             |
| `LastName`   | `string`         | Nom de famille                                |
| `FirstName`  | `string`         | Prénom                                        |
| `EntryDate`  | `DateTimeOffset` | Date d'entrée dans l'entreprise               |
| `ExitDate`   | `DateTimeOffset` | Date de sortie / fin d'activité               |
| `Department` | `string`         | Département de rattachement                   |

### 6.4 ManufacturingOrder — Ordre de Fabrication


| Champ                  | Type          | Description                                    |
|------------------------|---------------|------------------------------------------------|
| `ManufacturingOrderUid`| `int` (PK)    | Identifiant unique de l'OF                     |
| `ProductUid`           | `string`      | Identifiant produit associé                    |
| `Quantity`             | `int`         | Quantité totale à produire                     |
| `FirstSerialNumber`    | `int`         | Premier numéro de série attribué               |
| `InternalOrderNumber`  | `string(64)`  | Numéro de commande interne                     |
| `ExternalOrderNumber`  | `string(64)`  | Numéro de commande externe (client/ERP/GPAO)   |
| `Status`               | `string(64)`  | Statut dans le workflow (ex: `ACTIVE`)          |

### 6.5 Relations entre Entités

```
ManufacturingOrder ─►1:N──► MeasurementTraceability
User               ─►1:N──► MeasurementTraceability
Machine            ─►1:N──► MeasurementTraceability
Article (Product)  ─►1:N──► MeasurementTraceability

MacAddress   (table indépendante, liée par logique métier)
```

La traçabilité d'une programmation FlashBench est enregistrée dans `MeasurementTraceability` via l'endpoint `POST /api/MeasurementTraceability/create-with-mac` de l'API externe, avec enrichissement MAC depuis la table `MacAddresses`. Les endpoints `/next-mac`, `/programmed-board` et `/programmed-boards/today` qui étaient auparavant dans le service FastAPI local ont été migrés vers cette API externe.

---

## 7. Scripts Embarqués

### 7.1 Script Principal (`scripts/wrapup.sh` / `scripts/prepare.sh`)

Exécuté sur la carte Toradex **après** l'installation de l'image Tezi. Séquence :

```
1. START     → Envoie numéro de série/produit/révision via TCP vers 192.168.10.1:5000
2. MAC REQ   → GET http://192.168.10.1:10000/api/MacAddresses/next-mac
3. VALIDATE  → Vérification regex XX:XX:XX:XX:XX:XX
4. DETECT    → Récupère IP et MAC usine de l'interface réseau
5. INJECT    → fw_setenv ethaddr <clientMac> + vérification fw_printenv
6. TRACE     → POST http://192.168.10.1:5001/api/traceability/notify
7. REBOOT    → sync && reboot -f
```

Chaque étape journalise des événements pipe-délimités vers TCP:5000 pour le monitoring backend. Sortie avec code 1 en cas d'erreur.

### 7.2 Scripts de Simulation d'Erreur

Six scripts de test dans `scripts/` simulant des modes de défaillance spécifiques :

| Script                               | Erreur Simulée                       |
|--------------------------------------|--------------------------------------|
| `wrapup_err1_api_unreachable.sh`     | API MAC injoignable                  |
| `wrapup_err2_invalid_mac_response.sh`| JSON invalide depuis l'API MAC       |
| `wrapup_err3_invalid_mac_format.sh`  | Échec validation format MAC          |
| `wrapup_err4_fw_setenv_failed.sh`    | Échec écriture env U-Boot            |
| `wrapup_err5_mac_verification_failed.sh` | Incohérence relecture MAC        |
| `wrapup_err6_traceability_failed.sh` | Erreur HTTP API traçabilité          |

---

## 8. Infrastructure & Déploiement

### 8.1 Docker

**`docker-compose.yml`** — service unique `frontend` :

- Build multi-stage (node:20-alpine → nginx:alpine)
- Port : `8080:80`
- `extra_hosts: host.docker.internal:host-gateway` pour accès au backend hôte
- `restart: unless-stopped`

**`Dockerfile`** — Build en 2 étapes :

1. **Build** : `node:20-alpine`, `npm ci`, copie source + vendor, `npm run build`
2. **Serve** : `nginx:alpine`, config personnalisée, copie `/app/dist`

**`nginx.conf`** — Reverse proxy dans Docker :

| Route          | Destination                                         | Notes                      |
|----------------|-----------------------------------------------------|----------------------------|
| `/`            | SPA React (fichiers statiques)                     | try_files → index.html     |
| `/api/*`       | `http://host.docker.internal:5001/api/`            | Proxy HTTP                 |
| `/socket.io/*` | `http://host.docker.internal:5001/socket.io/`      | Upgrade WebSocket          |
| `/vnc/*`       | `http://host.docker.internal:6080/`                | Upgrade WebSocket, timeout 86400s |

### 8.2 Service Systemd (`backend/flashbench.service`)

```ini
[Unit]
Description=FlashBench Backend

[Service]
User=romu_admin
WorkingDirectory=<dossier backend>
ExecStart=.venv/bin/python main.py
Restart=always
RestartSec=5
SyslogIdentifier=flashbench

[Install]
WantedBy=multi-user.target
```

---

## 9. Cycle de Vie Complet d'un Flashage

```
 1. L'opérateur se connecte
    → sélectionne son identité depuis l'API Users externe

 2. L'opérateur scanne le code-barres de l'ordre de fabrication
    → validé contre l'API externe (statut ACTIVE requis)

 3. L'opérateur scanne un code-barres de position (POS1-POS5)
    → le slot passe en awaiting_card

 4. L'opérateur insère la carte et appuie sur Entrée
    → slot passe en awaiting_boot, rejoint la file FIFO

 5. La carte s'allume
    → exécute Tezi, télécharge les fichiers image depuis Nginx

 6. La carte envoie son numéro de série via TCP:5000
    → SerialListener → ModuleStore.register_board()

 7. ModuleStore notifie les souscripteurs
    → VncProxyManager met à jour le fichier tokens
    → modules_update émis vers le frontend

 8. Frontend mapModulesToSlots()
    → correspondance FIFO → slot passe en flashing
    → board_position_assigned émis vers le backend

 9. Frontend VncViewer se connecte via websockify
    → affichage VNC en direct

10. Tezi termine → le script prepare.sh/wrapup.sh embarqué s'exécute :
    a. Obtient une MAC depuis l'API externe
    b. Injecte la MAC via fw_setenv
    c. POST /api/traceability/notify
       → le backend enrichit et transmet à l'API externe
       → mark_done()

11. La carte redémarre
    → VNC se déconnecte
    → le slot affiche l'overlay done/error

12. L'opérateur peut re-scanner la position pour un nouveau cycle
```

---

## 10. Patterns de Gestion d'Erreur

| Composant            | Stratégie                                                        |
|----------------------|------------------------------------------------------------------|
| SerialListener TCP   | Watchdog avec back-off exponentiel (2s → 60s)                   |
| Connexions VNC       | 30 retries à 3s d'intervalle, timeout 10s par tentative         |
| Événements cartes    | Mot-clé `ERROR` pipe-délimité déclenche `mark_error()`          |
| API externe          | Erreurs HTTP remontées en 502/504 avec messages détaillés       |
| Monitoring services  | Polling continu 10s, redémarrage auto des flux de logs          |
| websockify           | Redémarrage automatique en cas d'arrêt inattendu                |
| Processus résiduels  | Nettoyage `fuser` au démarrage pour ports 5000/6080/5001        |

---

> **Résumé quantitatif** : Frontend React (10 composants, ~2200 lignes TSX), Backend Flask-SocketIO (14 modules Python, ~1700 lignes), 7 scripts shell embarqués, infrastructure Docker/systemd.
