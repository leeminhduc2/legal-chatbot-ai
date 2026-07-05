import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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

const RELATION_TYPES = [
  'guided_by', 'guides', 'detailed_and_guided_by', 'details_and_guides',
  'consolidated_by', 'consolidates', 'amended_by', 'amends', 'corrected_by',
  'corrects', 'replaced_by', 'replaces', 'repealed_by', 'repeals',
  'referenced_by', 'references', 'based_on', 'interpreted_by', 'interprets',
  'applies', 'suspended_by', 'suspends', 'temporarily_suspended_by',
  'temporarily_suspends', 'published_by', 'publishes',
];

const RELATION_TYPE_SET = new Set(RELATION_TYPES);
const DETAIL_TABS = ['metadata', 'chunks', 'relations'];
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
  const [metadataDraft, setMetadataDraft] = useState({});
  const [initialMetadata, setInitialMetadata] = useState({});
  const [chunksDraft, setChunksDraft] = useState([]);
  const [initialChunks, setInitialChunks] = useState([]);
  const [relationsDraft, setRelationsDraft] = useState([]);
  const [initialRelations, setInitialRelations] = useState([]);
  const [expandedRelations, setExpandedRelations] = useState({});
  const [relationInputs, setRelationInputs] = useState({});
  const [editingChunkIndex, setEditingChunkIndex] = useState(null);
  const [chunkEditText, setChunkEditText] = useState('');
  const [saving, setSaving] = useState(false);
  const [publishingDocId, setPublishingDocId] = useState('');
  const [publishingRunId, setPublishingRunId] = useState('');

  const applyDetail = useCallback((detail, tab = activeTab) => {
    const nextMetadata = { ...(detail.document || {}) };
    const nextChunks = Array.isArray(detail.chunks) ? detail.chunks : [];
    const nextRelations = Array.isArray(detail.relations) ? detail.relations : [];
    setSelected(detail);
    setMetadataDraft(nextMetadata);
    setInitialMetadata(nextMetadata);
    setChunksDraft(nextChunks);
    setInitialChunks(nextChunks);
    setRelationsDraft(nextRelations);
    setInitialRelations(nextRelations);
    setEditingChunkIndex(null);
    setChunkEditText('');
    setRelationInputs({});
    setActiveTab(tab);
  }, [activeTab]);

  const loadDocuments = useCallback(async ({ reset = false, isStale = () => false } = {}) => {
    setLoading(true);
    if (reset) {
      setDocuments([]);
      setSelected(null);
      setActiveTab('metadata');
      setMetadataDraft({});
      setInitialMetadata({});
      setChunksDraft([]);
      setInitialChunks([]);
      setRelationsDraft([]);
      setInitialRelations([]);
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

  const dirtyTabs = useMemo(() => ({
    metadata: !sameJson(metadataDraft, initialMetadata),
    chunks: !sameJson(chunksDraft, initialChunks),
    relations: !sameJson(relationsDraft, initialRelations),
  }), [chunksDraft, initialChunks, initialMetadata, initialRelations, metadataDraft, relationsDraft]);

  const lockedTab = DETAIL_TABS.find((tab) => dirtyTabs[tab]) || '';
  const hasUnsavedChanges = Boolean(lockedTab);
  const publishBlockers = selected?.publish_blockers || [];
  const selectedDocumentId = selected?.document?.document_id || '';
  const reviewFields = useMemo(
    () => new Set(selected?.needs_review_fields || []),
    [selected]
  );

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
      applyDetail(detail, 'metadata');
    } catch (err) {
      toast.error(err.message);
    }
  };

  const closeDetail = () => {
    if (hasUnsavedChanges) {
      toast.error(t('admin.documents.unsaved_lock'));
      return;
    }
    setSelected(null);
  };

  const handleTabClick = (tab) => {
    if (lockedTab && lockedTab !== tab) {
      toast.error(t('admin.documents.unsaved_lock'));
      return;
    }
    setActiveTab(tab);
  };

  const resetActiveDraft = () => {
    if (activeTab === 'metadata') {
      setMetadataDraft({ ...initialMetadata });
    } else if (activeTab === 'chunks') {
      setChunksDraft(cloneJson(initialChunks));
      setEditingChunkIndex(null);
      setChunkEditText('');
    } else if (activeTab === 'relations') {
      setRelationsDraft(cloneJson(initialRelations));
      setRelationInputs({});
    }
  };

  const saveMetadata = async () => {
    setSaving(true);
    try {
      const body = {};
      METADATA_FIELDS.forEach((key) => { body[key] = metadataDraft[key] || ''; });
      const suffix = isPublishedPage ? '?auto_publish=1' : '';
      const res = await api(`/admin/documents/${selected.document.document_id}/metadata${suffix}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      applyDetail(await res.json(), 'metadata');
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
      const suffix = isPublishedPage ? '?auto_publish=1' : '';
      const res = await api(`/admin/documents/${selected.document.document_id}/chunks${suffix}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ chunks: chunksDraft }),
      });
      applyDetail(await res.json(), 'chunks');
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
      const suffix = isPublishedPage ? '?auto_publish=1' : '';
      const res = await api(`/admin/documents/${selected.document.document_id}/relationships${suffix}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ relations: relationsDraft }),
      });
      applyDetail(await res.json(), 'relations');
      toast.success(t('admin.documents.saved'));
      loadDocuments();
    } catch (err) {
      toast.error(formatRelationshipSaveError(err, t), { duration: 7000 });
    } finally {
      setSaving(false);
    }
  };

  const handlePublish = async (docId) => {
    if (publishingDocId || hasUnsavedChanges) {
      if (hasUnsavedChanges) toast.error(t('admin.documents.unsaved_lock'));
      return;
    }
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

  const startEditChunk = (index) => {
    setEditingChunkIndex(index);
    setChunkEditText(chunksDraft[index]?.content || '');
  };

  const applyChunkEdit = () => {
    if (editingChunkIndex === null) return;
    setChunksDraft((chunks) => chunks.map((chunk, index) => (
      index === editingChunkIndex ? { ...chunk, content: chunkEditText } : chunk
    )));
    setEditingChunkIndex(null);
    setChunkEditText('');
  };

  const deleteChunk = (index) => {
    const chunk = chunksDraft[index];
    const label = chunk?.hierarchy_path || chunk?.citation_label || `#${index + 1}`;
    if (!window.confirm(`${t('admin.documents.confirm_delete_chunk')} ${label}?`)) return;
    setChunksDraft((chunks) => chunks.filter((_, itemIndex) => itemIndex !== index));
    if (editingChunkIndex === index) {
      setEditingChunkIndex(null);
      setChunkEditText('');
    }
  };

  const addRelation = (relationType) => {
    const targetDocumentNumber = (relationInputs[relationType] || '').trim();
    if (!targetDocumentNumber) {
      toast.error(t('admin.documents.relationship_target_required'));
      return;
    }
    setRelationsDraft((relations) => [
      ...relations,
      {
        relation_type: relationType,
        target_document_number: targetDocumentNumber,
        target_document_id: null,
        source_text: '',
      },
    ]);
    setRelationInputs((inputs) => ({ ...inputs, [relationType]: '' }));
    setExpandedRelations((expanded) => ({ ...expanded, [relationType]: true }));
  };

  const deleteRelation = (relationIndex) => {
    const relation = relationsDraft[relationIndex];
    const target = relation?.target_document_number || relation?.target_document_id || '';
    if (!window.confirm(`${t('admin.documents.confirm_delete_relationship')} ${target}?`)) return;
    setRelationsDraft((relations) => relations.filter((_, index) => index !== relationIndex));
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return documents;
    const q = search.toLowerCase();
    return documents.filter((doc) =>
      (doc.title || '').toLowerCase().includes(q) ||
      (doc.document_number || '').toLowerCase().includes(q)
    );
  }, [documents, search]);

  const groupedRelations = useMemo(
    () => groupRelations(relationsDraft),
    [relationsDraft]
  );

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
          onChange={(event) => setSearch(event.target.value)}
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
            {filtered.map((doc, index) => (
              <tr key={doc.document_id}>
                <td>{index + 1}</td>
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
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDownload(doc.document_id, doc.document_number)} title={t('admin.documents.download')}>DL</button>
                    <button className="btn btn-ghost btn-sm" onClick={() => openDetail(doc.document_id)} title={t('admin.documents.edit')}>{t('admin.documents.edit')}</button>
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
                        {t('admin.documents.publish')}
                      </button>
                    )}
                    <button className="btn btn-ghost btn-sm" onClick={() => handleDelete(doc.document_id, doc.title)} title={t('admin.documents.delete')}>{t('admin.documents.delete')}</button>
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

      <Modal
        isOpen={!!selected}
        onClose={closeDetail}
        title={selected?.document?.title || 'Document'}
        width="1100px"
        closeDisabled={hasUnsavedChanges}
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
        {hasUnsavedChanges && (
          <div className="admin-warning detail-dirty-banner">
            {t('admin.documents.unsaved_lock')}
          </div>
        )}

        <div className="tabs">
          {DETAIL_TABS.map((tab) => {
            const disabled = Boolean(lockedTab && lockedTab !== tab);
            return (
              <button
                key={tab}
                type="button"
                className={`tab-btn ${activeTab === tab ? 'active' : ''}`}
                onClick={() => handleTabClick(tab)}
                disabled={disabled}
                title={disabled ? t('admin.documents.unsaved_lock') : ''}
              >
                {t(`admin.documents.${tab === 'relations' ? 'relations' : tab === 'chunks' ? 'chunks_tab' : 'metadata'}`)}
              </button>
            );
          })}
        </div>

        {activeTab === 'metadata' && (
          <div className="detail-tab-pane">
            <div className="metadata-grid">
              {METADATA_FIELDS.map((key) => (
                <div key={key} className={`form-group ${reviewFields.has(key) ? 'needs-review' : ''}`}>
                  <label>{t(`admin.import.fields.${key}`)}</label>
                  {key === 'validity_status' ? (
                    <select
                      value={metadataDraft[key] || 'active'}
                      onChange={(event) => setMetadataDraft({ ...metadataDraft, [key]: event.target.value })}
                    >
                      {VALIDITY_OPTIONS.map((value) => (
                        <option key={value} value={value}>{t(`validity.${value}`)}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      value={metadataDraft[key] || ''}
                      onChange={(event) => setMetadataDraft({ ...metadataDraft, [key]: event.target.value })}
                    />
                  )}
                </div>
              ))}
            </div>
            <DetailSaveBar
              dirty={dirtyTabs.metadata}
              saving={saving}
              onReset={resetActiveDraft}
              onSave={saveMetadata}
              t={t}
            />
          </div>
        )}

        {activeTab === 'chunks' && (
          <div className="detail-tab-pane">
            <div className="detail-table-wrap">
              <table className="detail-table chunks-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{t('admin.documents.hierarchy_path')}</th>
                    <th>{t('admin.documents.content')}</th>
                    <th>{t('admin.documents.actions')}</th>
                  </tr>
                </thead>
                <tbody>
                  {chunksDraft.map((chunk, index) => (
                    <tr key={chunk.chunk_id || `${chunk.hierarchy_path}-${index}`}>
                      <td>{index + 1}</td>
                      <td className="chunk-path">{chunk.hierarchy_path || '-'}</td>
                      <td>
                        {editingChunkIndex === index ? (
                          <textarea
                            className="chunk-edit-textarea"
                            value={chunkEditText}
                            onChange={(event) => setChunkEditText(event.target.value)}
                          />
                        ) : (
                          <div className="chunk-content-preview">{chunk.content || '-'}</div>
                        )}
                      </td>
                      <td>
                        <div className="table-actions">
                          {editingChunkIndex === index ? (
                            <>
                              <button type="button" className="btn btn-primary btn-sm" onClick={applyChunkEdit}>{t('admin.documents.apply')}</button>
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditingChunkIndex(null)}>{t('admin.documents.cancel')}</button>
                            </>
                          ) : (
                            <>
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => startEditChunk(index)}>{t('admin.documents.edit')}</button>
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => deleteChunk(index)}>{t('admin.documents.delete')}</button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {chunksDraft.length === 0 && (
                    <tr>
                      <td colSpan="4" className="text-center text-muted">{t('admin.documents.no_chunks')}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            <DetailSaveBar
              dirty={dirtyTabs.chunks}
              saving={saving}
              onReset={resetActiveDraft}
              onSave={saveChunks}
              t={t}
            />
          </div>
        )}

        {activeTab === 'relations' && (
          <div className="detail-tab-pane">
            <div className="relationship-list">
              {[...RELATION_TYPES, 'other'].map((relationType) => {
                const relations = groupedRelations[relationType] || [];
                if (relationType === 'other' && relations.length === 0) return null;
                const expanded = Boolean(expandedRelations[relationType]);
                return (
                  <div className="relationship-group" key={relationType}>
                    <button
                      type="button"
                      className="relationship-toggle"
                      onClick={() => setExpandedRelations((items) => ({ ...items, [relationType]: !expanded }))}
                    >
                      <span>{relationType === 'other' ? t('admin.documents.other_relationships') : relationType}</span>
                      <span className="badge badge-muted">{relations.length}</span>
                    </button>
                    {expanded && (
                      <div className="relationship-panel">
                        {relationType !== 'other' && (
                          <div className="relationship-add-row">
                            <input
                              value={relationInputs[relationType] || ''}
                              onChange={(event) => setRelationInputs((items) => ({ ...items, [relationType]: event.target.value }))}
                              placeholder={t('admin.documents.target_document_number')}
                            />
                            <button type="button" className="btn btn-primary btn-sm" onClick={() => addRelation(relationType)}>
                              {t('admin.documents.add')}
                            </button>
                          </div>
                        )}
                        <div className="relationship-items">
                          {relations.map(({ relation, index }) => (
                            <div className="relationship-item" key={relation.id || `${relation.relation_type}-${relation.target_document_number}-${index}`}>
                              <div className="relationship-target">
                                <strong>{relation.target_document_number || relation.target_document_id || '-'}</strong>
                                {relation.source_text && <span>{relation.source_text}</span>}
                              </div>
                              <button type="button" className="btn btn-ghost btn-sm" onClick={() => deleteRelation(index)}>
                                {t('admin.documents.delete')}
                              </button>
                            </div>
                          ))}
                          {relations.length === 0 && (
                            <div className="text-muted text-sm">{t('admin.documents.no_relationships')}</div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
            <DetailSaveBar
              dirty={dirtyTabs.relations}
              saving={saving}
              onReset={resetActiveDraft}
              onSave={saveRelations}
              t={t}
            />
          </div>
        )}
        {!isPublishedPage && selectedDocumentId && (
          <div className="flex justify-end mt-lg">
            <button
              className="btn btn-primary"
              onClick={() => handlePublish(selectedDocumentId)}
              disabled={publishBlockers.length > 0 || publishingDocId === selectedDocumentId || hasUnsavedChanges}
              title={hasUnsavedChanges ? t('admin.documents.unsaved_lock') : ''}
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

function DetailSaveBar({ dirty, saving, onReset, onSave, t }) {
  return (
    <div className="detail-save-bar">
      <button type="button" className="btn btn-ghost" onClick={onReset} disabled={!dirty || saving}>
        {t('admin.documents.revert')}
      </button>
      <button type="button" className="btn btn-primary" onClick={onSave} disabled={!dirty || saving}>
        {saving ? <span className="spinner" /> : null} {t('admin.documents.save')}
      </button>
    </div>
  );
}

function groupRelations(relations) {
  const groups = Object.fromEntries(RELATION_TYPES.map((type) => [type, []]));
  groups.other = [];
  relations.forEach((relation, index) => {
    const type = relation?.relation_type || 'other';
    const groupKey = RELATION_TYPE_SET.has(type) ? type : 'other';
    groups[groupKey].push({ relation, index });
  });
  return groups;
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function cloneJson(value) {
  return JSON.parse(JSON.stringify(value));
}

function formatRelationshipSaveError(err, t) {
  if (err?.code === 'RELATION_TARGET_NOT_FOUND') {
    const target = err?.details?.target_document_number;
    return target
      ? `${t('admin.documents.relationship_target_not_found')}: ${target}`
      : t('admin.documents.relationship_target_not_found');
  }
  return err.message;
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
