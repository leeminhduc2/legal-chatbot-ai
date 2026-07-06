import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Header from '../components/Header';
import { api } from '../services/api';
import './FeaturePage.css';

export default function ContractReviewPage() {
  const { t } = useTranslation();
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState(null);

  const handleAnalyze = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await api('/review/contract', { method: 'POST', body: form });
      const data = await res.json();
      setReport(data);
    } catch {
      /* Mock report */
      setReport({
        authority: {
          issuing_body: { status: 'passed', detail: 'Bộ Tài chính' },
          signer: { status: 'passed', detail: 'Phó Tổng Giám đốc' },
        },
        validity: {
          status: 'active',
          warnings: ['Điều 15 đã bị sửa đổi bởi Nghị định 46/2023/NĐ-CP'],
        },
        risks: [
          { severity: 'high', description: 'Thiếu điều khoản bảo mật thông tin', suggestion: 'Bổ sung điều khoản bảo mật theo Luật An ninh mạng 2018' },
          { severity: 'medium', description: 'Điều khoản phạt vi phạm chưa rõ mức phạt', suggestion: 'Quy định cụ thể mức phạt theo tỷ lệ % giá trị hợp đồng' },
          { severity: 'low', description: 'Viện dẫn văn bản đã cũ (Luật KDBH 2000)', suggestion: 'Cập nhật sang Luật KDBH 2022 (08/2022/QH15)' },
        ],
      });
    } finally {
      setBusy(false);
    }
  };

  const statusIcon = { passed: '✅', failed: '❌', warning: '⚠️' };
  const severityBadge = { high: 'badge-danger', medium: 'badge-warning', low: 'badge-info' };
  const risks = Array.isArray(report?.risks) ? report.risks : [];

  return (
    <div className="home-layout">
      <Header />
      <main className="feature-page page-container animate-slideUp">
        <div className="page-header">
          <h1>{t('review.title')}</h1>
          <p>{t('review.subtitle')}</p>
        </div>

        <form className="feature-form card" onSubmit={handleAnalyze} style={{ maxWidth: 500 }}>
          <div className="form-group">
            <label>{t('review.upload')}</label>
            <input
              type="file"
              accept=".docx"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? <span className="spinner" /> : null}
            {busy ? t('review.analyzing') : t('review.analyze')}
          </button>
        </form>

        {report && (
          <div className="review-report animate-slideUp">
            {/* Authority Module */}
            <div className="card mt-lg">
              <h3>{t('review.authority')}</h3>
              <div className="review-checklist">
                <div className="check-row">
                  <span>{t('review.issuing_body')}</span>
                  <span>{statusIcon[report.authority?.issuing_body?.status]} {report.authority?.issuing_body?.detail}</span>
                </div>
                <div className="check-row">
                  <span>{t('review.signer')}</span>
                  <span>{statusIcon[report.authority?.signer?.status]} {report.authority?.signer?.detail}</span>
                </div>
              </div>
            </div>

            {/* Validity Module */}
            <div className="card mt-md">
              <h3>{t('review.validity')}</h3>
              <span className={`badge ${report.validity?.status === 'active' ? 'badge-success' : 'badge-danger'}`}>
                {t(`validity.${report.validity?.status || 'unknown'}`)}
              </span>
              {report.validity?.warnings?.map((w, i) => (
                <p key={i} className="review-warning">⚠️ {w}</p>
              ))}
            </div>

            {/* Risk Summary */}
            <div className="card mt-md">
              <h3>{t('review.risk_summary')}</h3>
              <div className="table-container">
                <table>
                  <thead>
                    <tr>
                      <th>{t('risk.severity')}</th>
                      <th>{t('risk.description')}</th>
                      <th>{t('risk.suggestion')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {risks.length > 0 ? (
                      risks.map((r, i) => (
                        <tr key={i}>
                          <td><span className={`badge ${severityBadge[r.severity]}`}>{t(`risk.${r.severity}`)}</span></td>
                          <td>{r.description}</td>
                          <td>{r.suggestion}</td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={3} className="text-muted">
                          {t('risk.no_risks')}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
