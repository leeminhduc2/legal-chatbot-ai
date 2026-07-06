import { useState } from 'react';
import Header from '../components/Header';
import { api } from '../services/api';
import './FeaturePage.css';

const COPY = {
  title: 'Ra soat hop dong',
  subtitle: 'Tai len file .docx de kiem tra tham quyen, hieu luc va rui ro phap ly so bo.',
  upload: 'File .docx',
  analyze: 'Phan tich',
  analyzing: 'Dang phan tich...',
  status: 'Trang thai',
  documentKind: 'Loai tai lieu',
  riskSummary: 'Tong quan rui ro',
  modules: 'Module ra soat',
  sections: 'Noi dung can chu y',
  citations: 'Can cu',
  toolTrace: 'Tool trace',
  noFindings: 'Chua co phat hien.',
  noCitations: 'Chua co citation.',
  recommendation: 'Khuyen nghi',
  evidence: 'Bang chung',
  chooseFile: 'Chon mot file .docx de bat dau.',
};

const STATUS_LABEL = {
  queued: 'Dang cho',
  running: 'Dang xu ly',
  completed: 'Hoan tat',
  failed: 'That bai',
};

const SEVERITY_CLASS = {
  high: 'badge-danger',
  medium: 'badge-warning',
  low: 'badge-info',
  info: 'badge-success',
  none: 'badge-muted',
};

