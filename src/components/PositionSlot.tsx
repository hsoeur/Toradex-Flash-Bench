import type { PositionSlot as PositionSlotType } from '../types/board';
import VncViewer from './VncViewer';

interface Props {
  position: number;        // 1-5
  slot: PositionSlotType;
  wsPort: number;
  isActiveTarget: boolean; // This slot is waiting for Enter confirmation
  boardInterfaceConnected: boolean;
  onRetryPower: () => void;
}

export default function PositionSlot({ position, slot, wsPort, isActiveTarget, boardInterfaceConnected, onRetryPower }: Props) {
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
              <rect x="8" y="14" width="40" height="8" rx="2" stroke="currentColor" strokeWidth="2" />
              <rect x="14" y="26" width="28" height="4" rx="1" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
              <rect x="14" y="33" width="20" height="4" rx="1" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2" />
              <path
                className="pos-slot__arrow-down"
                d="M28 42v8M24 47l4 4 4-4"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <p className="pos-slot__message pos-slot__message--action">
            Insérez la carte puis scannez son <strong>code-barres</strong>
          </p>
          <p className="pos-slot__message pos-slot__message--hint">
            pour <strong>{label}</strong>
          </p>
        </div>
      )}

      {slot.state === 'awaiting_boot' && (
        <div className="pos-slot__body pos-slot__body--centered">
          <div className="pos-slot__power-icon pos-slot__power-icon--auto">
            <svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2v6" />
              <path d="M6.34 6.34a8 8 0 1 0 11.32 0" />
            </svg>
          </div>
          {slot.expectedSerial && (
            <p className="pos-slot__serial-badge">
              S/N {slot.expectedSerial}
            </p>
          )}
          <p className="pos-slot__message pos-slot__message--power">
            Mise sous tension automatique…
          </p>
          <p className="pos-slot__message pos-slot__message--hint">
            En attente du démarrage de la carte <strong>{label}</strong>
          </p>
          {!boardInterfaceConnected && (
            <button
              className="pos-slot__retry-btn"
              onClick={(e) => { e.stopPropagation(); onRetryPower(); }}
              title="Réessayer la mise sous tension"
            >
              ↻ Réessayer alimentation
            </button>
          )}
          <div className="pos-slot__waiting-dot" />
        </div>
      )}

      {(slot.state === 'flashing' || slot.state === 'done' || slot.state === 'error') && slot.boardIp && slot.boardData && (
        <div className="pos-slot__body pos-slot__body--vnc">

          {/* Always show VNC viewer as soon as the board is detected */}
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

          {/* Re-scan hint below the VNC viewer */}
          {(slot.state === 'done' || slot.state === 'error') && (
            <div className={`pos-slot__rescan-hint pos-slot__rescan-hint--${slot.state}`}>
              Eteindre puis Re-scannez <strong>{label}</strong> pour un nouveau cycle
            </div>
          )}
        </div>
      )}
    </div>
  );
}
