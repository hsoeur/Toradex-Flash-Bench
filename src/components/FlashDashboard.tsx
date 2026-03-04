import { useEffect, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import type { ModulesMap } from '../types/board';
import BoardCard from './BoardCard';
import ConsolePanel from './ConsolePanel';
import ServicesPanel, { type ServicesStatus } from './ServicesPanel';

const BACKEND_URL = 'http://localhost:5001';

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

const DEFAULT_SERVICES_STATUS: ServicesStatus = {
  mac_api:       'stopped',
  docker:        'stopped',
  db_connection: 'disconnected',
};

export default function FlashDashboard() {
  const [modules, setModules] = useState<ModulesMap>({});
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [servicesOpen, setServicesOpen] = useState(false);
  const [servicesStatus, setServicesStatus] = useState<ServicesStatus>(DEFAULT_SERVICES_STATUS);
  const [socket, setSocket] = useState<Socket | null>(null);

  useEffect(() => {
    const s = io(BACKEND_URL, { transports: ['websocket', 'polling'] });
    setSocket(s);

    s.on('connect',       () => setConnectionStatus('connected'));
    s.on('disconnect',    () => setConnectionStatus('disconnected'));
    s.on('connect_error', () => setConnectionStatus('disconnected'));
    s.on('modules_update', (data: ModulesMap) => setModules({ ...data }));
    s.on('services_status', (data: ServicesStatus) => setServicesStatus(data));

    return () => { s.disconnect(); };
  }, []);

  const boardEntries = Object.entries(modules);
  const doneCount     = boardEntries.filter(([, d]) => d.status === 'done').length;
  const flashingCount = boardEntries.filter(([, d]) => d.status === 'flashing').length;
  const waitingCount  = boardEntries.filter(([, d]) => d.status === 'waiting').length;

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard__header">
        <div className="dashboard__title-group">
          <div className="dashboard__logo">
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <rect width="32" height="32" rx="6" fill="#3b82f6" />
              <path
                d="M8 22l4-12h2l2 8 2-8h2l4 12h-2l-2.8-8.4L17 22h-2l-2.2-8.4L10 22H8z"
                fill="white"
              />
            </svg>
          </div>
          <div>
            <h1 className="dashboard__title">Verdin AM62 Flash Monitor</h1>
            <p className="dashboard__subtitle">Surveillance du flashage en temps réel</p>
          </div>
        </div>

        <div className="dashboard__status-bar">
          <div className="dashboard__stat">
            <span className="dashboard__stat-value dashboard__stat-value--flashing">{flashingCount}</span>
            <span className="dashboard__stat-label">En cours</span>
          </div>
          <div className="dashboard__stat">
            <span className="dashboard__stat-value dashboard__stat-value--done">{doneCount}</span>
            <span className="dashboard__stat-label">Terminés</span>
          </div>
          <div className="dashboard__stat">
            <span className="dashboard__stat-value dashboard__stat-value--waiting">{waitingCount}</span>
            <span className="dashboard__stat-label">En attente</span>
          </div>

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
            {/* DB status dot in button */}
            <span className={`dashboard__db-dot dashboard__db-dot--${servicesStatus.db_connection}`} />
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
        ) : (
          <div className="board-grid">
            {boardEntries.map(([ip, data]) => (
              <BoardCard key={ip} ip={ip} data={data} />
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
      />
    </div>
  );
}
