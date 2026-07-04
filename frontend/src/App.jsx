import { useEffect, useMemo, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api/v1";
const METADATA_FIELDS = [
  ["title", "Ten van ban"],
  ["document_number", "So hieu"],
  ["document_type", "Loai van ban"],
  ["issued_date", "Ngay ban hanh"],
  ["effective_date", "Ngay thi hanh"],
  ["expiry_date", "Ngay het hieu luc"],
  ["validity_status", "Trang thai"],
  ["issuing_body", "Co quan ban hanh"],
  ["signer_title", "Chuc danh nguoi ky"],
  ["signer_name", "Nguoi ky"]
];
const VALIDITY_STATUS_OPTIONS = [
  ["active", "Active"],
  ["partially_expired", "Partially expired"],
  ["expired", "Fully expired"],
  ["not_yet_effective", "Not yet effective"],
  ["suspended", "Suspended"],
  ["revoked", "Revoked"],
  ["unknown", "Unknown"]
];

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("adminToken") || "");
  const [loginForm, setLoginForm] = useState({ username: "admin", password: "" });
  const [documents, setDocuments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [activeTab, setActiveTab] = useState("metadata");
  const [uploadFile, setUploadFile] = useState(null);
  const [isLegalDocument, setIsLegalDocument] = useState(true);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (token) {
      loadDocuments();
    }
  }, [token]);

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (!response.ok) {
      let errorMessage = `HTTP ${response.status}`;
      try {
        const body = await response.json();
        errorMessage = body?.error?.message || body?.error?.code || errorMessage;
      } catch {
        // Keep the HTTP fallback.
      }
      throw new Error(errorMessage);
    }
    return response;
  }

  async function login(event) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(loginForm)
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message || "Login failed");
      localStorage.setItem("adminToken", body.access_token);
      setToken(body.access_token);
      setMessage("Da dang nhap.");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function loadDocuments() {
    setBusy(true);
    try {
      const response = await api("/admin/documents");
      const body = await response.json();
      setDocuments(body.documents || []);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function uploadDocument(event) {
    event.preventDefault();
    if (!uploadFile) {
      setMessage("Chon file DOCX truoc khi upload.");
      return;
    }
    const form = new FormData();
    form.append("file", uploadFile);
    form.append("is_legal_document", isLegalDocument ? "true" : "false");
    setBusy(true);
    setMessage("");
    try {
      await api("/admin/documents/import", { method: "POST", body: form });
      setUploadFile(null);
      event.target.reset();
      setMessage("Da import DOCX va dua vao hang review.");
      await loadDocuments();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function openEditor(documentId) {
    setBusy(true);
    setMessage("");
    try {
      const response = await api(`/admin/documents/${documentId}`);
      setSelected(await response.json());
      setActiveTab("metadata");
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function downloadDocument(documentId, fallbackName) {
    setBusy(true);
    try {
      const response = await api(`/admin/documents/${documentId}/download`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${fallbackName || "document"}.docx`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function deleteDocument(documentId, title) {
    if (!window.confirm(`Xoa vinh vien "${title || documentId}"?`)) return;
    setBusy(true);
    try {
      await api(`/admin/documents/${documentId}`, { method: "DELETE" });
      setSelected(null);
      setMessage("Da xoa document.");
      await loadDocuments();
    } catch (error) {
      setMessage(error.message);
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    localStorage.removeItem("adminToken");
    setToken("");
    setDocuments([]);
    setSelected(null);
  }

  if (!token) {
    return (
      <main className="login-shell">
        <form className="login-panel" onSubmit={login}>
          <h1>Legal Admin</h1>
          <label>
            Username
            <input
              value={loginForm.username}
              onChange={(event) => setLoginForm({ ...loginForm, username: event.target.value })}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={loginForm.password}
              onChange={(event) => setLoginForm({ ...loginForm, password: event.target.value })}
            />
          </label>
          <button disabled={busy} type="submit">Dang nhap</button>
          {message ? <p className="status">{message}</p> : null}
        </form>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <h1>Document Admin</h1>
          <p>{documents.length} van ban trong registry</p>
        </div>
        <div className="topbar-actions">
          <button onClick={loadDocuments} disabled={busy}>Tai lai</button>
          <button className="secondary" onClick={logout}>Dang xuat</button>
        </div>
      </header>

      <section className="workspace">
        <aside className="upload-panel">
          <h2>Upload DOCX</h2>
          <form onSubmit={uploadDocument}>
            <label className="file-picker">
              File DOCX
              <input
                type="file"
                accept=".docx"
                onChange={(event) => setUploadFile(event.target.files?.[0] || null)}
              />
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={isLegalDocument}
                onChange={(event) => setIsLegalDocument(event.target.checked)}
              />
              Van ban phap luat
            </label>
            <button disabled={busy} type="submit">Upload</button>
          </form>
          {message ? <p className="status">{message}</p> : null}
        </aside>

        <section className="document-area">
          <DocumentTable
            documents={documents}
            onEdit={openEditor}
            onDownload={downloadDocument}
            onDelete={deleteDocument}
          />
        </section>
      </section>

      {selected ? (
        <EditorModal
          detail={selected}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          onClose={() => setSelected(null)}
          onSaved={(detail) => {
            setSelected(detail);
            loadDocuments();
          }}
          api={api}
        />
      ) : null}
    </main>
  );
}

function DocumentTable({ documents, onEdit, onDownload, onDelete }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>STT</th>
            <th>Ten van ban</th>
            <th>So hieu</th>
            <th>So chunk</th>
            <th>Review</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document, index) => (
            <tr key={document.document_id}>
              <td>{index + 1}</td>
              <td className="title-cell">{document.title || "Untitled"}</td>
              <td>{document.document_number || "-"}</td>
              <td>{document.chunk_count ?? 0}</td>
              <td>
                <span className={document.needs_review ? "pill warn" : "pill ok"}>
                  {document.needs_review ? "Can review" : "OK"}
                </span>
              </td>
              <td>
                <div className="row-actions">
                  <button onClick={() => onDownload(document.document_id, document.document_number)}>
                    Tai xuong
                  </button>
                  <button onClick={() => onEdit(document.document_id)}>Sua</button>
                  <button className="danger" onClick={() => onDelete(document.document_id, document.title)}>
                    Xoa
                  </button>
                </div>
              </td>
            </tr>
          ))}
          {!documents.length ? (
            <tr>
              <td colSpan="6" className="empty">Chua co document.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

function EditorModal({ detail, activeTab, setActiveTab, onClose, onSaved, api }) {
  const [metadata, setMetadata] = useState(() => ({ ...detail.document }));
  const [chunksText, setChunksText] = useState(() => JSON.stringify(detail.chunks || [], null, 2));
  const [relationsText, setRelationsText] = useState(() => JSON.stringify(detail.relations || [], null, 2));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const reviewFields = useMemo(() => new Set(detail.needs_review_fields || []), [detail]);

  async function saveMetadata() {
    await save(async () => {
      const body = {};
      for (const [key] of METADATA_FIELDS) body[key] = metadata[key] || "";
      const response = await api(`/admin/documents/${detail.document.document_id}/metadata`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      onSaved(await response.json());
    });
  }

  async function saveChunks() {
    await save(async () => {
      const chunks = JSON.parse(chunksText);
      const response = await api(`/admin/documents/${detail.document.document_id}/chunks`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunks })
      });
      onSaved(await response.json());
    });
  }

  async function saveRelations() {
    await save(async () => {
      const relations = JSON.parse(relationsText);
      const response = await api(`/admin/documents/${detail.document.document_id}/relationships`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ relations })
      });
      onSaved(await response.json());
    });
  }

  async function save(action) {
    setSaving(true);
    setError("");
    try {
      await action();
    } catch (saveError) {
      setError(saveError.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-backdrop">
      <section className="modal">
        <header className="modal-header">
          <div>
            <h2>{detail.document.title || "Document"}</h2>
            <p>{detail.document.document_number || detail.document.document_id}</p>
          </div>
          <button className="secondary" onClick={onClose}>Dong</button>
        </header>

        <nav className="tabs">
          {["metadata", "chunks", "relationship"].map((tab) => (
            <button
              key={tab}
              className={activeTab === tab ? "active" : ""}
              onClick={() => setActiveTab(tab)}
            >
              {tab === "metadata" ? "Metadata" : tab === "chunks" ? "Chunks" : "Relationship"}
            </button>
          ))}
        </nav>

        {activeTab === "metadata" ? (
          <div className="metadata-grid">
            {METADATA_FIELDS.map(([key, label]) => (
              <label key={key} className={reviewFields.has(key) ? "needs-review" : ""}>
                {label}
                {key === "validity_status" ? (
                  <select
                    value={metadata[key] || "active"}
                    onChange={(event) => setMetadata({ ...metadata, [key]: event.target.value })}
                  >
                    {VALIDITY_STATUS_OPTIONS.map(([value, optionLabel]) => (
                      <option key={value} value={value}>{optionLabel}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    value={metadata[key] || ""}
                    onChange={(event) => setMetadata({ ...metadata, [key]: event.target.value })}
                  />
                )}
              </label>
            ))}
            <button disabled={saving} onClick={saveMetadata}>Luu metadata</button>
          </div>
        ) : null}

        {activeTab === "chunks" ? (
          <div className="editor-pane">
            <textarea value={chunksText} onChange={(event) => setChunksText(event.target.value)} />
            <button disabled={saving} onClick={saveChunks}>Luu chunks</button>
          </div>
        ) : null}

        {activeTab === "relationship" ? (
          <div className="editor-pane">
            <textarea value={relationsText} onChange={(event) => setRelationsText(event.target.value)} />
            <button disabled={saving} onClick={saveRelations}>Luu relationship</button>
          </div>
        ) : null}

        {error ? <p className="status error">{error}</p> : null}
      </section>
    </div>
  );
}
