import { useEffect, useRef, useState } from 'react';
import RFB from 'novnc/core/rfb.js';
import type { BoardStatus } from '../types/board';

type VncStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

/** Max number of automatic reconnection attempts */
const MAX_RETRIES = 30;
/** Delay between reconnection attempts (ms) */
const RETRY_DELAY = 3_000;
/**
 * Per-attempt connection timeout (ms).
 * If neither 'connect' nor 'disconnect' fires within this window,
 * the attempt is torn down and a retry is scheduled.
 */
const CONNECT_TIMEOUT = 10_000;

interface Props {
  ip: string;
  serial: string;
  wsPort: number;
  startTime: number | null;
  boardStatus: BoardStatus;
  errorMessage: string | null;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`;
}

/**
 * Embeds a noVNC viewer that connects to a board's Tezi VNC server
 * through the websockify proxy.
 *
 * Automatically retries on connection failure (the VNC server may not
 * be ready yet when the board has just booted).
 *
 * The connection is stopped automatically when the board reaches a
 * terminal state (done / error) to avoid pointless retry noise.
 */
export default function VncViewer({ ip, serial, wsPort, startTime, boardStatus, errorMessage }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retriesRef = useRef(0);
  const mountedRef = useRef(true);
  /** True once at least one successful VNC connection was made this lifecycle. */
  const connectedOnceRef = useRef(false);

  const [status, setStatus] = useState<VncStatus>('connecting');
  const [retryCount, setRetryCount] = useState(0);
  const [elapsed, setElapsed] = useState(0);

  // Keep boardStatus accessible inside non-React callbacks (timers, RFB events)
  const boardStatusRef = useRef(boardStatus);
  boardStatusRef.current = boardStatus;

  // ── Elapsed flash time counter ──────────────────
  useEffect(() => {
    if (!startTime || boardStatus === 'waiting') {
      setElapsed(0);
      return;
    }
    setElapsed(Math.floor(Date.now() / 1000 - startTime));
    if (boardStatus === 'done' || boardStatus === 'error') return;
    const interval = setInterval(() => {
      setElapsed(Math.floor(Date.now() / 1000 - startTime));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime, boardStatus]);

  // ── Stop retries once board reaches terminal state ──
  useEffect(() => {
    if (boardStatus !== 'done' && boardStatus !== 'error') return;

    // Cancel any pending retry / connection-timeout timers
    if (retryTimerRef.current) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
    if (connectTimeoutRef.current) {
      clearTimeout(connectTimeoutRef.current);
      connectTimeoutRef.current = null;
    }

    // If VNC was never connected, switch to a silent 'disconnected' status
    // so the header no longer shows a misleading "Connexion VNC… (tentative N)".
    if (!connectedOnceRef.current) {
      setStatus('disconnected');
    }
  }, [boardStatus]);

  // ── Main VNC connection effect ──────────────────
  useEffect(() => {
    mountedRef.current = true;
    retriesRef.current = 0;
    connectedOnceRef.current = false;
    setRetryCount(0);

    const el = containerRef.current;
    if (!el) return;

    const wsHost = window.location.hostname || 'localhost';
    const wsUrl = `ws://${wsHost}:${wsPort}/?token=${ip}`;

    /** Safely tear down the current RFB instance and clear timers. */
    function cleanupRfb() {
      if (connectTimeoutRef.current) {
        clearTimeout(connectTimeoutRef.current);
        connectTimeoutRef.current = null;
      }
      // Null the ref *before* calling disconnect so that the disconnect
      // event handler (which checks rfbRef.current === rfb) becomes a no-op.
      const rfb = rfbRef.current;
      rfbRef.current = null;
      try { rfb?.disconnect(); } catch { /* already gone */ }
    }

