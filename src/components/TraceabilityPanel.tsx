import { useEffect, useState, useCallback } from 'react';

const API_URL = 'http://localhost:8000';

interface ProgrammedBoard {
  Id: number;
  SerialNumber: string;
  ProductId: string;
  BoardRevision: string;
  FactoryMac: string;
  ClientMac: string;
  ProductionOrder: string;
  OperatorId: string;
  ImageFolder: string;
  IpBeforeReboot: string;
  ProgrammingStatus: string;
  ProgrammedAt: string;
}

interface TodayResponse {
  date: string;
  count: number;
  boards: ProgrammedBoard[];
}

interface Props {
  open: boolean;
  onClose: () => void;
}

function formatTime(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleTimeString('fr-FR', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return dateStr;
  }
}

export default function TraceabilityPanel({ open, onClose }: Props) {
  const [data, setData] = useState<TodayResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const fetchBoards = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/programmed-boards/today`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json: TodayResponse = await res.json();
      setData(json);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur inconnue');
    } finally {
      setLoading(false);
    }
  }, []);

  // Fetch when panel opens
  useEffect(() => {
    if (open) fetchBoards();
  }, [open, fetchBoards]);

  const filtered = data?.boards.filter(b => {
    if (!filter) return true;
    const q = filter.toLowerCase();
    return (
      b.SerialNumber.toLowerCase().includes(q) ||
      b.ClientMac.toLowerCase().includes(q) ||
      b.ProductionOrder.toLowerCase().includes(q) ||
      b.OperatorId.toLowerCase().includes(q) ||
      b.ProgrammingStatus.toLowerCase().includes(q)
    );
  }) ?? [];

  return (
    <>
      {/* Backdrop */}
      <div
        className={`svc-overlay ${open ? 'svc-overlay--visible' : ''}`}
        onClick={onClose}
      />

      {/* Right-side panel */}
      <aside className={`trace-panel ${open ? 'trace-panel--open' : ''}`}>

        {/* Header */}
        <div className="svc-panel__header">
          <div className="svc-panel__title-row">
            <span className="svc-panel__title">Traçabilité du jour</span>
            {data && (
              <span className="trace-panel__badge">
                {data.count} carte{data.count > 1 ? 's' : ''} — {data.date}
              </span>
            )}
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button
              className="console-panel__btn"
              onClick={fetchBoards}
              disabled={loading}
              title="Rafraîchir"
            >
              <svg
                width="14" height="14" viewBox="0 0 16 16" fill="none"
                style={{ transform: loading ? 'rotate(360deg)' : 'none', transition: loading ? 'transform 0.8s linear' : 'none' }}
              >
                <path
                  d="M13.65 2.35A8 8 0 1 0 15 8h-2a6 6 0 1 1-1.05-3.39L10 6h5V1l-1.35 1.35z"
                  fill="currentColor"
                />
              </svg>
            </button>
            <button className="console-panel__btn console-panel__btn--close" onClick={onClose}>✕</button>
          </div>
        </div>

        {/* Filter bar */}
        <div className="trace-panel__toolbar">
          <input
            className="console-panel__filter"
            type="text"
            placeholder="Filtrer (SN, MAC, OF, opérateur…)"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>

        {/* Content */}
        <div className="trace-panel__content">
          {loading && (
            <div className="trace-panel__state">Chargement…</div>
          )}

          {!loading && error && (
            <div className="trace-panel__state trace-panel__state--error">
              Erreur : {error}
            </div>
          )}

          {!loading && !error && filtered.length === 0 && (
            <div className="trace-panel__state">
              {filter ? 'Aucun résultat pour ce filtre.' : 'Aucune carte flashée aujourd\'hui.'}
            </div>
          )}

          {!loading && !error && filtered.length > 0 && (
            <table className="trace-table">
              <thead>
                <tr>
                  <th>Heure</th>
                  <th>N° Série</th>
                  <th>Produit</th>
                  <th>OF</th>
                  <th>Opérateur</th>
                  <th>MAC Client</th>
                  <th>Statut</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map(b => (
                  <tr key={b.Id}>
                    <td className="trace-table__time">{formatTime(b.ProgrammedAt)}</td>
                    <td className="trace-table__mono">{b.SerialNumber}</td>
                    <td>{b.ProductId} <span className="trace-table__rev">r{b.BoardRevision}</span></td>
                    <td>{b.ProductionOrder}</td>
                    <td>{b.OperatorId}</td>
                    <td className="trace-table__mono">{b.ClientMac}</td>
                    <td>
                      <span className={`trace-badge trace-badge--${b.ProgrammingStatus.toLowerCase()}`}>
                        {b.ProgrammingStatus}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </aside>
    </>
  );
}
