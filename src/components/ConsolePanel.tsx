import { useEffect, useRef, useState } from 'react';
import type { Socket } from 'socket.io-client';

export interface LogEntry {
  ts: number;
  level: 'debug' | 'info' | 'warning' | 'error' | 'critical';
  message: string;
}

interface Props {
  socket: Socket | null;
  open: boolean;
  onClose: () => void;
}

function formatTs(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString('fr-FR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export default function ConsolePanel({ socket, open, onClose }: Props) {
  const [lines, setLines] = useState<LogEntry[]>([]);
  const [filter, setFilter] = useState<string>('');
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!socket) return;

    const onHistory = (history: LogEntry[]) => {
      setLines(history);
    };

    const onLine = (entry: LogEntry) => {
      setLines(prev => {
        const next = [...prev, entry];
        return next.length > 500 ? next.slice(next.length - 500) : next;
      });
    };

    socket.on('log_history', onHistory);
    socket.on('log_line', onLine);

    return () => {
      socket.off('log_history', onHistory);
      socket.off('log_line', onLine);
    };
  }, [socket]);

  // Auto-scroll when new lines arrive
  useEffect(() => {
    if (autoScroll && open) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [lines, autoScroll, open]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  };

  const filteredLines = filter
    ? lines.filter(l =>
        l.message.toLowerCase().includes(filter.toLowerCase()) ||
        l.level.includes(filter.toLowerCase())
      )
    : lines;

  const handleClear = () => setLines([]);

  return (
    <>
      {/* Overlay */}
      <div
        className={`console-overlay ${open ? 'console-overlay--visible' : ''}`}
        onClick={onClose}
      />

      {/* Panel */}
      <aside className={`console-panel ${open ? 'console-panel--open' : ''}`}>
        {/* Panel header */}
        <div className="console-panel__header">
          <div className="console-panel__title-row">
            <span className="console-panel__icon">&#9654;</span>
            <span className="console-panel__title">Console — FlashBench Monitor</span>
            <div className="console-panel__dot console-panel__dot--green" />
          </div>
          <div className="console-panel__toolbar">
            <input
              className="console-panel__filter"
              placeholder="Filtrer les logs…"
              value={filter}
              onChange={e => setFilter(e.target.value)}
            />
            <button
              className="console-panel__btn"
              onClick={handleClear}
              title="Effacer la console"
            >
              ⌫ Effacer
            </button>
            <button
              className={`console-panel__btn console-panel__btn--scroll ${autoScroll ? 'active' : ''}`}
              onClick={() => {
                setAutoScroll(true);
                bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
              }}
              title="Défiler automatiquement"
            >
              ↓ Auto
            </button>
            <button
              className="console-panel__btn console-panel__btn--close"
              onClick={onClose}
              title="Fermer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Log lines */}
        <div
          className="console-panel__body"
          ref={scrollRef}
          onScroll={handleScroll}
        >
          {filteredLines.length === 0 ? (
            <div className="console-panel__empty">
              {filter ? 'Aucun résultat pour ce filtre.' : 'En attente de logs…'}
            </div>
          ) : (
            filteredLines.map((entry, i) => (
              <div key={i} className={`console-line console-line--${entry.level}`}>
                <span className="console-line__ts">{formatTs(entry.ts)}</span>
                <span className={`console-line__level console-line__level--${entry.level}`}>
                  {entry.level.toUpperCase().padEnd(8)}
                </span>
                <span className="console-line__msg">{entry.message}</span>
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>

        {/* Status bar */}
        <div className="console-panel__footer">
          <span>{filteredLines.length} ligne{filteredLines.length !== 1 ? 's' : ''}</span>
          {filter && <span>· filtre actif : <em>{filter}</em></span>}
          {!autoScroll && (
            <span className="console-panel__footer-warn">· défilement manuel</span>
          )}
        </div>
      </aside>
    </>
  );
}
