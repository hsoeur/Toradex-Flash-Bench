import type { PositionSlot as PositionSlotType } from '../types/board';
import VncViewer from './VncViewer';

interface Props {
  position: number;        // 1-5
  slot: PositionSlotType;
  wsPort: number;
  isActiveTarget: boolean; // This slot is waiting for Enter confirmation
}

export default function PositionSlot({ position, slot, wsPort, isActiveTarget }: Props) {
  const label = `POS${position}`;

  const slotClass = [
    'pos-slot',
    `pos-slot--${slot.state}`,
    isActiveTarget ? 'pos-slot--active-target' : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={slotClass}>
      {/* Position badge — always visible */}
      <div className={`pos-slot__badge pos-slot__badge--${slot.state}`}>
        {label}
      </div>

      {/* Content depends on state */}
      {slot.state === 'empty' && (
        <div className="pos-slot__body pos-slot__body--centered">
          <svg className="pos-slot__icon" width="48" height="48" viewBox="0 0 48 48" fill="none" opacity="0.35">
            <rect x="6" y="10" width="36" height="28" rx="3" stroke="currentColor" strokeWidth="2" strokeDasharray="4 3" />
            <path d="M18 24h12M24 18v12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          <p className="pos-slot__message pos-slot__message--muted">
            Scannez <strong>{label}</strong>
          </p>
        </div>
      )}

      {slot.state === 'awaiting_card' && (
        <div className="pos-slot__body pos-slot__body--centered">
          <div className="pos-slot__insert-anim">
            <svg width="56" height="56" viewBox="0 0 56 56" fill="none">
              <rect x="12" y="8" width="32" height="20" rx="3" stroke="currentColor" strokeWidth="2" />
              <path
                className="pos-slot__arrow-down"
                d="M28 32v16M22 42l6 6 6-6"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <p className="pos-slot__message pos-slot__message--action">
            Insérez la carte dans <strong>{label}</strong>
          </p>
          <p className="pos-slot__message pos-slot__message--hint">
            puis appuyez sur <kbd>Entrée</kbd>
          </p>
        </div>
      )}

      {slot.state === 'awaiting_boot' && (
        <div className="pos-slot__body pos-slot__body--centered">
          <div className="pos-slot__power-icon">
            <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2v6" />
              <path d="M6.34 6.34a8 8 0 1 0 11.32 0" />
            </svg>
          </div>
          <p className="pos-slot__message pos-slot__message--power">
            Lancez manuellement l'alimentation
          </p>
          <p className="pos-slot__message pos-slot__message--hint">
            Appuyez sur le bouton d'alimentation de <strong>{label}</strong>
          </p>
          <div className="pos-slot__waiting-dot" />
        </div>
      )}

      {(slot.state === 'flashing' || slot.state === 'done' || slot.state === 'error') && slot.boardIp && slot.boardData && (
        <div className="pos-slot__body pos-slot__body--vnc">
          {/* Progress bar */}
          {slot.state === 'flashing' && slot.boardData.status !== 'waiting' && (
            <div className="pos-slot__progress">
              <div className="pos-slot__progress-track">
                <div
                  className="pos-slot__progress-fill"
                  style={{ width: `${slot.boardData.progress}%` }}
                />
              </div>
              <span className="pos-slot__progress-pct">{slot.boardData.progress}%</span>
            </div>
          )}

          {/* Show a "waiting for Tezi" message when card is detected but not yet flashing */}
          {slot.state === 'flashing' && slot.boardData.status === 'waiting' ? (
            <div className="pos-slot__body pos-slot__body--centered">
              <div className="pos-slot__spinner" />
              <p className="pos-slot__message pos-slot__message--info">
                Carte détectée sur {label}
              </p>
              <p className="pos-slot__message pos-slot__message--hint">
                Démarrage de Tezi en cours…
              </p>
              <p className="pos-slot__message pos-slot__message--muted" style={{ fontSize: '0.75rem' }}>
                {slot.boardData.serial} — {slot.boardIp}
              </p>
            </div>
          ) : (
            <div className="pos-slot__vnc-container">
              <VncViewer
                ip={slot.boardIp}
                serial={slot.boardData.serial}
                wsPort={wsPort}
                startTime={slot.boardData.startTime}
                boardStatus={slot.boardData.status}
                errorMessage={slot.boardData.errorMessage ?? null}
              />
            </div>
          )}

          {/* Re-scan hint below the VNC viewer */}
          {(slot.state === 'done' || slot.state === 'error') && (
            <div className={`pos-slot__rescan-hint pos-slot__rescan-hint--${slot.state}`}>
              Re-scannez <strong>{label}</strong> pour un nouveau cycle
            </div>
          )}
        </div>
      )}
    </div>
  );
}
