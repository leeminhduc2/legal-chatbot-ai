import { useNavigate } from 'react-router-dom';
import './FeatureCard.css';

export default function FeatureCard({ icon, title, description, to, locked = false, lockedText = '', lockedTo = '' }) {
  const navigate = useNavigate();
  const target = locked ? lockedTo : to;
  const isClickable = Boolean(target);

  const handleActivate = () => {
    if (isClickable) {
      navigate(target);
    }
  };

  const handleKeyDown = (e) => {
    if (!isClickable || (e.key !== 'Enter' && e.key !== ' ')) return;
    e.preventDefault();
    handleActivate();
  };

  return (
    <div
      className={`feature-card card ${locked ? 'is-locked' : ''} ${isClickable ? 'is-clickable' : 'is-disabled'}`}
      onClick={handleActivate}
      onKeyDown={handleKeyDown}
      role={isClickable ? 'button' : undefined}
      tabIndex={isClickable ? 0 : undefined}
      aria-disabled={locked && !lockedTo ? true : undefined}
    >
      <div className="feature-card-body">
        <div className="feature-card-header">
          <div className="feature-icon">{icon}</div>
        </div>
        <h3 className="feature-title">{title}</h3>
        <p className="feature-desc">{description}</p>
      </div>
      {locked && lockedText && (
        <div className="feature-lock-overlay">
          <span className="feature-lock-text">{lockedText}</span>
        </div>
      )}
    </div>
  );
}
