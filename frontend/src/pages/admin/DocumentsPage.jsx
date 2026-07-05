import { useCallback, useEffect, useRef, useState, useMemo } from 'react';
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

const PUBLISH_RELOAD_DELAY_MS = 800;
const PUBLISH_POLL_INTERVAL_MS = 2000;
const PUBLISH_TERMINAL_STATUSES = new Set(['published', 'failed']);

export default function DocumentsPage({ mode = 'published' }) {
  const { t } = useTranslation();
  const isPublishedPage = mode === 'published';
  const documentStatus = isPublishedPage ? 'published' : 'ready_for_review';
  const detailScope = isPublishedPage ? 'active' : 'latest';
  const publishReloadTimerRef = useRef(null);
  const publishPollTimerRef = useRef(null);
  const [documents, setDocuments] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);
  const [activeTab, setActiveTab] = useState('metadata');
  const [metadata, setMetadata] = useState({});
  const [chunksText, setChunksText] = useState('');
  const [relationsText, setRelationsText] = useState('');
  const [saving, setSaving] = useState(false);
  const [publishingDocId, setPublishingDocId] = useState('');
  const [publishingRunId, setPublishingRunId] = useState('');

  const loadDocuments = useCallback(async ({ reset = false, isStale = () => false } = {}) => {
    setLoading(true);
    if (reset) {
      setDocuments([]);
      setSelected(null);
      setActiveTab('metadata');
      setMetadata({});
      setChunksText('');
      setRelationsText('');
    }

    try {
      const res = await api(`/admin/documents?status=${documentStatus}`);
      const data = await res.json();
      if (isStale()) return;
      setDocuments(data.documents || []);
    } catch (err) {
      if (!isStale()) {
        setDocuments([]);
        toast.error(err.message);
      }
    } finally {
      if (!isStale()) {
        setLoading(false);
      }
    }
  }, [documentStatus]);

  useEffect(() => {
    let stale = false;
    loadDocuments({ reset: true, isStale: () => stale });
    return () => { stale = true; };
  }, [loadDocuments]);

  useEffect(() => () => {
    if (publishReloadTimerRef.current) {
      clearTimeout(publishReloadTimerRef.current);
    }
    if (publishPollTimerRef.current) {
      clearTimeout(publishPollTimerRef.current);
    }
  }, []);

  const scheduleReload = useCallback(() => {
    if (publishReloadTimerRef.current) {
      clearTimeout(publishReloadTimerRef.current);
    }
    publishReloadTimerRef.current = setTimeout(() => {
      loadDocuments();
      publishReloadTimerRef.current = null;
    }, PUBLISH_RELOAD_DELAY_MS);
  }, [loadDocuments]);

  const clearPublishPolling = useCallback(() => {
    if (publishPollTimerRef.current) {
      clearTimeout(publishPollTimerRef.current);
      publishPollTimerRef.current = null;
    }
  }, []);

  const finishPublishSuccess = useCallback((docId) => {
    clearPublishPolling();
    toast.success(t('admin.documents.published_success'));
    if (selected?.document?.document_id === docId) {
      setSelected(null);
    }
    setPublishingDocId('');
    setPublishingRunId('');
    scheduleReload();
  }, [clearPublishPolling, scheduleReload, selected, t]);

  const pollPublishRun = useCallback(async (runId, docId) => {
    try {
      const res = await api(`/admin/pipeline/${runId}`);
      const detail = await res.json();
      const pipelineRun = detail.pipeline_run || {};
      const status = pipelineRun.status || '';

      if (status === 'published') {
        finishPublishSuccess(docId);
        return;
      }

      if (status === 'failed') {
        clearPublishPolling();
        toast.error(formatPipelinePublishError(detail, t), { duration: 7000 });
        setPublishingDocId('');
        setPublishingRunId('');
        return;
      }

      if (!PUBLISH_TERMINAL_STATUSES.has(status)) {
        publishPollTimerRef.current = setTimeout(
          () => pollPublishRun(runId, docId),
          PUBLISH_POLL_INTERVAL_MS
        );
      }
    } catch (err) {
      clearPublishPolling();
      toast.error(formatPublishError(err, t), { duration: 6000 });
      setPublishingDocId('');
      setPublishingRunId('');
    }
  }, [clearPublishPolling, finishPublishSuccess, t]);

  const openDetail = async (docId) => {
    try {
      const res = await api(`/admin/documents/${docId}?scope=${detailScope}`);
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
      const suffix = isPublishedPage ? '?auto_publish=1' : '';
      const res = await api(`/admin/documents/${selected.document.document_id}/metadata${suffix}`, {
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
      const suffix = isPublishedPage ? '?auto_publish=1' : '';
      const res = await api(`/admin/documents/${selected.document.document_id}/chunks${suffix}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chunks }),
      });
      setSelected(await res.json());
      toast.success(t('admin.documents.saved'));
      loadDocuments();
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
      const suffix = isPublishedPage ? '?auto_publish=1' : '';
      const res = await api(`/admin/documents/${selected.document.document_id}/relationships${suffix}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ relations }),
      });
      setSelected(await res.json());
      toast.success(t('admin.documents.saved'));
      loadDocuments();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async (docId) => {
    if (publishingDocId) return;
    clearPublishPolling();
    setPublishingDocId(docId);
    setPublishingRunId('');
    try {
      const res = await api(`/admin/documents/${docId}/publish`, { method: 'POST' });
      const result = await res.json();
      if (result.status === 'published') {
        finishPublishSuccess(docId);
        return;
      }
      if (!result.pipeline_run_id) {
        throw new Error(t('admin.documents.publish_connection_error'));
      }
      setPublishingRunId(result.pipeline_run_id || '');
      toast.success(t('admin.documents.publish_started'));
      pollPublishRun(result.pipeline_run_id, docId);
    } catch (err) {
      toast.error(formatPublishError(err, t), { duration: 6000 });
      setPublishingDocId('');
      setPublishingRunId('');
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
  const publishBlockers = selected?.publish_blockers || [];
  const selectedDocumentId = selected?.document?.document_id || '';

  if (loading) {
    return <div className="flex justify-center" style={{ padding: 80 }}><div className="spinner spinner-lg" /></div>;
  }

  return (
    <div className="admin-page animate-fadeIn">
      <div className="page-header flex justify-between items-center flex-wrap gap-md">
        <h1>{t(isPublishedPage ? 'admin.documents.published_title' : 'admin.documents.review_title')}</h1>
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
              <th>{t(isPublishedPage ? 'admin.documents.doc_status' : 'admin.documents.review')}</th>
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
                  <span className={`badge ${doc.needs_republish || doc.needs_review ? 'badge-warning' : 'badge-success'}`}>
                    {doc.needs_republish ? t('admin.documents.needs_republish') : doc.needs_review ? t('admin.documents.needs_review') : t('admin.documents.ok')}
                  </span>
                </td>
                <td>
                  <div className="flex gap-sm flex-wrap">
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload(doc.document_id, doc.document_number)}>📥</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => openDetail(doc.document_id)}>✏️</button>
                    {!isPublishedPage && publishingDocId === doc.document_id && (
                      <button className="btn btn-ghost btn-sm" disabled title={publishingRunId || t('admin.documents.publish')}>
                        <span className="spinner" />
                      </button>
                    )}
                    {!isPublishedPage && publishingDocId !== doc.document_id && (
                      <button
                        className="btn btn-ghost btn-sm"
                        onClick={() => handlePublish(doc.document_id)}
                        disabled={!doc.is_publishable || publishingDocId === doc.document_id}
                        title={!doc.is_publishable ? `${t('admin.documents.missing_fields')}: ${(doc.publish_blockers || []).join(', ')}` : t('admin.documents.publish')}
                      >
                        🚀
                      </button>
                    )}
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
        {isPublishedPage && (
          <div className="admin-warning">
            {t('admin.documents.published_edit_warning')}
          </div>
        )}
        {!isPublishedPage && publishBlockers.length > 0 && (
          <div className="admin-warning">
            {t('admin.documents.missing_fields')}: {publishBlockers.join(', ')}
          </div>
        )}
        {selected?.last_publish_error && (
          <div className="admin-error">
            {t('admin.documents.last_publish_error')}: {selected.last_publish_error.message}
          </div>
        )}

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
        {!isPublishedPage && selectedDocumentId && (
          <div className="flex justify-end mt-lg">
            <button
              className="btn btn-primary"
              onClick={() => handlePublish(selectedDocumentId)}
              disabled={publishBlockers.length > 0 || publishingDocId === selectedDocumentId}
            >
              {publishingDocId === selectedDocumentId ? <span className="spinner" /> : null}
              {t('admin.documents.publish')}
            </button>
          </div>
        )}
      </Modal>
    </div>
  );
}

