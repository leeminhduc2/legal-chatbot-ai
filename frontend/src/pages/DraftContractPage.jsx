import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Header from '../components/Header';
import toast from 'react-hot-toast';
import { api } from '../services/api';
import './FeaturePage.css';

export default function DraftContractPage() {
  const { t } = useTranslation();
  const [contractType, setContractType] = useState('agency');
  const [partyA, setPartyA] = useState('');
  const [partyB, setPartyB] = useState('');
  const [terms, setTerms] = useState('');
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState(false);

  const handleGenerate = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api('/draft/contract', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: contractType, party_a: partyA, party_b: partyB, terms }),
      });
      const data = await res.json();
      setPreview(data.content || data.draft || '');
      toast.success(t('admin.documents.saved'));
    } catch {
      setPreview(`[${t('draft.contract.types.' + contractType)}]\n\nBên A: ${partyA || '...'}\nBên B: ${partyB || '...'}\n\nĐiều khoản chính:\n${terms || '...'}\n\n---\n(Bản nháp được tạo tự động - vui lòng rà soát trước khi sử dụng)`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="home-layout">
      <Header />
      <main className="feature-page page-container animate-slideUp">
        <div className="page-header">
          <h1>{t('draft.contract.title')}</h1>
          <p>{t('draft.contract.subtitle')}</p>
        </div>

        <div className="feature-content">
          <form className="feature-form card" onSubmit={handleGenerate}>
            <div className="form-group">
              <label>{t('draft.contract.type')}</label>
              <select value={contractType} onChange={(e) => setContractType(e.target.value)}>
                {['agency', 'service', 'partnership'].map((type) => (
                  <option key={type} value={type}>
                    {t(`draft.contract.types.${type}`)}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label>{t('draft.contract.party_a')}</label>
                <input type="text" value={partyA} onChange={(e) => setPartyA(e.target.value)} />
              </div>
              <div className="form-group">
                <label>{t('draft.contract.party_b')}</label>
                <input type="text" value={partyB} onChange={(e) => setPartyB(e.target.value)} />
              </div>
            </div>
            <div className="form-group">
              <label>{t('draft.contract.terms')}</label>
              <textarea
                rows={5}
                value={terms}
                onChange={(e) => setTerms(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : null}
              {t('draft.contract.generate')}
            </button>
          </form>

          {preview && (
            <div className="feature-preview card">
              <h3>{t('draft.contract.preview')}</h3>
              <pre className="preview-content">{preview}</pre>
              <div className="disclaimer-banner">{t('draft.contract.disclaimer')}</div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
