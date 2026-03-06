import { useEffect, useState, useCallback } from 'react';
import type { Socket } from 'socket.io-client';

// ──────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────

export interface TeziImage {
  path:         string;
  folder:       string;
  name:         string;
  description:  string;
  version:      string;
  release_date: string;
  autoinstall:  boolean;
}

interface Props {
  socket: Socket | null;
  open: boolean;
  onClose: () => void;
}

const BACKEND_URL = 'http://localhost:5001';

// ──────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────

export default function ImageSelectorPanel({ socket, open, onClose }: Props) {
  const [images, setImages] = useState<TeziImage[]>([]);
  const [switching, setSwitching] = useState<string | null>(null);

  // ─── Fetch images on mount & listen for socket updates ───
  const fetchImages = useCallback(async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/images`);
      const data = await res.json();
      if (data.images) setImages(data.images);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    fetchImages();
  }, [fetchImages]);

  useEffect(() => {
    if (!socket) return;
    const handler = (data: { images: TeziImage[] }) => {
      if (data.images) setImages(data.images);
    };
    socket.on('images_update', handler);
    return () => { socket.off('images_update', handler); };
  }, [socket]);

  // ─── Switch autoinstall ───
  const handleSelect = async (path: string) => {
    setSwitching(path);
    try {
      await fetch(`${BACKEND_URL}/api/images/autoinstall`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      });
      // Optimistic local update
      setImages(prev =>
        prev.map(img => ({ ...img, autoinstall: img.path === path })),
      );
    } catch {
      // ignore, will be updated by socket
    } finally {
      setSwitching(null);
    }
  };

  const activeImage = images.find(img => img.autoinstall);

  return (
    <>
      {/* Overlay */}
      <div
        className={`svc-overlay ${open ? 'svc-overlay--visible' : ''}`}
        onClick={onClose}
      />

      {/* Panel */}
      <div className={`img-panel ${open ? 'img-panel--open' : ''}`}>
        {/* Header */}
        <div className="img-panel__header">
          <div className="img-panel__title-row">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <rect x="1" y="3" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.3" />
              <path d="M4 7h8M4 10h5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
              <circle cx="12" cy="10" r="1.5" fill="currentColor" />
            </svg>
            <span className="img-panel__title">Sélection de l'image</span>
          </div>
          {activeImage && (
            <span className="img-panel__active-badge">
              <span className="img-panel__active-dot" />
              {activeImage.folder}
            </span>
          )}
          <button className="console-panel__btn console-panel__btn--close" onClick={onClose}>
            ✕
          </button>
        </div>

        {/* Image list */}
        <div className="img-panel__list">
          {images.length === 0 ? (
            <div className="img-panel__empty">
              Aucune image trouvée dans image_list.json
            </div>
          ) : (
            images.map(img => {
              const isActive = img.autoinstall;
              const isSwitching = switching === img.path;
              return (
                <div
                  key={img.path}
                  className={`img-card ${isActive ? 'img-card--active' : ''} ${isSwitching ? 'img-card--switching' : ''}`}
                >
                  {/* Radio button */}
                  <button
                    className={`img-card__radio ${isActive ? 'img-card__radio--on' : ''}`}
                    onClick={() => !isActive && handleSelect(img.path)}
                    disabled={isSwitching}
                    title={isActive ? 'Image active (autoinstall)' : 'Activer cette image'}
                  >
                    <span className="img-card__radio-inner" />
                  </button>

                  {/* Info */}
                  <div className="img-card__info">
                    <div className="img-card__name">{img.name}</div>
                    <div className="img-card__folder">{img.folder}</div>
                    <div className="img-card__meta">
                      <span className="img-card__version">v{img.version}</span>
                      {img.release_date && (
                        <span className="img-card__date">{img.release_date}</span>
                      )}
                    </div>
                    {img.description && (
                      <div className="img-card__desc">{img.description}</div>
                    )}
                  </div>

                  {/* Status badge */}
                  <div className="img-card__status">
                    {isActive ? (
                      <span className="img-card__badge img-card__badge--active">
                        <svg width="12" height="12" viewBox="0 0 16 16" fill="none">
                          <path d="M3 8.5l3.5 3.5 6.5-8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                        Autoinstall
                      </span>
                    ) : (
                      <span className="img-card__badge img-card__badge--inactive">
                        Inactif
                      </span>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Footer info */}
        <div className="img-panel__footer">
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="7" stroke="currentColor" strokeWidth="1.2"/>
            <path d="M8 5v1M8 8v3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <span>
            L'image sélectionnée sera installée automatiquement au démarrage des cartes.
          </span>
        </div>
      </div>
    </>
  );
}
