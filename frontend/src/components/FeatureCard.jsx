import { useNavigate } from 'react-router-dom';
import './FeatureCard.css';

export default function FeatureCard({ icon, title, description, to }) {
  const navigate = useNavigate();

  return (
    <div className="feature-card card" onClick={() => navigate(to)}>
      <div className="feature-card-header">
        <div className="feature-icon">{icon}</div>
      </div>
      <h3 className="feature-title">{title}</h3>
      <p className="feature-desc">{description}</p>
    </div>
  );
}
