import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import StatCard from '../../components/StatCard';
import './DashboardPage.css';

export default function DashboardPage() {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadData();
  }, []);

  const loadData = async () => {
    setLoading(true);
    try {
      const docRes = await api('/admin/documents');
      const docData = await docRes.json();
      setDocuments(docData.documents || []);
    } catch { /* ignore */ }

    try {
      const userRes = await api('/admin/users');
      const userData = await userRes.json();
      setUsers(userData.users || []);
    } catch { /* No user endpoint yet */ }

    setLoading(false);
  };

  const stats = useMemo(() => {
    const now = new Date();
    const thirtyDays = new Date(now.getTime() + 30 * 24 * 60 * 60 * 1000);

    const active = documents.filter((d) => d.validity_status === 'active');
    const expired = documents.filter((d) => d.validity_status === 'expired');
    const expiring = documents.filter((d) => {
      if (!d.expiry_date) return false;
      const exp = new Date(d.expiry_date);
      return exp > now && exp <= thirtyDays;
    });

    return {
      total: documents.length,
      active: active.length,
      expiring: expiring.length,
      expired: expired.length,
      users: users.length || documents.length > 0 ? Math.max(users.length, 1) : 0,
      expiringDocs: expiring.concat(
        documents.filter((d) => d.validity_status === 'expired' || d.validity_status === 'partially_expired')
      ).slice(0, 10),
    };
  }, [documents, users]);

  /* Validity chart data */
  const chartData = useMemo(() => {
    const statusCounts = {};
    documents.forEach((d) => {
      const st = d.validity_status || 'unknown';
      statusCounts[st] = (statusCounts[st] || 0) + 1;
    });
    return Object.entries(statusCounts).map(([status, count]) => ({ status, count }));
  }, [documents]);

  const chartColors = {
    active: '#2e7d32',
    partially_expired: '#ef6c00',
    expired: '#c62828',
    not_yet_effective: '#1565c0',
    unknown: '#757575',
    suspended: '#ff8f00',
    revoked: '#6a1b9a',
  };

  const totalForChart = chartData.reduce((s, d) => s + d.count, 0) || 1;

  if (loading) {
    return (
      <div className="flex justify-center items-center" style={{ padding: 80 }}>
        <div className="spinner spinner-lg" />
      </div>
    );
  }

  return (
    <div className="dashboard-page animate-fadeIn">
      <div className="page-header">
        <h1>
          {t('admin.dashboard.title')}
          <span className="dashboard-subtitle">{t('admin.dashboard.subtitle')} · <span className="live-dot" />{t('admin.dashboard.live')}</span>
        </h1>
      </div>

      {/* Stat Cards */}
      <div className="stats-grid">
        <StatCard icon="📄" value={stats.total} label={t('admin.dashboard.total_docs')} color="rgba(26,35,126,0.12)" trend="📈" />
        <StatCard icon="✅" value={stats.active} label={t('admin.dashboard.active_docs')} color="rgba(46,125,50,0.12)" trend="📊" />
        <StatCard icon="⏰" value={stats.expiring} label={t('admin.dashboard.expiring_docs')} color="rgba(239,108,0,0.12)" trend="📉" />
        <StatCard icon="❌" value={stats.expired} label={t('admin.dashboard.expired_docs')} color="rgba(198,40,40,0.12)" trend="📊" />
        <StatCard icon="👥" value={stats.users || users.length} label={t('admin.dashboard.total_users')} color="rgba(249,168,37,0.12)" trend="📈" />
      </div>

      {/* Bottom Grid */}
      <div className="dashboard-bottom">
        {/* Expiring Docs Table */}
        <div className="card dashboard-table-card">
          <h3>{t('admin.dashboard.expiring_table')}</h3>
          <div className="table-container" style={{ border: 'none' }}>
            <table>
              <thead>
                <tr>
                  <th>{t('admin.dashboard.doc_number')}</th>
                  <th>{t('admin.dashboard.doc_title')}</th>
                  <th>{t('admin.dashboard.expiry_date')}</th>
                  <th>{t('admin.dashboard.doc_status')}</th>
                </tr>
              </thead>
              <tbody>
                {stats.expiringDocs.length === 0 ? (
                  <tr><td colSpan="4" className="text-center text-muted" style={{ padding: 24 }}>—</td></tr>
                ) : (
                  stats.expiringDocs.map((doc) => (
                    <tr key={doc.document_id} className={doc.validity_status === 'expired' ? 'row-danger' : 'row-warning'}>
                      <td><span className="badge badge-navy">{doc.document_number || '-'}</span></td>
                      <td className="truncate" style={{ maxWidth: 300 }}>{doc.title || '-'}</td>
                      <td>{doc.expiry_date || '-'}</td>
                      <td>
                        <span className={`badge ${doc.validity_status === 'expired' ? 'badge-danger' : 'badge-warning'}`}>
                          {t(`validity.${doc.validity_status || 'unknown'}`)}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Validity Chart */}
        <div className="card dashboard-chart-card">
          <h3>{t('admin.dashboard.validity_chart')}</h3>
          <div className="donut-chart-wrapper">
            <svg className="donut-chart" viewBox="0 0 120 120">
              {(() => {
                let cumAngle = 0;
                return chartData.map((d, i) => {
                  const angle = (d.count / totalForChart) * 360;
                  const startAngle = cumAngle;
                  cumAngle += angle;
                  const r = 44;
                  const cx = 60, cy = 60;
                  const toRad = (a) => (a - 90) * (Math.PI / 180);
                  const x1 = cx + r * Math.cos(toRad(startAngle));
                  const y1 = cy + r * Math.sin(toRad(startAngle));
                  const x2 = cx + r * Math.cos(toRad(startAngle + angle));
                  const y2 = cy + r * Math.sin(toRad(startAngle + angle));
                  const largeArc = angle > 180 ? 1 : 0;
                  const pathData = chartData.length === 1
                    ? `M ${cx} ${cy - r} A ${r} ${r} 0 1 1 ${cx - 0.01} ${cy - r}`
                    : `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
                  return (
                    <path
                      key={i}
                      d={pathData}
                      fill={chartColors[d.status] || '#757575'}
                    />
                  );
                });
              })()}
              <circle cx="60" cy="60" r="28" fill="var(--bg-card)" />
            </svg>
          </div>
          <div className="chart-legend">
            {chartData.map((d) => (
              <div key={d.status} className="legend-item">
                <span className="legend-dot" style={{ background: chartColors[d.status] || '#757575' }} />
                <span className="legend-label">{t(`validity.${d.status}`)}</span>
                <span className="legend-value">{d.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
