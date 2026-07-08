import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import Header from '../components/Header';
import toast from 'react-hot-toast';
import { api } from '../services/api';
import './FeaturePage.css';

const LEGAL_DRAFT_TYPES = [
  { value: 'submission', mode: 'document', labelKey: 'draft.document.types.submission' },
  { value: 'approval', mode: 'document', labelKey: 'draft.document.types.approval' },
  { value: 'appendix', mode: 'document', labelKey: 'draft.document.types.appendix' },
  { value: 'agency', mode: 'contract', labelKey: 'draft.contract.types.agency' },
  { value: 'service', mode: 'contract', labelKey: 'draft.contract.types.service' },
  { value: 'partnership', mode: 'contract', labelKey: 'draft.contract.types.partnership' },
];

export default function LegalDraftingPage() {
  const { t } = useTranslation();
  const [draftType, setDraftType] = useState('submission');
  const [subject, setSubject] = useState('');
  const [details, setDetails] = useState('');
  const [partyA, setPartyA] = useState('');
  const [partyB, setPartyB] = useState('');
  const [preview, setPreview] = useState('');
  const [busy, setBusy] = useState(false);

  const selectedType = LEGAL_DRAFT_TYPES.find((type) => type.value === draftType) || LEGAL_DRAFT_TYPES[0];
  const isContract = selectedType.mode === 'contract';

  const buildContractTerms = () => (
    [
      subject.trim() ? `${t('draft.legal.purpose')}: ${subject.trim()}` : '',
      details.trim(),
    ].filter(Boolean).join('\n\n')
  );

  const buildFallbackPreview = () => {
    const typeLabel = t(selectedType.labelKey);
    if (isContract) {
      return [
        `[${typeLabel}]`,
        '',
        `${t('draft.legal.purpose')}: ${subject || '...'}`,
        `${t('draft.contract.party_a')}: ${partyA || '...'}`,
        `${t('draft.contract.party_b')}: ${partyB || '...'}`,
        '',
        `${t('draft.legal.requirements')}:`,
        details || '...',
        '',
        '---',
        t('draft.legal.auto_note'),
      ].join('\n');
    }

    return [
      `[${typeLabel}]`,
      '',
      `${t('draft.legal.purpose')}: ${subject}`,
      '',
      `${t('draft.legal.requirements')}:`,
      details || '...',
      '',
      '---',
      t('draft.legal.auto_note'),
    ].join('\n');
  };

  const handleGenerate = async (e) => {
    e.preventDefault();
    if (!subject.trim()) {
      toast.error(t('draft.legal.missing_subject'));
      return;
    }

    setBusy(true);
    try {
      const path = isContract ? '/draft/contract' : '/draft/document';
      const body = isContract
        ? { type: draftType, party_a: partyA, party_b: partyB, terms: buildContractTerms() }
        : { type: draftType, subject, details };

      const res = await api(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      setPreview(data.content || data.draft || '');
      toast.success(t('draft.legal.generated'));
    } catch {
      setPreview(buildFallbackPreview());
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="home-layout">
      <Header />
      <main className="feature-page page-container animate-slideUp">
        <div className="page-header">
          <h1>{t('draft.legal.title')}</h1>
          <p>{t('draft.legal.subtitle')}</p>
        </div>

        <div className="feature-content">
          <form className="feature-form card" onSubmit={handleGenerate}>
            <div className="form-group">
              <label>{t('draft.legal.type')}</label>
              <select value={draftType} onChange={(e) => setDraftType(e.target.value)}>
                {LEGAL_DRAFT_TYPES.map((type) => (
                  <option key={type.value} value={type.value}>
                    {t(type.labelKey)}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>{t('draft.legal.purpose')}</label>
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder={t('draft.legal.purpose_placeholder')}
              />
            </div>

            {isContract && (
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
            )}

            <div className="form-group">
              <label>{t('draft.legal.requirements')}</label>
              <textarea
                rows={6}
                value={details}
                onChange={(e) => setDetails(e.target.value)}
                placeholder={t('draft.legal.requirements_placeholder')}
              />
            </div>

            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : null}
              {t('draft.legal.generate')}
            </button>
          </form>

          {preview && (
            <div className="feature-preview card">
              <h3>{t('draft.legal.preview')}</h3>
              <pre className="preview-content">{preview}</pre>
              <div className="disclaimer-banner">{t('draft.legal.disclaimer')}</div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
