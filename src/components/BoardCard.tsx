import { useEffect, useState } from 'react';
import type { BoardModule } from '../types/board';

const STEP_LABELS: Record<string, string> = {
  'bootfs.tar.xz': 'Boot FS',
  '.tar.xz HTTP': 'Root FS',
  tiboot3: 'TI Boot3',
  tispl: 'TI SPL',
  'u-boot.img': 'U-Boot',
};

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
  const { serial, progress, status, currentStep, startTime } = data;
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

  const stepLabel = currentStep ? (STEP_LABELS[currentStep] ?? currentStep) : '—';
  const clampedProgress = Math.min(100, Math.max(0, progress));

  return (
    <div className={`board-card board-card--${status}`}>
      <div className="board-card__header">
        <span className="board-card__serial">{serial}</span>
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
          <span className="board-card__label">Étape courante</span>
          <span className="board-card__value board-card__value--step">{stepLabel}</span>
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

      <div className="board-card__progress-section">
        <div className="board-card__progress-header">
          <span className="board-card__label">Progression</span>
          <span className={`board-card__percent board-card__percent--${status}`}>
            {clampedProgress}%
          </span>
        </div>
        <div className="board-card__progress-track">
          <div
            className={`board-card__progress-fill board-card__progress-fill--${status}`}
            style={{ width: `${clampedProgress}%` }}
          />
        </div>
        {status === 'flashing' && (
          <div className="board-card__steps">
            {Object.entries(STEP_LABELS).map(([key, label]) => {
              const isDone = currentStep
                ? Object.keys(STEP_LABELS).indexOf(key) <
                  Object.keys(STEP_LABELS).indexOf(currentStep)
                : false;
              const isActive = key === currentStep;
              return (
                <span
                  key={key}
                  className={`board-card__step-chip ${isDone ? 'done' : ''} ${isActive ? 'active' : ''}`}
                >
                  {label}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
