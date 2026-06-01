import { useCallback, useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import type { ModulesMap, PositionSlot as PositionSlotType } from '../types/board';
import { NUM_POSITIONS, createEmptySlot } from '../types/board';
import ConsolePanel from './ConsolePanel';
import ImageSelectorPanel from './ImageSelectorPanel';
import PositionSlot from './PositionSlot';
import ServicesPanel, { type ServicesStatus, type MonitorStatus } from './ServicesPanel';
import TraceabilityPanel from './TraceabilityPanel';

import type { Theme } from '../App';

// In production (Docker), nginx proxies /socket.io/ and /api/ to the backend.
// In development, point to the local backend directly.
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected';

/** Regex matching barcode scans: POS1 … POS5 (case-insensitive) */
const POS_RE = /^POS([1-5])$/i;

/**
 * Regex matching a card barcode.
 * Must be a numeric string of at least 8 digits.
 * The last 8 digits are the board serial number.
 */
const CARD_BARCODE_RE = /^\d{8,}$/;

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

function initSlots(): PositionSlotType[] {
  return Array.from({ length: NUM_POSITIONS }, () => createEmptySlot());
}

interface Props {
  operatorId: string;
  operatorName: string;
  orderNumber: string;
  onLogout: () => void;
  theme: Theme;
  onToggleTheme: () => void;
}

export default function FlashDashboard({ operatorId, operatorName, orderNumber, onLogout, theme, onToggleTheme }: Props) {
  // ── Socket & backend state ────────────────────
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connecting');
  const [consoleOpen, setConsoleOpen] = useState(false);
  const [servicesOpen, setServicesOpen] = useState(false);
  const [traceOpen, setTraceOpen] = useState(false);
  const [imageSelectorOpen, setImageSelectorOpen] = useState(false);
  const [servicesStatus, setServicesStatus] = useState<ServicesStatus>(DEFAULT_SERVICES_STATUS);
  const [monitorStatus, setMonitorStatus] = useState<MonitorStatus>(DEFAULT_MONITOR_STATUS);
  const [socket, setSocket] = useState<Socket | null>(null);
  const [vncWsPort, setVncWsPort] = useState<number>(6080);
  const [boardInterfaceConnected, setBoardInterfaceConnected] = useState<boolean>(false);

  // ── Position slot state ───────────────────────
  const [slots, setSlots] = useState<PositionSlotType[]>(initSlots);
  /**
   * Synchronous set of IPs that have been claimed by a slot.
   * Ensures the same IP can never be assigned to two different slots
   * even when mapModulesToSlots is called multiple times before React renders.
   */
  const assignedIpsRef = useRef<Set<string>>(new Set());
  /** Feedback text shown briefly under the scan bar */
  const [scanFeedback, setScanFeedback] = useState<string>('');
  /** Track which slot is in awaiting_card state (for Enter confirmation) */
  const awaitingCardSlot = slots.findIndex(s => s.state === 'awaiting_card');

  // ── Modules from backend ──────────────────────
  const modulesRef = useRef<ModulesMap>({});

  // ── Refs kept in sync with latest state (for use inside
  //    non-React callbacks: socket events, timers, etc.) ──
  const slotsRef = useRef(slots);
  slotsRef.current = slots;
  const socketRef = useRef(socket);
  socketRef.current = socket;

  // ── Global keyboard buffer for barcode scanner ──
  // Captures keystrokes globally (no need for a focused input).
  // Barcode scanners type characters quickly then send Enter.
  const scanBufferRef = useRef<string>('');
  const scanTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Show temporary feedback
  const showFeedback = useCallback((msg: string) => {
    setScanFeedback(msg);
    setTimeout(() => setScanFeedback(''), 3000);
  }, []);
  const showFeedbackRef = useRef(showFeedback);
  showFeedbackRef.current = showFeedback;

  // ── Socket.IO connection ──────────────────────
  useEffect(() => {
    const s = io(BACKEND_URL, { transports: ['websocket', 'polling'] });
    setSocket(s);

    s.on('connect', () => {
      setConnectionStatus('connected');
      s.emit('set_session_context', { operatorId, orderNumber });
    });
    s.on('disconnect',    () => setConnectionStatus('disconnected'));
    s.on('connect_error', () => setConnectionStatus('disconnected'));
    s.on('services_status', (data: ServicesStatus) => setServicesStatus(data));
    s.on('monitor_status',  (data: MonitorStatus)  => setMonitorStatus(data));
    s.on('vnc_config',      (data: { ws_port: number }) => setVncWsPort(data.ws_port));

    // Board Interface status
    s.on('board_interface_status', (data: { connected: boolean }) => {
      setBoardInterfaceConnected(data.connected);
    });

    // Power operation results
    s.on('power_status', (data: { position: number; status: string; message?: string }) => {
      if (data.status === 'powered_on') {
        setBoardInterfaceConnected(true);
      } else if (data.status === 'error') {
        showFeedbackRef.current(
          `⚠️ Erreur alimentation POS${data.position} : ${data.message ?? 'erreur inconnue'}`
        );
      }
    });

    // modules_update: update ref + trigger slot mapping
    s.on('modules_update', (data: ModulesMap) => {
      modulesRef.current = data;
      mapModulesToSlots(data);
    });

    return () => { s.disconnect(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [operatorId, orderNumber]);

  // ── Map boards to slots by SERIAL NUMBER match (deterministic) ─
  // When a board registers via TCP, its serial is compared against
  // the expectedSerial of each awaiting_boot slot. Only exact
  // matches are accepted — no FIFO, no guessing.
  const mapModulesToSlots = useCallback((newModules: ModulesMap) => {
    const currentSlots = slotsRef.current;

    // Build assignments by matching serial numbers
    type Assignment = { slotIdx: number; ip: string };
    const assignments: Assignment[] = [];

    for (const [ip, mod] of Object.entries(newModules)) {
      // Skip IPs already claimed
      if (assignedIpsRef.current.has(ip)) continue;

      // Skip IPs that were cleared from any slot
      let isCleared = false;
      for (const slot of currentSlots) {
        if (slot.clearedIps.has(ip)) { isCleared = true; break; }
      }
      if (isCleared) continue;

      // Find a slot that expects THIS serial
      for (let i = 0; i < currentSlots.length; i++) {
        const slot = currentSlots[i];
        if (slot.state === 'awaiting_boot' && slot.expectedSerial && slot.expectedSerial === mod.serial) {
          assignedIpsRef.current.add(ip);
          assignments.push({ slotIdx: i, ip });
          break; // One board per slot
        }
      }
    }

    // Apply to React state
    if (assignments.length > 0 || Object.keys(newModules).length > 0) {
      setSlots(prev => {
        const updated = [...prev];

        // Apply serial-matched assignments
        for (const { slotIdx, ip } of assignments) {
          if (updated[slotIdx]?.state === 'awaiting_boot') {
            updated[slotIdx] = {
              ...updated[slotIdx],
              state: 'flashing',
              boardIp: ip,
              boardData: newModules[ip],
            };
          }
        }

        // Update boardData for all assigned slots from latest modules
        const slotsToTurnOff: number[] = [];
        for (let i = 0; i < updated.length; i++) {
          const slot = updated[i];
          if (slot.boardIp && newModules[slot.boardIp]) {
            const mod = newModules[slot.boardIp];
            const newState =
              mod.status === 'done' ? 'done' :
              mod.status === 'error' ? 'error' :
              (mod.status === 'flashing' || mod.status === 'waiting') ? 'flashing' :
              slot.state;

            // Detect transition from flashing → done/error → power OFF
            if (slot.state === 'flashing' && (newState === 'done' || newState === 'error')) {
              slotsToTurnOff.push(i + 1); // 1-based position
            }

            updated[i] = {
              ...slot,
              state: (slot.state === 'flashing' || slot.state === 'done' || slot.state === 'error') ? newState : slot.state,
              boardData: mod,
            };
          }
        }

        // Power OFF boards that finished flashing (done or error)
        for (const position of slotsToTurnOff) {
          socketRef.current?.emit('power_off_board', { position });
        }

        return updated;
      });
    }

    // Notify backend OUTSIDE the state updater to ensure it fires exactly once.
    for (const { slotIdx, ip } of assignments) {
      socketRef.current?.emit('board_position_assigned', {
        ip,
        position: slotIdx + 1,
      });
    }
  }, []);

  // ── Core action: process a barcode scan string ──
  const processScan = useCallback((raw: string) => {
    // 1️⃣ POS barcode: POS1…POS5
    const posMatch = raw.match(POS_RE);
    if (posMatch) {
      const posIdx = parseInt(posMatch[1], 10) - 1;
      setSlots(prev => {
        const slot = prev[posIdx];
        if (slot.state === 'done' || slot.state === 'error') {
          const clearedIps = new Set(slot.clearedIps);
          if (slot.boardIp) {
            clearedIps.add(slot.boardIp);
            assignedIpsRef.current.delete(slot.boardIp);
            socketRef.current?.emit('reset_board', { ip: slot.boardIp });
          }
          const updated = [...prev];
          updated[posIdx] = {
            state: 'awaiting_card',
            boardIp: null,
            boardData: null,
            scannedAt: Date.now(),
            expectedSerial: null,
            clearedIps,
          };
          return updated;
        }
        if (slot.state === 'empty') {
          const updated = [...prev];
          updated[posIdx] = {
            state: 'awaiting_card',
            boardIp: null,
            boardData: null,
            scannedAt: Date.now(),
            expectedSerial: null,
            clearedIps: new Set(),
          };
          return updated;
        }
        showFeedback(`⚠️ POS${posIdx + 1} est déjà en cours d'utilisation`);
        return prev;
      });
      return;
    }

    // 2️⃣ Card barcode: numeric, at least 8 digits — last 8 = serial
    if (CARD_BARCODE_RE.test(raw) && awaitingCardSlotRef.current >= 0) {
      const serial = raw.slice(-8);
      const idx = awaitingCardSlotRef.current;

      // Check if another slot already expects this serial
      const currentSlots = slotsRef.current;
      const duplicate = currentSlots.find(
        (s, i) => i !== idx && s.expectedSerial === serial &&
        (s.state === 'awaiting_boot' || s.state === 'flashing')
      );
      if (duplicate) {
        showFeedback(`⚠️ S/N ${serial} est déjà assigné à un autre slot`);
        return;
      }

      setSlots(prev => {
        const updated = [...prev];
        updated[idx] = {
          ...prev[idx],
          state: 'awaiting_boot',
          expectedSerial: serial,
          scannedAt: Date.now(),
        };
        return updated;
      });
      showFeedback(`✅ POS${idx + 1} — S/N ${serial} — mise sous tension automatique…`);

      // Trigger automatic power ON via Board Interface
      socketRef.current?.emit('power_on_board', { position: idx + 1 });

      // Check if board already available in modules
      const modules = modulesRef.current;
      for (const [ip, mod] of Object.entries(modules)) {
        if (mod.serial === serial && !assignedIpsRef.current.has(ip)) {
          assignedIpsRef.current.add(ip);
          setSlots(prev => {
            const updated = [...prev];
            if (updated[idx]?.state === 'awaiting_boot') {
              updated[idx] = {
                ...updated[idx],
                state: 'flashing',
                boardIp: ip,
                boardData: mod,
              };
            }
            return updated;
          });
          socketRef.current?.emit('board_position_assigned', { ip, position: idx + 1 });
          break;
        }
      }
      return;
    }

    if (raw !== '') {
      if (awaitingCardSlotRef.current >= 0) {
        showFeedback(`⚠️ Code-barres carte invalide : "${raw}"`);
      } else {
        showFeedback(`⚠️ Code non reconnu : "${raw}"`);
      }
    }
  }, [showFeedback]);

  // ── Handle barcode scan input — global keydown listener ─
  const awaitingCardSlotRef = useRef(awaitingCardSlot);
  awaitingCardSlotRef.current = awaitingCardSlot;
  const processScanRef = useRef(processScan);
  processScanRef.current = processScan;

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ignore keystrokes only in real text inputs
      const el = e.target as HTMLElement;
      const tag = el?.tagName;
      const isEditable = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el?.isContentEditable;
      if (isEditable) return;

      if (e.key === 'Enter') {
        e.preventDefault();
        e.stopPropagation();
        // Also blur the focused element to prevent button re-activation
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }

        const raw = scanBufferRef.current.trim().toUpperCase();
        scanBufferRef.current = '';
        if (scanTimerRef.current) { clearTimeout(scanTimerRef.current); scanTimerRef.current = null; }

        if (raw !== '') {
          // Barcode scan content (POS or card barcode)
          processScanRef.current(raw);
        }
        // Empty Enter is now ignored (no more "confirm insertion")
        return;
      }

      // Accumulate printable characters (barcode scanner or manual typing)
      if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
        scanBufferRef.current += e.key;
        // Auto-clear buffer after 500ms of inactivity (handles stale chars)
        if (scanTimerRef.current) clearTimeout(scanTimerRef.current);
        scanTimerRef.current = setTimeout(() => { scanBufferRef.current = ''; }, 500);
      }
    };

    // Use capture phase to intercept before buttons handle it
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, []);

  // ── Skip current awaiting_card slot ───────────
  const handleSkip = useCallback(() => {
    if (awaitingCardSlot < 0) return;
    setSlots(prev => {
      const updated = [...prev];
      updated[awaitingCardSlot] = createEmptySlot();
      return updated;
    });
    showFeedback(`POS${awaitingCardSlot + 1} ignorée`);
  }, [awaitingCardSlot, showFeedback]);

  // ── Stop scanning (clear all awaiting_card slots) ─
  const handleFinishPrep = useCallback(() => {
    setSlots(prev => prev.map(s =>
      s.state === 'awaiting_card' ? createEmptySlot() : s
    ));
    showFeedback('Préparation terminée');
  }, [showFeedback]);

  // Count active (non-empty) slots
  const activeCount = slots.filter(s => s.state !== 'empty').length;
  const hasAwaitingCard = awaitingCardSlot >= 0;
  const hasAwaitingBoot = slots.some(s => s.state === 'awaiting_boot');

  return (
    <div className="dashboard">

      {/* Header */}
      <header className="dashboard__header">
        <div className="dashboard__title-group">
          <div className="dashboard__logo">
            <img src="/images.png" alt="Toradex" height="32" />
          </div>
          <div>
            <h1 className="dashboard__title">Verdin AM62 — Banc de Flashage</h1>
            <p className="dashboard__subtitle">
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
          {/* Action buttons for scan workflow */}
          {hasAwaitingCard && (
            <button
              className="dashboard__console-btn dashboard__skip-btn"
              onClick={handleSkip}
              title={`Passer POS${awaitingCardSlot + 1}`}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M4 3l8 5-8 5V3z" fill="currentColor"/>
                <path d="M13 3v10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              Passer
            </button>
          )}
          {activeCount > 0 && hasAwaitingCard && (
            <button
              className="dashboard__console-btn"
              onClick={handleFinishPrep}
              title="Terminer la préparation"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M2 2l12 12M14 2L2 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              Terminer
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
            <span className={`dashboard__db-dot dashboard__db-dot--${servicesStatus.db_connection}`} />
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
            <span
              className={`dashboard__db-dot dashboard__db-dot--${boardInterfaceConnected ? 'connected' : 'disconnected'}`}
              title={`Board Interface — ${boardInterfaceConnected ? 'connectée' : 'déconnectée'}`}
            />
          </button>

          <div className={`dashboard__conn dashboard__conn--${connectionStatus}`}>
            <span className="dashboard__conn-dot" />
            <span className="dashboard__conn-label">
              {connectionStatus === 'connected'
                ? 'Connecté'
                : connectionStatus === 'connecting'
                ? 'Connexion...'
                : 'Déconnecté'}
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

      {/* Scan instruction bar */}
      <div className={`scan-bar ${hasAwaitingCard ? 'scan-bar--action' : ''} ${hasAwaitingBoot ? 'scan-bar--power' : ''}`}>
        <div className="scan-bar__instruction">
          {hasAwaitingCard ? (
            <>
              <span className="scan-bar__icon scan-bar__icon--insert">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <rect x="2" y="4" width="6" height="16" rx="1" fill="currentColor" opacity="0.7"/>
                  <rect x="9" y="4" width="3" height="16" rx="0.5" fill="currentColor" opacity="0.5"/>
                  <rect x="13" y="4" width="6" height="16" rx="1" fill="currentColor" opacity="0.7"/>
                  <rect x="20" y="4" width="2" height="16" rx="0.5" fill="currentColor" opacity="0.5"/>
                </svg>
              </span>
              Scannez le <strong>code-barres de la carte</strong> pour <strong>POS{awaitingCardSlot + 1}</strong>
            </>
          ) : hasAwaitingBoot ? (
            <>
              <span className="scan-bar__icon scan-bar__icon--power">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2v6" />
                  <path d="M6.34 6.34a8 8 0 1 0 11.32 0" />
                </svg>
              </span>
              Mise sous tension automatique — en attente de démarrage des cartes
            </>
          ) : (
            <>
              <span className="scan-bar__icon">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                  <rect x="2" y="4" width="6" height="16" rx="1" fill="currentColor" opacity="0.7"/>
                  <rect x="9" y="4" width="3" height="16" rx="0.5" fill="currentColor" opacity="0.5"/>
                  <rect x="13" y="4" width="6" height="16" rx="1" fill="currentColor" opacity="0.7"/>
                  <rect x="20" y="4" width="2" height="16" rx="0.5" fill="currentColor" opacity="0.5"/>
                </svg>
              </span>
              Scannez le code-barres d'une position (POS1 à POS5)
            </>
          )}
        </div>
        {scanFeedback && (
          <div className="scan-bar__feedback">{scanFeedback}</div>
        )}
      </div>

      {/* 5 Position Slots */}
      <main className="dashboard__content">
        <div className="position-grid">
          {slots.map((slot, idx) => (
            <PositionSlot
              key={idx}
              position={idx + 1}
              slot={slot}
              wsPort={vncWsPort}
              isActiveTarget={idx === awaitingCardSlot}
              boardInterfaceConnected={boardInterfaceConnected}
              onRetryPower={() => socketRef.current?.emit('power_on_board', { position: idx + 1 })}
            />
          ))}
        </div>
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
        boardInterfaceConnected={boardInterfaceConnected}
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
