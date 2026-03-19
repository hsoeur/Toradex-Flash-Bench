import { useEffect, useRef, useState } from 'react';
import RFB from 'novnc/core/rfb.js';
import type { BoardStatus } from '../types/board';

type VncStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

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
 */
export default function VncViewer({ ip, serial, wsPort, startTime, boardStatus, errorMessage }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const [status, setStatus] = useState<VncStatus>('connecting');
  const [elapsed, setElapsed] = useState(0);

  // Elapsed flash time counter
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

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Derive websockify host from current page location
    const wsHost = window.location.hostname || 'localhost';
    const wsUrl = `ws://${wsHost}:${wsPort}/?token=${ip}`;

    setStatus('connecting');

    let rfb: RFB;
    try {
      rfb = new RFB(el, wsUrl);
    } catch {
      setStatus('error');
      return;
    }

    rfb.scaleViewport = true;
    rfb.resizeSession = false;
    rfb.viewOnly = true;        // read-only — just monitoring
    rfb.focusOnClick = false;
    rfb.background = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#101316';

    rfb.addEventListener('connect', () => {
      setStatus('connected');
    });

    rfb.addEventListener('disconnect', (e) => {
      setStatus(e.detail.clean ? 'disconnected' : 'error');
    });

    rfbRef.current = rfb;

    return () => {
      try {
        rfb.disconnect();
      } catch {
        // already disconnected
      }
      rfbRef.current = null;
    };
  }, [ip, wsPort]);

  const statusLabels: Record<VncStatus, string> = {
    connecting: 'Connexion VNC…',
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
