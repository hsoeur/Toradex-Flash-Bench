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
}

export default function LoginScreen({ onSelect }: Props) {
  return (
    <div className="login-screen">
      <div className="login-card">

        {/* Logo / titre */}
        <div className="login-card__logo">
          <svg width="48" height="48" viewBox="0 0 32 32" fill="none">
            <rect width="32" height="32" rx="6" fill="#3b82f6" />
            <path
              d="M8 22l4-12h2l2 8 2-8h2l4 12h-2l-2.8-8.4L17 22h-2l-2.2-8.4L10 22H8z"
              fill="white"
            />
          </svg>
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