function formatPublishError(err, t) {
  const details = err?.details || {};
  const hasStructuredError = Boolean(err?.code || err?.details);
  if (!hasStructuredError && (!err?.status || err.status >= 500)) {
    return err?.message
      ? `${t('admin.documents.publish_connection_error')} (${err.message})`
      : t('admin.documents.publish_connection_error');
  }

  const parts = [];

  if (err?.message) parts.push(err.message);
  if (err?.code && err.code !== err.message) parts.push(err.code);
  if (details.message && details.message !== err?.message) parts.push(details.message);
  if (details.reason && details.reason !== err?.message) parts.push(details.reason);
  if (details.type) parts.push(details.type);
  if (Array.isArray(details.publish_blockers) && details.publish_blockers.length > 0) {
    parts.push(`${t('admin.documents.missing_fields')}: ${details.publish_blockers.join(', ')}`);
  }
  if (Array.isArray(details.cleanup_errors) && details.cleanup_errors.length > 0) {
    const cleanupMessages = details.cleanup_errors
      .map((item) => item.error || item.reason || item.message)
      .filter(Boolean);
    if (cleanupMessages.length > 0) {
      parts.push(`Cleanup: ${cleanupMessages.join('; ')}`);
    }
  }

  const uniqueParts = [...new Set(parts.filter(Boolean))];
  if (uniqueParts.length > 0) {
    return uniqueParts.join(' | ');
  }

  return t('admin.documents.publish_connection_error');
}

