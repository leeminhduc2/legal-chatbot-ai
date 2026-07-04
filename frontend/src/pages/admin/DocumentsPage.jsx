import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import Modal from '../../components/Modal';
import toast from 'react-hot-toast';
import './AdminPage.css';

const METADATA_FIELDS = [
  'title', 'document_number', 'document_type', 'issued_date',
  'effective_date', 'expiry_date', 'validity_status', 'issuing_body',
  'signer_title', 'signer_name',
];

const VALIDITY_OPTIONS = [
  'active', 'partially_expired', 'expired', 'not_yet_effective',
  'suspended', 'revoked', 'unknown',
];

export default function DocumentsPage() {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [activeTab, setActiveTab] = useState('metadata');
  const [metadata, setMetadata] = useState({});
  const [chunksText, setChunksText] = useState('');
  const [relationsText, setRelationsText] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => { loadDocuments(); }, []);

  const loadDocuments = async () => {
    setLoading(true);
    try {
      const res = await api('/admin/documents');
      const data = await res.json();
      setDocuments(data.documents || []);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  };

  const openDetail = async (docId) => {
    try {
      const res = await api(`/admin/documents/${docId}`);
      const detail = await res.json();
      setSelected(detail);
      setMetadata({ ...detail.document });
      setChunksText(JSON.stringify(detail.chunks || [], null, 2));
      setRelationsText(JSON.stringify(detail.relations || [], null, 2));
      setActiveTab('metadata');
    } catch (err) {
      toast.error(err.message);
    }
  };

  const saveMetadata = async () => {
    setSaving(true);
    try {
      const body = {};
      METADATA_FIELDS.forEach((k) => { body[k] = metadata[k] || ''; });
      const res = await api(`/admin/documents/${selected.document.document_id}/metadata`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const detail = await res.json();
      setSelected(detail);
      toast.success(t('admin.documents.saved'));
      loadDocuments();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const saveChunks = async () => {
    setSaving(true);
    try {
      const chunks = JSON.parse(chunksText);
      const res = await api(`/admin/documents/${selected.document.document_id}/chunks`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chunks }),
      });
      setSelected(await res.json());
      toast.success(t('admin.documents.saved'));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const saveRelations = async () => {
    setSaving(true);
    try {
      const relations = JSON.parse(relationsText);
      const res = await api(`/admin/documents/${selected.document.document_id}/relationships`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ relations }),
      });
      setSelected(await res.json());
      toast.success(t('admin.documents.saved'));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async (docId) => {
    try {
      await api(`/admin/documents/${docId}/publish`, { method: 'POST' });
      toast.success('Published!');
      loadDocuments();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDownload = async (docId, name) => {
    try {
      const res = await api(`/admin/documents/${docId}/download`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${name || 'document'}.docx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async (docId, title) => {
    if (!window.confirm(`${t('admin.documents.confirm_delete')} "${title || docId}"?`)) return;
    try {
      await api(`/admin/documents/${docId}`, { method: 'DELETE' });
      toast.success(t('admin.documents.deleted'));
      setSelected(null);
      loadDocuments();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return documents;
    const q = search.toLowerCase();
    return documents.filter((d) =>
      (d.title || '').toLowerCase().includes(q) ||
      (d.document_number || '').toLowerCase().includes(q)
    );
  }, [documents, search]);

  const reviewFields = useMemo(
    () => new Set(selected?.needs_review_fields || []),
    [selected]
  );

  if (loading) {
    return <div className="flex justify-center" style={{ padding: 80 }}><div className="spinner spinner-lg" /></div>;
  }

  return (
    <div className="admin-page animate-fadeIn">
      <div className="page-header flex justify-between items-center flex-wrap gap-md">
        <h1>{t('admin.documents.title')}</h1>
        <input
          type="text"
          placeholder={t('admin.documents.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="search-input"
          id="doc-search"
        />
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>{t('admin.documents.doc_name')}</th>
              <th>{t('admin.documents.doc_number')}</th>
              <th>{t('admin.documents.chunks')}</th>
              <th>{t('admin.documents.review')}</th>
              <th>{t('admin.documents.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((doc, i) => (
              <tr key={doc.document_id}>
                <td>{i + 1}</td>
                <td className="truncate" style={{ maxWidth: 350 }}>{doc.title || 'Untitled'}</td>
                <td>{doc.document_number || '-'}</td>
                <td>{doc.chunk_count ?? 0}</td>
                <td>
                  <span className={`badge ${doc.needs_review ? 'badge-warning' : 'badge-success'}`}>
                    {doc.needs_review ? t('admin.documents.needs_review') : t('admin.documents.ok')}
                  </span>
                </td>
                <td>
                  <div className="flex gap-sm flex-wrap">
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload(doc.document_id, doc.document_number)}>📥</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => openDetail(doc.document_id)}>✏️</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handlePublish(doc.document_id)}>🚀</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(doc.document_id, doc.title)}>🗑️</button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan="6" className="text-center text-muted" style={{ padding: 32 }}>{t('admin.documents.no_docs')}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Detail Modal */}
      <Modal
        isOpen={!!selected}
        onClose={() => setSelected(null)}
        title={selected?.document?.title || 'Document'}
        width="980px"
      >
        <p className="text-muted text-sm">{selected?.document?.document_number || selected?.document?.document_id}</p>

        <div className="tabs">
          {['metadata', 'chunks', 'relations'].map((tab) => (
            <button
              key={tab}
              className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {t(`admin.documents.${tab === 'relations' ? 'relations' : tab === 'chunks' ? 'chunks_tab' : 'metadata'}`)}
            </button>
          ))}
        </div>

        {activeTab === 'metadata' && (
          <div className="metadata-grid">
            {METADATA_FIELDS.map((key) => (
              <div key={key} className={`form-group ${reviewFields.has(key) ? 'needs-review' : ''}`}>
                <label>{t(`admin.import.fields.${key}`)}</label>
                {key === 'validity_status' ? (
                  <select
                    value={metadata[key] || 'active'}
                    onChange={(e) => setMetadata({ ...metadata, [key]: e.target.value })}
                  >
                    {VALIDITY_OPTIONS.map((v) => (
                      <option key={v} value={v}>{t(`validity.${v}`)}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={metadata[key] || ''}
                    onChange={(e) => setMetadata({ ...metadata, [key]: e.target.value })}
                  />
                )}
              </div>
            ))}
            <button className="btn btn-primary" onClick={saveMetadata} disabled={saving}>
              {saving ? <span className="spinner" /> : null} {t('admin.documents.save')}
            </button>
          </div>
        )}

        {activeTab === 'chunks' && (
          <div className="editor-pane">
            <textarea
              value={chunksText}
              onChange={(e) => setChunksText(e.target.value)}
              className="code-editor"
            />
            <button className="btn btn-primary" onClick={saveChunks} disabled={saving}>
              {saving ? <span className="spinner" /> : null} {t('admin.documents.save')}
            </button>
          </div>
        )}

        {activeTab === 'relations' && (
          <div className="editor-pane">
            <textarea
              value={relationsText}
              onChange={(e) => setRelationsText(e.target.value)}
              className="code-editor"
            />
            <button className="btn btn-primary" onClick={saveRelations} disabled={saving}>
              {saving ? <span className="spinner" /> : null} {t('admin.documents.save')}
            </button>
          </div>
        )}
      </Modal>
    </div>
  );
}
