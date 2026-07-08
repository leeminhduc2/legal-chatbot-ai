import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import toast from 'react-hot-toast';
import './AdminPage.css';

export default function ImportDocxPage() {
  const { t } = useTranslation();
  const [files, setFiles] = useState([]);
  const [fieldId, setFieldId] = useState('');
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState([]);

  const handleImport = async (e) => {
    e.preventDefault();
    if (!files.length) return;
    const normalizedFieldId = fieldId.trim();
    if (normalizedFieldId && !/^\d+$/.test(normalizedFieldId)) {
      toast.error(t('admin.users.field_ids_invalid'));
      return;
    }

    setBusy(true);
    setResults([]);
    const nextResults = [];

    for (const file of files) {
      try {
        const form = new FormData();
        form.append('file', file);
        form.append('is_legal_document', 'false');
        if (normalizedFieldId) {
          form.append('field_id', normalizedFieldId);
        }

        const res = await api('/admin/documents/import', { method: 'POST', body: form });
        const data = await res.json();
        nextResults.push({ file_name: file.name, ok: true, data });
      } catch (err) {
        nextResults.push({
          file_name: file.name,
          ok: false,
          error: err.message || 'Import failed',
        });
      }
      setResults([...nextResults]);
    }

    const successCount = nextResults.filter((result) => result.ok).length;
    if (successCount === nextResults.length) {
      toast.success(`${successCount}/${nextResults.length} files imported.`);
      setFiles([]);
      setFieldId('');
      e.target.reset();
    } else {
      toast.error(`${successCount}/${nextResults.length} files imported.`);
    }
    setBusy(false);
  };

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
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files || []))}
            disabled={busy}
          />
        </div>

        <div className="form-group">
          <label>{t('admin.import.fields.field_id')}</label>
          <input
            type="number"
            min="0"
            step="1"
            value={fieldId}
            onChange={(e) => setFieldId(e.target.value)}
            disabled={busy}
            placeholder="0"
          />
        </div>

        {files.length > 0 && (
          <div className="import-file-list">
            {files.map((file) => (
              <span key={`${file.name}-${file.lastModified}`} className="badge badge-info">
                {file.name}
              </span>
            ))}
          </div>
        )}

        <button type="submit" className="btn btn-primary" disabled={busy || !files.length}>
          {busy ? <><span className="spinner" /> {t('admin.import.importing')}</> : t('admin.import.import_btn')}
        </button>
      </form>

      {results.length > 0 && (
        <div className="card mt-lg animate-slideUp">
          <h3>Import Result</h3>
          <div className="table-container" style={{ border: 'none' }}>
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th>File</th>
                  <th>Status</th>
                  <th>Document</th>
                </tr>
              </thead>
              <tbody>
                {results.map((result, index) => (
                  <tr key={`${result.file_name}-${index}`}>
                    <td>{index + 1}</td>
                    <td className="truncate" style={{ maxWidth: 360 }}>{result.file_name}</td>
                    <td>
                      <span className={`badge ${result.ok ? 'badge-success' : 'badge-danger'}`}>
                        {result.ok ? result.data?.status || 'imported' : 'failed'}
                      </span>
                    </td>
                    <td className="truncate" style={{ maxWidth: 420 }}>
                      {result.ok
                        ? result.data?.title || result.data?.document_number || result.data?.document_id
                        : result.error}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="result-json">{JSON.stringify(results, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
