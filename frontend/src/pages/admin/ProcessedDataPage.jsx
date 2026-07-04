import { useEffect, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import Modal from '../../components/Modal';
import toast from 'react-hot-toast';
import './AdminPage.css';

export default function ProcessedDataPage() {
  const { t } = useTranslation();
  const [documents, setDocuments] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [editDoc, setEditDoc] = useState(null);
  const [editMeta, setEditMeta] = useState({});

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
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

  const filtered = useMemo(() => {
    if (!search.trim()) return documents;
    const q = search.toLowerCase();
    return documents.filter((d) =>
      (d.title || '').toLowerCase().includes(q) ||
      (d.document_number || '').toLowerCase().includes(q)
    );
  }, [documents, search]);

  const openEdit = (doc) => {
    setEditDoc(doc);
    setEditMeta({
      title: doc.title || '',
      document_number: doc.document_number || '',
      validity_status: doc.validity_status || 'active',
    });
  };

  const saveEdit = async () => {
    try {
      await api(`/admin/documents/${editDoc.document_id}/metadata`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editMeta),
      });
      toast.success(t('admin.documents.saved'));
      setEditDoc(null);
      loadData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = async (doc) => {
    if (!window.confirm(t('admin.processed.confirm_delete'))) return;
    try {
      await api(`/admin/documents/${doc.document_id}`, { method: 'DELETE' });
      toast.success(t('admin.documents.deleted'));
      loadData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  if (loading) {
    return <div className="flex justify-center" style={{ padding: 80 }}><div className="spinner spinner-lg" /></div>;
  }

  return (
    <div className="admin-page animate-fadeIn">
      <div className="page-header flex justify-between items-center flex-wrap gap-md">
        <div>
          <h1>{t('admin.processed.title')}</h1>
          <p>{t('admin.processed.subtitle')}</p>
        </div>
        <input
          type="text"
          placeholder={t('admin.processed.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="search-input"
        />
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>{t('admin.processed.index')}</th>
              <th>{t('admin.processed.filename')}</th>
              <th>{t('admin.processed.chunk_count')}</th>
              <th>{t('admin.processed.article_count')}</th>
              <th>{t('admin.processed.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((doc, i) => (
              <tr key={doc.document_id}>
                <td>{i + 1}</td>
                <td className="truncate" style={{ maxWidth: 350 }}>{doc.title || doc.document_number || '-'}</td>
                <td>{doc.chunk_count ?? 0}</td>
                <td>{doc.article_count ?? '-'}</td>
                <td>
                  <div className="flex gap-sm">
                    <button className="btn btn-ghost btn-sm" onClick={() => openEdit(doc)}>✏️ {t('admin.processed.edit')}</button>
                    <button className="btn btn-ghost btn-sm" style={{ color: 'var(--danger)' }} onClick={() => handleDelete(doc)}>🗑️ {t('admin.processed.delete')}</button>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan="5" className="text-center text-muted" style={{ padding: 32 }}>{t('admin.processed.no_data')}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Edit Modal */}
      <Modal
        isOpen={!!editDoc}
        onClose={() => setEditDoc(null)}
        title={`${t('admin.processed.edit')}: ${editDoc?.title || ''}`}
        width="500px"
      >
        <div className="form-group">
          <label>{t('admin.import.fields.title')}</label>
          <input value={editMeta.title} onChange={(e) => setEditMeta({ ...editMeta, title: e.target.value })} />
        </div>
        <div className="form-group">
          <label>{t('admin.import.fields.document_number')}</label>
          <input value={editMeta.document_number} onChange={(e) => setEditMeta({ ...editMeta, document_number: e.target.value })} />
        </div>
        <div className="form-group">
          <label>{t('admin.import.fields.validity_status')}</label>
          <select value={editMeta.validity_status} onChange={(e) => setEditMeta({ ...editMeta, validity_status: e.target.value })}>
            {['active', 'partially_expired', 'expired', 'not_yet_effective', 'suspended', 'revoked', 'unknown'].map((v) => (
              <option key={v} value={v}>{t(`validity.${v}`)}</option>
            ))}
          </select>
        </div>
        <div className="flex gap-sm" style={{ marginTop: 8 }}>
          <button className="btn btn-primary" onClick={saveEdit}>{t('common.save')}</button>
          <button className="btn btn-secondary" onClick={() => setEditDoc(null)}>{t('common.cancel')}</button>
        </div>
      </Modal>
    </div>
  );
}
