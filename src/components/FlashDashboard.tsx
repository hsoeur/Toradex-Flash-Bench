import { useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import type { ModulesMap } from '../types/board';
import ConsolePanel from './ConsolePanel';
import ImageSelectorPanel from './ImageSelectorPanel';
import ServicesPanel, { type ServicesStatus, type MonitorStatus } from './ServicesPanel';
import TraceabilityPanel from './TraceabilityPanel';
import VncViewer from './VncViewer';

import type { Theme } from '../App';

const BACKEND_URL = 'http://localhost:5001';

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

const DEFAULT_SERVICES_STATUS: ServicesStatus = {
  db_connection:  'disconnected',
  dnsmasq_status: 'unknown',
  nginx_status:   'unknown',
};

const DEFAULT_MONITOR_STATUS: MonitorStatus = {
  status:      'starting',
  last_error:  '',
  retry_count: 0,
  host:        '0.0.0.0',
  port:        5000,
};

interface Props {
  operatorId: string;
  operatorName: string;
  orderNumber: string;
  onLogout: () => void;
  theme: Theme;
  onToggleTheme: () => void;
}

export default function FlashDashboard({ operatorId, operatorName, orderNumber, onLogout, theme, onToggleTheme }: Props) {
  const [modules, setModules] = useState<ModulesMap>({});
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [servicesOpen, setServicesOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [imageSelectorOpen, setImageSelectorOpen] = useState(false);
  const [servicesStatus, setServicesStatus] = useState<ServicesStatus>(DEFAULT_SERVICES_STATUS);
  const [monitorStatus, setMonitorStatus] = useState<MonitorStatus>(DEFAULT_MONITOR_STATUS);
  const [socket, setSocket] = useState<Socket | null>(null);
  const [vncWsPort, setVncWsPort] = useState<number>(6080);

  useEffect(() => {
    const s = io(BACKEND_URL, { transports: ['websocket', 'polling'] });
    setSocket(s);

    s.on('connect', () => {
      setConnectionStatus('connected');
      // Send session context so the backend can enrich traceability calls
      s.emit('set_session_context', { operatorId: operatorId, orderNumber });
    });
    s.on('disconnect',    () => setConnectionStatus('disconnected'));
    s.on('connect_error', () => setConnectionStatus('disconnected'));
    s.on('modules_update',  (data: ModulesMap)      => setModules({ ...data }));
    s.on('services_status', (data: ServicesStatus)  => setServicesStatus(data));
    s.on('monitor_status',  (data: MonitorStatus)   => setMonitorStatus(data));
    s.on('vnc_config',      (data: { ws_port: number }) => setVncWsPort(data.ws_port));

    return () => { s.disconnect(); };
  }, [operatorId, orderNumber]);

  const boardEntries = Object.entries(modules);
  const doneCount     = boardEntries.filter(([, d]) => d.status === 'done').length;
  const errorCount    = boardEntries.filter(([, d]) => d.status === 'error').length;
  const flashingCount = boardEntries.filter(([, d]) => d.status === 'flashing').length;
  const waitingCount  = boardEntries.filter(([, d]) => d.status === 'waiting').length;
  const flashingBoards = boardEntries.filter(([, d]) => d.status === 'flashing' || d.status === 'done' || d.status === 'error');
  const finishedCount = doneCount + errorCount;

  const handleResetBoards = (mode: 'done' | 'all' = 'done') => {
    if (!socket) return;
    socket.emit('reset_boards', { mode });
  };

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard__header">
        <div className="dashboard__title-group">
          <div className="dashboard__logo">
            <img src="/images.png" alt="Toradex" height="32" />
          </div>
          <div>
            <h1 className="dashboard__title">Verdin AM62 Flash Monitor</h1>
            <p className="dashboard__subtitle">
              Surveillance du flashage en temps réel
              <span className="dashboard__order-badge">
                <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                  <rect x="1" y="1" width="4" height="14" rx="0.5" fill="currentColor"/>
                  <rect x="6" y="1" width="2" height="14" rx="0.5" fill="currentColor"/>
                  <rect x="9" y="1" width="4" height="14" rx="0.5" fill="currentColor"/>
                  <rect x="14" y="1" width="1" height="14" rx="0.5" fill="currentColor"/>
                </svg>
                OF&nbsp;{orderNumber}
              </span>
            </p>
          </div>
        </div>

        <div className="dashboard__status-bar">
          {/* Reset button — visible when any boards exist */}
          {boardEntries.length > 0 && (
            <button
              className="dashboard__console-btn dashboard__reset-btn"
              onClick={() => handleResetBoards(finishedCount > 0 ? 'done' : 'all')}
              title={finishedCount > 0
                ? 'Effacer les cartes terminées et en erreur'
                : 'Effacer toutes les cartes'
              }
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M2 2l12 12M14 2L2 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              {finishedCount > 0
                ? `Réinitialiser (${finishedCount})`
                : 'Tout effacer'
              }
            </button>
          )}

          {/* Image selector button */}
          <button
            className={`dashboard__console-btn ${imageSelectorOpen ? 'dashboard__console-btn--active' : ''}`}
            onClick={() => setImageSelectorOpen(o => !o)}
            title="Sélectionner l'image Tezi"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="3" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.3" />
              <path d="M4 7h8M4 10h5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <circle cx="12" cy="10" r="1.5" fill="currentColor" />
            </svg>
            Image
          </button>

          {/* Console button */}
          <button
            className={`dashboard__console-btn ${consoleOpen ? 'dashboard__console-btn--active' : ''}`}
            onClick={() => setConsoleOpen(o => !o)}
            title="Ouvrir la console FlashBench"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="2" width="14" height="12" rx="2" stroke="currentColor" strokeWidth="1.4"/>
              <path d="M4 6l3 2.5L4 11" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
              <path d="M9 11h3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
            </svg>
            Console
          </button>

          {/* Traceability button */}
          <button
            className={`dashboard__console-btn ${traceOpen ? 'dashboard__console-btn--active' : ''}`}
            onClick={() => setTraceOpen(o => !o)}
            title="Traçabilité des cartes flashées aujourd'hui"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="2" y="1" width="10" height="13" rx="1.5" stroke="currentColor" strokeWidth="1.3"/>
              <path d="M4 5h6M4 8h6M4 11h4" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
              <circle cx="13" cy="12" r="2.5" fill="currentColor" opacity="0.9"/>
              <path d="M12.3 12l.5.5.9-.9" stroke="white" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
            Traçabilité
          </button>

          {/* Services button */}
          <button
            className={`dashboard__console-btn ${servicesOpen ? 'dashboard__console-btn--active' : ''}`}
            onClick={() => setServicesOpen(o => !o)}
            title="Ouvrir le panneau des services"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="8" r="2.5" stroke="currentColor" strokeWidth="1.4"/>
              <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.42 1.42M11.54 11.54l1.41 1.41M3.05 12.95l1.42-1.41M11.54 4.46l1.41-1.41" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/>
            </svg>
            Services
            {/* DB status dot */}
            <span className={`dashboard__db-dot dashboard__db-dot--${servicesStatus.db_connection}`} />
            {/* Monitor :5000 dot */}
            <span
              className={`dashboard__db-dot dashboard__db-dot--${
                monitorStatus.status === 'running'    ? 'connected' :
                monitorStatus.status === 'error'      ? 'disconnected' :
                                                        'checking'
              }`}
              title={`Monitor TCP :5000 — ${monitorStatus.status}${
                monitorStatus.retry_count > 0 ? ` (${monitorStatus.retry_count} retry)` : ''
              }`}
            />
          </button>

          <div className={`dashboard__conn dashboard__conn--${connectionStatus}`}>
            <span className="dashboard__conn-dot" />
            <span className="dashboard__conn-label">
              {connectionStatus === 'connected'
                ? 'Backend connecté'
                : connectionStatus === 'connecting'
                ? 'Connexion...'
                : 'Backend déconnecté'}
            </span>
          </div>

          {/* Theme toggle */}
          <button
            className="theme-toggle"
            onClick={onToggleTheme}
            title={theme === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre'}
          >
            {theme === 'dark' ? (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5"/>
                <line x1="12" y1="1" x2="12" y2="3"/>
                <line x1="12" y1="21" x2="12" y2="23"/>
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
                <line x1="1" y1="12" x2="3" y2="12"/>
                <line x1="21" y1="12" x2="23" y2="12"/>
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
              </svg>
            ) : (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
              </svg>
            )}
          </button>

          {/* Operator chip */}
          <div className="dashboard__operator">
            <span className="dashboard__operator-avatar">
              {operatorName.charAt(0).toUpperCase()}
            </span>
            <span className="dashboard__operator-name">{operatorName}</span>
            <button
              className="dashboard__operator-logout"
              onClick={onLogout}
              title="Changer d'opérateur"
            >
              <svg width="13" height="13" viewBox="0 0 16 16" fill="none">
                <path d="M6 2H3a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                <path d="M10 11l3-3-3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                <path d="M13 8H6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </button>
          </div>
        </div>
      </header>

      {/* Content */}
      <main className="dashboard__content">
        {boardEntries.length === 0 ? (
          <div className="dashboard__empty">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none" opacity="0.4">
              <rect x="8" y="14" width="48" height="36" rx="4" stroke="currentColor" strokeWidth="2" />
              <path d="M20 50v4M44 50v4M14 54h36" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <circle cx="32" cy="32" r="8" stroke="currentColor" strokeWidth="2" />
              <path d="M32 28v4l3 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <p className="dashboard__empty-title">Aucune carte détectée</p>
            <p className="dashboard__empty-sub">
              En attente de connexion des modules Verdin AM62…
            </p>
          </div>
        ) : flashingBoards.length === 0 ? (
          <div className="dashboard__empty">
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none" opacity="0.4">
              <rect x="8" y="14" width="48" height="36" rx="4" stroke="currentColor" strokeWidth="2" />
              <path d="M20 50v4M44 50v4M14 54h36" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              <path d="M24 32h16M32 24v16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <p className="dashboard__empty-title">{boardEntries.length} carte{boardEntries.length > 1 ? 's' : ''} détectée{boardEntries.length > 1 ? 's' : ''}</p>
            <p className="dashboard__empty-sub">
              Aucun flashage en cours — les écrans VNC apparaîtront automatiquement
            </p>
          </div>
        ) : (
          <div className="vnc-grid">
            {flashingBoards.map(([ip, data]) => (
              <VncViewer
                key={ip}
                ip={ip}
                serial={data.serial}
                wsPort={vncWsPort}
                startTime={data.startTime}
                boardStatus={data.status}
                errorMessage={data.errorMessage ?? null}
              />
            ))}
          </div>
        )}
      </main>

      {/* Console slide-in panel (bottom) */}
      <ConsolePanel
        socket={socket}
        open={consoleOpen}
        onClose={() => setConsoleOpen(false)}
      />

      {/* Services slide-in panel (right) */}
      <ServicesPanel
        socket={socket}
        open={servicesOpen}
        onClose={() => setServicesOpen(false)}
        servicesStatus={servicesStatus}
        monitorStatus={monitorStatus}
      />

      {/* Traceability slide-in panel (right) */}
      <TraceabilityPanel
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
      />

      {/* Image selector slide-in panel (right) */}
      <ImageSelectorPanel
        socket={socket}
        open={imageSelectorOpen}
        onClose={() => setImageSelectorOpen(false)}
      />
    </div>
  );
}
