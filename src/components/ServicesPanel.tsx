import { useEffect, useRef, useState, useCallback } from 'react';
import type { Socket } from 'socket.io-client';

const BACKEND_URL = 'http://localhost:5001';

// ──────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────

export type ServiceSource = 'dhcp' | 'nginx' | 'mac_api' | 'docker';

export interface ServiceLogEntry {
  ts: number;
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical';
  message: string;
  source: ServiceSource;
}

export interface ServicesStatus {
  mac_api: 'running' | 'stopped' | 'starting' | 'stopping' | 'restarting';
  docker:  'running' | 'stopped' | 'starting' | 'stopping' | 'restarting';
  db_connection: 'connected' | 'disconnected' | 'checking';
}

interface Props {
  socket: Socket | null;
  open: boolean;
  onClose: () => void;
  servicesStatus: ServicesStatus;
}

// ──────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('fr-FR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
}

async function callServiceApi(path: string) {
  try {
    await fetch(`${BACKEND_URL}${path}`, { method: 'POST' });
  } catch {
    // silently ignore — UI state is driven by socket events
  }
}

// ──────────────────────────────────────────────────
// Sub-component: Log console for one source
// ──────────────────────────────────────────────────

function ServiceLogPane({ lines }: { lines: ServiceLogEntry[] }) {
  const [filter, setFilter] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [lines, autoScroll]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 40);
  };

  const filtered = filter
    ? lines.filter(l =>
        l.message.toLowerCase().includes(filter.toLowerCase()) ||
        l.level.includes(filter.toLowerCase()),
      )
    : lines;

  return (
    <div className="svc-log-pane">
      <div className="svc-log-pane__toolbar">
        <input
          className="console-panel__filter"
          placeholder="Filtrer…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <button
          className={`console-panel__btn console-panel__btn--scroll ${autoScroll ? 'active' : ''}`}
          onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }}
          title="Défilement automatique"
        >
          ↓ Auto
        </button>
        <span className="svc-log-pane__count">{filtered.length} ligne{filtered.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="svc-log-pane__body" ref={scrollRef} onScroll={handleScroll}>
        {filtered.length === 0 ? (
          <div className="console-panel__empty">
            {filter ? 'Aucun résultat.' : 'En attente de logs…'}
          </div>
        ) : (
          filtered.map((entry, i) => (
            <div key={i} className={`console-line console-line--${entry.level}`}>
              <span className="console-line__ts">{formatTs(entry.ts)}</span>
              <span className={`console-line__level console-line__level--${entry.level}`}>
                {entry.level.toUpperCase().padEnd(8)}
              </span>
              <span className="console-line__msg">{entry.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────
// Sub-component: Service control row (start / stop)
// ──────────────────────────────────────────────────

function ServiceControl({
  label,
  status,
  onStart,
  onStop,
  onRestart,
}: {
  label: string;
  status: ServicesStatus['mac_api'] | ServicesStatus['docker'];
  onStart: () => void;
  onStop: () => void;
  onRestart: () => void;
}) {
  const isRunning  = status === 'running';
  const isBusy     = status === 'starting' || status === 'stopping' || status === 'restarting';

  const statusLabel =
    status === 'running'    ? 'En cours'   :
    status === 'starting'   ? 'Démarrage…' :
    status === 'stopping'   ? 'Arrêt…'     :
    status === 'restarting' ? 'Redémarrage…' :
                              'Arrêté';

  return (
    <div className="svc-control">
      <span className="svc-control__label">{label}</span>
      <span className={`svc-control__badge svc-control__badge--${status}`}>
        <span className="svc-control__dot" />
        {statusLabel}
      </span>
      <div className="svc-control__actions">
        <button
          className="svc-control__btn svc-control__btn--start"
          onClick={onStart}
          disabled={isRunning || isBusy}
          title="Démarrer"
        >
          ▶ Démarrer
        </button>
        <button
          className="svc-control__btn svc-control__btn--restart"
          onClick={onRestart}
          disabled={!isRunning || isBusy}
          title="Redémarrer"
        >
          ↺ Redémarrer
        </button>
        <button
          className="svc-control__btn svc-control__btn--stop"
          onClick={onStop}
          disabled={!isRunning || isBusy}
          title="Arrêter"
        >
          ■ Arrêter
        </button>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────
// Main panel
// ──────────────────────────────────────────────────

const TABS: { id: ServiceSource; label: string }[] = [
  { id: 'dhcp',    label: 'DHCP' },
  { id: 'nginx',   label: 'NGINX' },
  { id: 'mac_api', label: 'MAC API' },
  { id: 'docker',  label: 'Docker DB' },
];

export default function ServicesPanel({ socket, open, onClose, servicesStatus }: Props) {
  const [activeTab, setActiveTab] = useState<ServiceSource>('dhcp');
  const [logs, setLogs] = useState<Record<ServiceSource, ServiceLogEntry[]>>({
    dhcp: [], nginx: [], mac_api: [], docker: [],
  });

  // ── socket listeners ──────────────────────────
  useEffect(() => {
    if (!socket) return;

    const onHistory = (history: Record<ServiceSource, ServiceLogEntry[]>) => {
      setLogs({
        dhcp:    history.dhcp    ?? [],
        nginx:   history.nginx   ?? [],
        mac_api: history.mac_api ?? [],
        docker:  history.docker  ?? [],
      });
    };

    const onLine = (entry: ServiceLogEntry) => {
      const src = entry.source;
      if (!src) return;
      setLogs(prev => {
        const updated = [...(prev[src] ?? []), entry];
        return { ...prev, [src]: updated.length > 500 ? updated.slice(-500) : updated };
      });
    };

    socket.on('service_log_history', onHistory);
    socket.on('service_log', onLine);

    return () => {
      socket.off('service_log_history', onHistory);
      socket.off('service_log', onLine);
    };
  }, [socket]);

  // ── service actions ───────────────────────────
  const startMacApi   = useCallback(() => callServiceApi('/api/services/mac-api/start'),   []);
  const stopMacApi    = useCallback(() => callServiceApi('/api/services/mac-api/stop'),    []);
  const restartMacApi = useCallback(() => callServiceApi('/api/services/mac-api/restart'), []);
  const startDocker   = useCallback(() => callServiceApi('/api/services/docker/start'),   []);
  const stopDocker    = useCallback(() => callServiceApi('/api/services/docker/stop'),    []);
  const restartDocker = useCallback(() => callServiceApi('/api/services/docker/restart'), []);

  const dbStatus = servicesStatus.db_connection;

  return (
    <>
      {/* Backdrop */}
      <div
        className={`svc-overlay ${open ? 'svc-overlay--visible' : ''}`}
        onClick={onClose}
      />

      {/* Right-side panel */}
      <aside className={`svc-panel ${open ? 'svc-panel--open' : ''}`}>

        {/* Panel header */}
        <div className="svc-panel__header">
          <div className="svc-panel__title-row">
            <span className="svc-panel__title">Services</span>
            {/* Global DB badge */}
            <span className={`svc-db-badge svc-db-badge--${dbStatus}`}>
              <span className="svc-db-badge__dot" />
              {dbStatus === 'connected'    ? 'DB connectée'     :
               dbStatus === 'checking'     ? 'DB vérification…' :
                                            'DB déconnectée'}
            </span>
          </div>
          <button className="console-panel__btn console-panel__btn--close" onClick={onClose}>✕</button>
        </div>

        {/* Tabs */}
        <div className="svc-tabs">
          {TABS.map(tab => (
            <button
              key={tab.id}
              className={`svc-tab ${activeTab === tab.id ? 'svc-tab--active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
              {logs[tab.id].length > 0 && (
                <span className="svc-tab__count">{logs[tab.id].length}</span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div className="svc-panel__content">

          {/* MAC API tab: control + logs */}
          {activeTab === 'mac_api' && (
            <>
              <ServiceControl
                label="MAC API  (api.py · uvicorn :8000)"
                status={servicesStatus.mac_api}
                onStart={startMacApi}
                onStop={stopMacApi}
                onRestart={restartMacApi}
              />
              <ServiceLogPane lines={logs.mac_api} />
            </>
          )}

          {/* Docker tab: control + DB status + logs */}
          {activeTab === 'docker' && (
            <>
              <ServiceControl
                label="Docker Compose  (MySQL :3307 + phpMyAdmin :8081)"
                status={servicesStatus.docker}
                onStart={startDocker}
                onStop={stopDocker}
                onRestart={restartDocker}
              />
              <div className={`svc-db-detail svc-db-detail--${dbStatus}`}>
                <span className="svc-db-detail__dot" />
                <span>
                  {dbStatus === 'connected'
                    ? 'MySQL localhost:3307 — connexion établie'
                    : dbStatus === 'checking'
                    ? 'Vérification de la connexion MySQL…'
                    : 'MySQL localhost:3307 — injoignable'}
                </span>
              </div>
              <ServiceLogPane lines={logs.docker} />
            </>
          )}

          {/* DHCP / NGINX tabs: logs only */}
          {(activeTab === 'dhcp' || activeTab === 'nginx') && (
            <ServiceLogPane lines={logs[activeTab]} />
          )}

        </div>
      </aside>
    </>
  );
}
