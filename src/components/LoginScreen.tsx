import type { Theme } from '../App';

// ─── Liste des opérateurs ─────────────────────────────────────────────────────
// Modifiez ce tableau pour ajouter / supprimer des opérateurs.
export const OPERATORS = [
  'Opérateur 1',
  'Opérateur 2',
  'Opérateur 3',
  'Opérateur 4',
  'Opérateur 5',
  'Opérateur 6',
];
// ──────────────────────────────────────────────────────────────────────────────

interface Props {
  onSelect: (operator: string) => void;
  theme: Theme;
  onToggleTheme: () => void;
}

export default function LoginScreen({ onSelect, theme, onToggleTheme }: Props) {
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

      <div className="login-card">

        {/* Logo / titre */}
        <div className="login-card__logo">
          <img src="/images.png" alt="Toradex" height="52" />
        </div>

        <h1 className="login-card__title">Verdin AM62 Flash Monitor</h1>
        <p className="login-card__subtitle">Sélectionnez votre nom pour continuer</p>

        <div className="login-card__list">
          {OPERATORS.map(op => (
            <button
              key={op}
              className="login-card__op-btn"
              onClick={() => onSelect(op)}
            >
              <span className="login-card__op-avatar">
                {op.charAt(0).toUpperCase()}
              </span>
              <span className="login-card__op-name">{op}</span>
              <svg className="login-card__op-arrow" width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
