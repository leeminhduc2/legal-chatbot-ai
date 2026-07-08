import './StatCard.css';

export default function StatCard({ icon, value, label, color, trend }) {
  return (
    <div className="stat-card card">
      <div className="stat-card-top">
        <div className="stat-icon" style={{ background: color || 'var(--accent-gold-light)' }}>
          {icon}
        </div>
        {trend && <span className="stat-trend">{trend}</span>}
      </div>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
