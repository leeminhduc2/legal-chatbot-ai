import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Header from '../components/Header';
import { api } from '../services/api';
import './FeaturePage.css';

export default function RiskAlertsPage() {
  const { t } = useTranslation();
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [risks, setRisks] = useState(null);

  const handleAnalyze = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api('/risk/analyze', { method: 'POST', body: form });
      const data = await res.json();
      setRisks(data.risks || []);
    } catch {
      /* Mock risks */
      setRisks([
        { severity: 'high', description: 'Thiếu điều khoản bảo mật thông tin khách hàng', suggestion: 'Bổ sung điều khoản bảo mật theo Luật An ninh mạng 2018' },
        { severity: 'high', description: 'Điều khoản bồi thường mơ hồ, không quy định giới hạn', suggestion: 'Quy định rõ giới hạn bồi thường tối đa' },
        { severity: 'medium', description: 'Không có điều khoản giải quyết tranh chấp', suggestion: 'Bổ sung điều khoản trọng tài hoặc tòa án có thẩm quyền' },
        { severity: 'medium', description: 'Viện dẫn văn bản đã hết hiệu lực (Luật KDBH 2000)', suggestion: 'Cập nhật sang Luật KDBH 2022 (08/2022/QH15)' },
        { severity: 'low', description: 'Thuật ngữ "bên liên quan" chưa được định nghĩa rõ', suggestion: 'Định nghĩa cụ thể trong phần giải thích từ ngữ' },
      ]);
    } finally {
      setBusy(false);
    }
  };

  const severityBadge = { high: 'badge-danger', medium: 'badge-warning', low: 'badge-info' };

  return (
    <div className="home-layout">
      <Header />
      <main className="feature-page page-container animate-slideUp">
        <div className="page-header">
          <h1>{t('risk.title')}</h1>
          <p>{t('risk.subtitle')}</p>
        </div>

        <form className="feature-form card" onSubmit={handleAnalyze} style={{ maxWidth: 500 }}>
          <div className="form-group">
            <label>{t('risk.upload')}</label>
            <input
              type="file"
              accept=".docx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? <span className="spinner" /> : null}
            {t('risk.analyze')}
          </button>
        </form>

        {risks && (
          <div className="risk-results animate-slideUp mt-lg">
            {risks.length === 0 ? (
              <div className="empty-state card">
                <span className="empty-icon">✅</span>
                <p>{t('risk.no_risks')}</p>
              </div>
            ) : (
              <div className="risk-list">
                {risks.map((risk, i) => (
                  <div key={i} className="card risk-item">
                    <div className="risk-header">
                      <span className={`badge ${severityBadge[risk.severity]}`}>
                        {t(`risk.${risk.severity}`)}
                      </span>
                    </div>
                    <p className="risk-description">{risk.description}</p>
                    <div className="risk-suggestion">
                      <span className="risk-suggestion-label">💡 {t('risk.suggestion')}:</span>
                      <span>{risk.suggestion}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
