import { useEffect, useState } from 'react';
import type { BoardModule } from '../types/board';

const STATUS_LABEL: Record<string, string> = {
  waiting: 'En attente',
  flashing: 'Flashage en cours',
  done: 'Terminé',
  error: 'Erreur',
};

interface Props {
  ip: string;
  data: BoardModule;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m}m ${s.toString().padStart(2, '0')}s` : `${s}s`;
}

function formatStartTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export default function BoardCard({ ip, data }: Props) {
  const { serial, status, startTime } = data;
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (status === 'done' || status === 'waiting' || !startTime) return;
    const interval = setInterval(() => {
      setElapsed(Math.floor(Date.now() / 1000 - startTime));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime, status]);

  useEffect(() => {
    if (startTime) {
      setElapsed(Math.floor(Date.now() / 1000 - startTime));
    }
  }, [startTime]);

  return (
    <div className={`board-card board-card--${status}`}>
      <div className="board-card__header">
        <div className="board-card__serial-group">
          <span className="board-card__serial-label">N° de série</span>
          <span className="board-card__serial">{serial}</span>
        </div>
        <span className={`board-card__badge board-card__badge--${status}`}>
          {STATUS_LABEL[status] ?? status}
        </span>
      </div>

      <div className="board-card__meta">
        <div className="board-card__meta-item">
          <span className="board-card__label">IP (DHCP)</span>
          <span className="board-card__value">{ip}</span>
        </div>
        <div className="board-card__meta-item">
          <span className="board-card__label">Heure de début</span>
          <span className="board-card__value">
            {startTime ? formatStartTime(startTime) : '—'}
          </span>
        </div>
        <div className="board-card__meta-item">
          <span className="board-card__label">Temps écoulé</span>
          <span className="board-card__value">
            {status !== 'waiting' && startTime ? formatTime(elapsed) : '—'}
          </span>
        </div>
      </div>
    </div>
  );
}
