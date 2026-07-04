import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import toast from 'react-hot-toast';
import './AdminPage.css';

const VALIDITY_OPTIONS = [
  'active', 'partially_expired', 'expired', 'not_yet_effective',
  'suspended', 'revoked', 'unknown',
];

export default function ImportDocxPage() {
  const { t } = useTranslation();
  const [file, setFile] = useState(null);
  const [isLegal, setIsLegal] = useState(true);
  const [metadata, setMetadata] = useState({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);

  const handleImport = async (e) => {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      form.append('is_legal_document', isLegal ? 'true' : 'false');
      Object.entries(metadata).forEach(([k, v]) => {
        if (v) form.append(k, v);
      });
      const res = await api('/admin/documents/import', { method: 'POST', body: form });
      const data = await res.json();
      setResult(data);
      toast.success(t('admin.import.success'));
      setFile(null);
      setMetadata({});
      e.target.reset();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  };

  const metaFields = [
    'title', 'document_number', 'document_type', 'issued_date',
    'effective_date', 'expiry_date', 'issuing_body', 'signer_title', 'signer_name',
  ];

  return (
    <div className="admin-page animate-fadeIn">
      <div className="page-header">
        <h1>{t('admin.import.title')}</h1>
        <p>{t('admin.import.subtitle')}</p>
      </div>

      <form className="card import-form" onSubmit={handleImport}>
        <div className="form-group">
          <label>{t('admin.import.file')}</label>
          <input
            type="file"
            accept=".docx"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
          />
        </div>

        <div className="checkbox-row">
          <input
            type="checkbox"
            id="is-legal"
            checked={isLegal}
            onChange={(e) => setIsLegal(e.target.checked)}
          />
          <label htmlFor="is-legal" style={{ marginBottom: 0, textTransform: 'none', fontWeight: 500 }}>
            {t('admin.import.legal_doc')}
          </label>
        </div>

        <h3 style={{ margin: '8px 0 0' }}>Metadata</h3>
        <div className="metadata-grid">
          {metaFields.map((key) => (
            <div key={key} className="form-group">
              <label>{t(`admin.import.fields.${key}`)}</label>
              <input
                value={metadata[key] || ''}
                onChange={(e) => setMetadata({ ...metadata, [key]: e.target.value })}
              />
            </div>
          ))}
          <div className="form-group">
            <label>{t('admin.import.fields.validity_status')}</label>
            <select
              value={metadata.validity_status || 'active'}
              onChange={(e) => setMetadata({ ...metadata, validity_status: e.target.value })}
            >
              {VALIDITY_OPTIONS.map((v) => (
                <option key={v} value={v}>{t(`validity.${v}`)}</option>
              ))}
            </select>
          </div>
        </div>

        <button type="submit" className="btn btn-primary" disabled={busy || !file}>
          {busy ? <><span className="spinner" /> {t('admin.import.importing')}</> : t('admin.import.import_btn')}
        </button>
      </form>

      {result && (
        <div className="card mt-lg animate-slideUp">
          <h3>Import Result</h3>
          <pre className="result-json">{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