    function connect() {
      if (!mountedRef.current || !el) return;

      // Don't attempt if the board has already finished
      const bs = boardStatusRef.current;
      if (bs === 'done' || bs === 'error') return;

      // Tear down the previous attempt cleanly
      cleanupRfb();

      // Clear previous children (noVNC injects canvas elements)
      while (el.firstChild) el.removeChild(el.firstChild);

      setStatus('connecting');

      let rfb: RFB;
      try {
        rfb = new RFB(el, wsUrl);
      } catch {
        scheduleRetry();
        return;
      }

      rfb.scaleViewport = true;
      rfb.resizeSession = false;
      rfb.viewOnly = true;
      rfb.focusOnClick = false;
      rfb.background = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#101316';

      // Safety net: if the RFB instance neither connects nor disconnects
      // within CONNECT_TIMEOUT ms, force-tear it down and retry.
      connectTimeoutRef.current = setTimeout(() => {
        if (!mountedRef.current) return;
        // Only act if this rfb is still the current one
        if (rfbRef.current !== rfb) return;
        cleanupRfb();
        scheduleRetry();
      }, CONNECT_TIMEOUT);

      rfb.addEventListener('connect', () => {
        if (!mountedRef.current || rfbRef.current !== rfb) return;
        if (connectTimeoutRef.current) {
          clearTimeout(connectTimeoutRef.current);
          connectTimeoutRef.current = null;
        }
        retriesRef.current = 0;
        connectedOnceRef.current = true;
        setRetryCount(0);
        setStatus('connected');
      });

      rfb.addEventListener('disconnect', () => {
        if (!mountedRef.current || rfbRef.current !== rfb) return;
        if (connectTimeoutRef.current) {
          clearTimeout(connectTimeoutRef.current);
          connectTimeoutRef.current = null;
        }
        // Always retry on *any* disconnect (clean or unclean).
        // A clean disconnect typically means the VNC server closed
        // the connection (e.g. board rebooting) — we still want to
        // attempt reconnection unless the board has finished.
        scheduleRetry();
      });

      rfbRef.current = rfb;
    }

    function scheduleRetry() {
      if (!mountedRef.current) return;

      // If the board has already finished, don't retry
      const bs = boardStatusRef.current;
      if (bs === 'done' || bs === 'error') {
        if (!connectedOnceRef.current) {
          setStatus('disconnected');
        }
        return;
      }

      if (retriesRef.current >= MAX_RETRIES) {
        setStatus('error');
        return;
      }
      retriesRef.current += 1;
      setRetryCount(retriesRef.current);
      setStatus('connecting');
      retryTimerRef.current = setTimeout(connect, RETRY_DELAY);
    }

    connect();

    return () => {
      mountedRef.current = false;
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      cleanupRfb();
    };
  }, [ip, wsPort]);

  const statusLabels: Record<VncStatus, string> = {
    connecting: retryCount > 0 ? `Connexion VNC… (tentative ${retryCount})` : 'Connexion VNC…',
    connected: 'VNC connecté',
    disconnected: 'VNC déconnecté',
    error: 'Erreur VNC',
  };

  const viewerClass = [
    'vnc-viewer',
    boardStatus === 'done' ? 'vnc-viewer--done' : '',
    boardStatus === 'error' ? 'vnc-viewer--error' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={viewerClass}>
      <div className="vnc-viewer__header">
        <div className="vnc-viewer__info">
          <span className="vnc-viewer__serial">{serial}</span>
          <span className="vnc-viewer__ip">{ip}</span>
        </div>
        {startTime && boardStatus !== 'waiting' && (
          <span className="vnc-viewer__timer">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
              <circle cx="8" cy="9" r="6" stroke="currentColor" strokeWidth="1.3" />
              <path d="M8 6v3.5l2.5 1.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M6.5 1.5h3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
            </svg>
            {formatElapsed(elapsed)}
          </span>
        )}
        <span className={`vnc-viewer__status vnc-viewer__status--${status}`}>
          <span className="vnc-viewer__status-dot" />
          {statusLabels[status]}
        </span>
      </div>
      <div className="vnc-viewer__canvas-wrapper">
        <div className="vnc-viewer__canvas" ref={containerRef} />
        {boardStatus === 'done' && (
          <div className="vnc-viewer__done-overlay">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="2.5" />
              <path d="M14 24l7 7 13-13" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="vnc-viewer__done-label">Flashage Terminé</span>
            <span className="vnc-viewer__done-time">{formatElapsed(elapsed)}</span>
          </div>
        )}
        {boardStatus === 'error' && (
          <div className="vnc-viewer__error-overlay">
            <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
              <circle cx="24" cy="24" r="22" stroke="currentColor" strokeWidth="2.5" />
              <path d="M16 16l16 16M32 16L16 32" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            </svg>
            <span className="vnc-viewer__error-label">Erreur de Programmation</span>
            {errorMessage && (
              <span className="vnc-viewer__error-detail">{errorMessage}</span>
            )}
            {startTime && (
              <span className="vnc-viewer__error-time">{formatElapsed(elapsed)}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
