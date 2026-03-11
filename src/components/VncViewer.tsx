import { useEffect, useRef, useState } from 'react';
import RFB from 'novnc/core/rfb.js';

type VncStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface Props {
  ip: string;
  serial: string;
  wsPort: number;
}

/**
 * Embeds a noVNC viewer that connects to a board's Tezi VNC server
 * through the websockify proxy.
 */
export default function VncViewer({ ip, serial, wsPort }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFB | null>(null);
  const [status, setStatus] = useState<VncStatus>('connecting');

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

  return (
    <div className="vnc-viewer">
      <div className="vnc-viewer__header">
        <div className="vnc-viewer__info">
          <span className="vnc-viewer__serial">{serial}</span>
          <span className="vnc-viewer__ip">{ip}</span>
        </div>
        <span className={`vnc-viewer__status vnc-viewer__status--${status}`}>
          <span className="vnc-viewer__status-dot" />
          {statusLabels[status]}
        </span>
      </div>
      <div className="vnc-viewer__canvas" ref={containerRef} />
    </div>
  );
}
