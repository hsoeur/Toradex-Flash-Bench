import { useEffect, useRef, useState } from 'react';
import type { Theme } from '../App';

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || '';

/** Parse "OF25000" or "of25000" or bare "25000" → numeric UID string, or null if invalid. */
function parseOfInput(raw: string): string | null {
  const stripped = raw.trim().replace(/^[Oo][Ff]/g, '');
  if (/^\d+$/.test(stripped)) return stripped;
  return null;
}

interface Props {
  operatorName: string;
  onConfirm: (orderNumber: string) => void;
  onBack: () => void;
  theme: Theme;
  onToggleTheme: () => void;
}

export default function ScanOrderScreen({ operatorName, onConfirm, onBack, theme, onToggleTheme }: Props) {
  const [value, setValue] = useState('');
  const [error, setError]   = useState('');
  const [loading, setLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Auto-focus the input so the barcode scanner can type directly
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      setError('Aucun code détecté. Scannez ou saisissez l\'ordre de fabrication.');
      inputRef.current?.focus();
      return;
    }

    const uid = parseOfInput(trimmed);
    if (!uid) {
      setError('Format invalide. Attendu : OF25000 ou un nombre.');
      inputRef.current?.focus();
      return;
    }

    setLoading(true);
    setError('');
    try {
      const resp = await fetch(`${BACKEND_URL}/api/manufacturing-order/${uid}`);
      const data = await resp.json();
      if (!resp.ok) {
        setError(data?.error ?? `Ordre de fabrication ${uid} introuvable.`);
        inputRef.current?.focus();
        return;
      }
      // data.status validation (optional guard)
      if (data.status && data.status !== 'ACTIVE') {
        setError(`L'OF ${uid} n'est pas actif (statut: ${data.status}).`);
        inputRef.current?.focus();
        return;
      }
      onConfirm(uid);
    } catch {
      setError('Impossible de contacter le serveur. Vérifiez la connexion.');
      inputRef.current?.focus();
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setValue(e.target.value);
    if (error) setError('');
  };

  return (
    <div className="login-screen">
      {/* Theme toggle (top-right corner) */}
      <button
        className="theme-toggle login-screen__theme-toggle"
        onClick={onToggleTheme}
        title={theme === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre'}
      >
        {theme === 'dark' ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="5"/>
            <line x1="12" y1="1" x2="12" y2="3"/>
            <line x1="12" y1="21" x2="12" y2="23"/>
            <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/>
            <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/>
            <line x1="1" y1="12" x2="3" y2="12"/>
            <line x1="21" y1="12" x2="23" y2="12"/>
            <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/>
            <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>
          </svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
        )}
      </button>

      <div className="login-card scan-order-card">

        {/* Logo */}
        <div className="login-card__logo">
          <img src="/images.png" alt="Toradex" height="52" />
        </div>

        <h1 className="login-card__title">Verdin AM62 Flash Monitor</h1>

        {/* Operator badge */}
        <div className="scan-order__operator-badge">
          <span className="scan-order__operator-avatar">
            {operatorName.charAt(0).toUpperCase()}
          </span>
          <span className="scan-order__operator-name">{operatorName}</span>
        </div>

        <p className="login-card__subtitle scan-order__subtitle">
          Scannez le code-barres de l'ordre de fabrication
        </p>

        {/* Barcode icon */}
        <div className="scan-order__icon">
          <svg width="56" height="40" viewBox="0 0 56 40" fill="none">
            <rect x="0"  y="4" width="4"  height="32" rx="1" fill="currentColor"/>
            <rect x="6"  y="4" width="2"  height="32" rx="1" fill="currentColor"/>
            <rect x="10" y="4" width="4"  height="32" rx="1" fill="currentColor"/>
            <rect x="16" y="4" width="2"  height="32" rx="1" fill="currentColor"/>
            <rect x="20" y="4" width="6"  height="32" rx="1" fill="currentColor"/>
            <rect x="28" y="4" width="2"  height="32" rx="1" fill="currentColor"/>
            <rect x="32" y="4" width="4"  height="32" rx="1" fill="currentColor"/>
            <rect x="38" y="4" width="2"  height="32" rx="1" fill="currentColor"/>
            <rect x="42" y="4" width="6"  height="32" rx="1" fill="currentColor"/>
            <rect x="50" y="4" width="2"  height="32" rx="1" fill="currentColor"/>
            <rect x="54" y="4" width="2"  height="32" rx="1" fill="currentColor"/>
          </svg>
        </div>

        <form className="scan-order__form" onSubmit={handleSubmit}>
          <div className={`scan-order__input-wrap ${error ? 'scan-order__input-wrap--error' : ''}`}>
            <input
              ref={inputRef}
              className="scan-order__input"
              type="text"
              placeholder="Scan ou saisie manuelle…"
              value={value}
              onChange={handleChange}
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          {error && (
            <p className="scan-order__error">{error}</p>
          )}

          <button type="submit" className="scan-order__confirm-btn" disabled={loading}>
            {loading ? (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" style={{ animation: 'spin 0.8s linear infinite' }}>
                <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="2" strokeDasharray="28" strokeDashoffset="10"/>
              </svg>
            ) : (
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M3 8l4 4 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            )}
            {loading ? 'Validation…' : 'Confirmer'}
          </button>
        </form>

        <button className="scan-order__back-btn" onClick={onBack}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none">
            <path d="M10 4l-4 4 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          Changer d'opérateur
        </button>
      </div>
    </div>
  );
}
