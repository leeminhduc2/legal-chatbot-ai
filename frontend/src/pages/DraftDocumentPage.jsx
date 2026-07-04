import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Header from '../components/Header';
import toast from 'react-hot-toast';
import { api } from '../services/api';
import './FeaturePage.css';

export default function DraftDocumentPage() {
  const { t } = useTranslation();
  const [docType, setDocType] = useState('submission');
  const [subject, setSubject] = useState('');
  const [details, setDetails] = useState('');
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState(false);

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (!subject.trim()) return;
    setBusy(true);
    try {
      const res = await api('/draft/document', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: docType, subject, details }),
      });
      const data = await res.json();
      setPreview(data.content || data.draft || '');
      toast.success(t('admin.documents.saved'));
    } catch {
      setPreview(`[${t('draft.document.types.' + docType)}]\n\nChủ đề: ${subject}\n\nNội dung:\n${details || '...'}\n\n---\n(Bản nháp được tạo tự động - vui lòng rà soát trước khi sử dụng)`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="home-layout">
      <Header />
      <main className="feature-page page-container animate-slideUp">
        <div className="page-header">
          <h1>{t('draft.document.title')}</h1>
          <p>{t('draft.document.subtitle')}</p>
        </div>

        <div className="feature-content">
          <form className="feature-form card" onSubmit={handleGenerate}>
            <div className="form-group">
              <label>{t('draft.document.type')}</label>
              <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                {['submission', 'approval', 'appendix'].map((type) => (
                  <option key={type} value={type}>
                    {t(`draft.document.types.${type}`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-group">
              <label>{t('draft.document.subject')}</label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder={t('draft.document.subject')}
              />
            </div>
            <div className="form-group">
              <label>{t('draft.document.details')}</label>
              <textarea
                rows={5}
                value={details}
                onChange={(e) => setDetails(e.target.value)}
                placeholder={t('draft.document.details')}
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : null}
              {t('draft.document.generate')}
            </button>
          </form>

          {preview && (
            <div className="feature-preview card">
              <h3>{t('draft.document.preview')}</h3>
              <pre className="preview-content">{preview}</pre>
              <div className="disclaimer-banner">{t('draft.document.disclaimer')}</div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