function formatPipelinePublishError(detail, t) {
  const pipelineRun = detail?.pipeline_run || {};
  const events = Array.isArray(detail?.events) ? detail.events : [];
  const failedEvent = [...events].reverse().find((event) => event.state === 'failed');
  const eventPayload = parsePayloadJson(failedEvent?.payload_json);
  const details = eventPayload || {};
  const parts = [];

  if (pipelineRun.error_message) parts.push(pipelineRun.error_message);
  if (failedEvent?.message && failedEvent.message !== pipelineRun.error_message) {
    parts.push(failedEvent.message);
  }
  if (details.message) parts.push(details.message);
  if (details.reason) parts.push(details.reason);
  if (details.type) parts.push(details.type);
  if (Array.isArray(details.cleanup_errors) && details.cleanup_errors.length > 0) {
    const cleanupMessages = details.cleanup_errors
      .map((item) => item.error || item.reason || item.message)
      .filter(Boolean);
    if (cleanupMessages.length > 0) {
      parts.push(`Cleanup: ${cleanupMessages.join('; ')}`);
    }
  }

  const uniqueParts = [...new Set(parts.filter(Boolean))];
  return uniqueParts.length > 0
    ? uniqueParts.join(' | ')
    : t('admin.documents.publish_connection_error');
}

function parsePayloadJson(raw) {
  if (!raw) return {};
  if (typeof raw === 'object') return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return {};
  }
}