export default function ContractReviewPage() {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');

  const handleAnalyze = async (event) => {
    event.preventDefault();
    if (!file || busy) return;

    setBusy(true);
    setError('');
    setJob(null);

    try {
      const form = new FormData();
      form.append('file', file);
      const response = await api('/contracts/review', { method: 'POST', body: form });
      const initialJob = await response.json();
      setJob(initialJob);

      const completedJob = await pollReviewJob(initialJob.job_id || initialJob.id);
      setJob(completedJob);
    } catch (err) {
      setError(err?.message || 'Khong the ra soat file nay.');
    } finally {
      setBusy(false);
    }
  };

  const result = job?.result || null;
  const modules = Array.isArray(result?.modules) ? result.modules : [];
  const sectionReviews = Array.isArray(result?.section_reviews) ? result.section_reviews : [];
  const citations = Array.isArray(result?.citations) ? result.citations : [];
  const toolTrace = Array.isArray(result?.tool_trace) ? result.tool_trace : [];
  const riskSummary = result?.risk_summary || null;

  return (
    <div className="home-layout">
      <Header />
      <main className="feature-page page-container animate-slideUp">
        <div className="page-header">
          <h1>{COPY.title}</h1>
          <p>{COPY.subtitle}</p>
        </div>

        <form className="feature-form card contract-review-form" onSubmit={handleAnalyze}>
          <div className="form-group">
            <label>{COPY.upload}</label>
            <input
              type="file"
              accept=".docx"
              onChange={(event) => setFile(event.target.files?.[0] || null)}
              disabled={busy}
            />
            {!file && <span className="text-muted text-sm">{COPY.chooseFile}</span>}
          </div>
          <button type="submit" className="btn btn-primary" disabled={busy || !file}>
            {busy ? <span className="spinner" /> : null}
            {busy ? COPY.analyzing : COPY.analyze}
          </button>
        </form>

        {error && <div className="review-error mt-md">{error}</div>}

        {job && (
          <div className="review-status-bar mt-lg">
            <div>
              <span className="text-muted text-sm">{COPY.status}</span>
              <strong>{STATUS_LABEL[job.status] || job.status}</strong>
            </div>
            <div>
              <span className="text-muted text-sm">{COPY.documentKind}</span>
              <strong>{result?.document?.kind || job.document_kind || '-'}</strong>
            </div>
            <div>
              <span className="text-muted text-sm">Job</span>
              <strong className="mono-text">{job.job_id || job.id}</strong>
            </div>
          </div>
        )}

        {riskSummary && (
          <section className="card mt-lg review-summary-card">
            <div className="review-card-header">
              <h3>{COPY.riskSummary}</h3>
              <span className={`badge ${SEVERITY_CLASS[riskSummary.overall] || 'badge-muted'}`}>
                {riskSummary.overall || 'none'}
              </span>
            </div>
            <div className="risk-count-grid">
              {Object.entries(riskSummary.counts || {}).map(([severity, count]) => (
                <div key={severity} className="risk-count-item">
                  <span className={`badge ${SEVERITY_CLASS[severity] || 'badge-muted'}`}>
                    {severity}
                  </span>
                  <strong>{count}</strong>
                </div>
              ))}
            </div>
          </section>
        )}

        {modules.length > 0 && (
          <section className="review-report mt-lg">
            <h2 className="review-section-title">{COPY.modules}</h2>
            <div className="review-module-grid">
              {modules.map((module) => (
                <ModuleCard key={module.module_id} module={module} />
              ))}
            </div>
          </section>
        )}

        {sectionReviews.length > 0 && (
          <section className="review-report mt-lg">
            <h2 className="review-section-title">{COPY.sections}</h2>
            <div className="review-section-list">
              {sectionReviews.map((section) => (
                <section key={section.section_id} className="card review-section-card">
                  <div className="review-card-header">
                    <h3>{section.title || section.section_id}</h3>
                    <span className="badge badge-muted">{section.findings?.length || 0}</span>
                  </div>
                  {section.content_preview && (
                    <p className="review-content-preview">{section.content_preview}</p>
                  )}
                  {(section.findings || []).map((finding, index) => (
                    <FindingItem key={`${finding.question_id}-${index}`} finding={finding} />
                  ))}
                </section>
              ))}
            </div>
          </section>
        )}

        {result && (
          <section className="review-report mt-lg">
            <div className="review-side-grid">
              <InfoList title={COPY.citations} items={citations} empty={COPY.noCitations} />
              <TraceList title={COPY.toolTrace} items={toolTrace} />
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

function ModuleCard({ module }) {
  const findings = Array.isArray(module.findings) ? module.findings : [];
  return (
    <section className="card review-module-card">
      <div className="review-card-header">
        <div>
          <h3>{module.title || module.module_id}</h3>
          <p className="text-muted text-sm">confidence {module.confidence ?? 0}</p>
        </div>
        <span className={`badge ${module.status === 'risk_found' ? 'badge-danger' : 'badge-info'}`}>
          {module.status}
        </span>
      </div>
      {findings.length === 0 ? (
        <p className="text-muted">{COPY.noFindings}</p>
      ) : (
        findings.map((finding, index) => (
          <FindingItem key={`${finding.question_id}-${index}`} finding={finding} />
        ))
      )}
    </section>
  );
}

function FindingItem({ finding }) {
  const evidence = Array.isArray(finding.evidence) ? finding.evidence : [];
  const citations = Array.isArray(finding.citations) ? finding.citations : [];
  return (
    <article className="review-finding">
      <div className="review-finding-top">
        <span className={`badge ${SEVERITY_CLASS[finding.severity] || 'badge-muted'}`}>
          {finding.severity || 'info'}
        </span>
        <strong>{finding.question_id}</strong>
        <span className="badge badge-muted">{finding.result}</span>
      </div>
      <p>{finding.reason}</p>
      {finding.recommendation && (
        <p className="review-recommendation">
          <strong>{COPY.recommendation}:</strong> {finding.recommendation}
        </p>
      )}
      {finding.article_status && (
        <p className="text-muted text-sm">
          article_status: {finding.article_status}. {finding.article_reason || ''}
        </p>
      )}
      {evidence.length > 0 && (
        <div className="review-mini-list">
          <strong>{COPY.evidence}</strong>
          {evidence.map((item, index) => (
            <span key={`${item}-${index}`}>{item}</span>
          ))}
        </div>
      )}
      {citations.length > 0 && (
        <div className="review-mini-list">
          <strong>{COPY.citations}</strong>
          {citations.map((citation, index) => (
            <span key={`${citation.citation_label}-${index}`}>
              {citation.citation_label || citation.document_number || citation.document_title}
            </span>
          ))}
        </div>
      )}
    </article>
  );
}

function InfoList({ title, items, empty }) {
  return (
    <section className="card review-info-card">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="text-muted">{empty}</p>
      ) : (
        <div className="review-mini-list">
          {items.map((item, index) => (
            <span key={`${item.citation_label || item.document_number || index}`}>
              {item.citation_label || item.document_number || item.document_title || 'Citation'}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function TraceList({ title, items }) {
  return (
    <section className="card review-info-card">
      <h3>{title}</h3>
      {items.length === 0 ? (
        <p className="text-muted">No trace.</p>
      ) : (
        <div className="review-trace-list">
          {items.map((item, index) => (
            <div key={`${item.tool}-${index}`} className="review-trace-row">
              <strong>{item.tool}</strong>
              <span>{item.phase}</span>
              <span>{item.status}</span>
              <span>{item.result_count}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

async function pollReviewJob(jobId) {
  if (!jobId) return null;
  let latest = null;
  for (let attempt = 0; attempt < 45; attempt += 1) {
    const response = await api(`/contracts/review/${jobId}`);
    latest = await response.json();
    if (latest.status === 'completed' || latest.status === 'failed') {
      return latest;
    }
    await sleep(1000);
  }
  return latest;
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}
