import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import './ChatMessage.css';

export default function ChatMessage({ message }) {
  const { t } = useTranslation();
  const [citationsOpen, setCitationsOpen] = useState(false);
  const [agentOpen, setAgentOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const isUser = message.role === 'user';
  const confidence = normalizeConfidence(message.confidence);
  const hasAgentTrace = message.agent_steps?.length > 0 || message.tool_trace?.length > 0;

  const handleCopy = () => {
    navigator.clipboard.writeText(message.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (isUser) {
    return (
      <div className="chat-msg chat-msg-user animate-slideUp">
        <div className="msg-bubble msg-user-bubble">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="chat-msg chat-msg-ai animate-slideUp">
      <div className="msg-avatar">⚖️</div>
      <div className="msg-body">
        <div className="msg-bubble msg-ai-bubble">
          <div className="msg-content">{message.content}</div>

          {message.warnings?.length > 0 && (
            <div className="msg-warnings">
              <div className="warnings-title">! {t('chat.warnings')}</div>
              {message.warnings.slice(0, 3).map((item, i) => (
                <div key={`${item.code || 'warning'}-${i}`} className="warning-item">
                  {item.message || item.code}
                </div>
              ))}
            </div>
          )}

          {message.citations?.length > 0 && (
            <div className="msg-citations">
              <button
                className="citations-toggle"
                onClick={() => setCitationsOpen(!citationsOpen)}
              >
                📎 {t('chat.citations')} ({message.citations.length})
                <span className={`toggle-arrow ${citationsOpen ? 'open' : ''}`}>▾</span>
              </button>
              {citationsOpen && (
                <div className="citations-list animate-slideDown">
                  {message.citations.map((cite, i) => (
                    <div key={i} className="citation-item">
                      <div className="citation-doc">
                        <span className="citation-name">
                          {cite.citation_label || cite.document_name || cite.document_title}
                        </span>
                        <span className="citation-number">
                          {cite.document_number || cite.document_id}
                        </span>
                        {(cite.article || cite.article_number) && (
                          <span className="citation-article">
                            {cite.article || `Dieu ${cite.article_number}`}
                          </span>
                        )}
                      </div>
                      <span className={`badge ${cite.is_active ? 'badge-success' : 'badge-danger'}`}>
                        {cite.is_active
                          ? t('chat.active')
                          : cite.validity_status === 'unknown'
                            ? t('chat.unknown')
                            : t('chat.expired')}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {hasAgentTrace && (
            <div className="msg-agent-trace">
              <button
                className="agent-trace-toggle"
                onClick={() => setAgentOpen(!agentOpen)}
              >
                {t('chat.agent_steps')} ({message.tool_trace?.length || message.agent_steps?.length || 0})
                <span className={`toggle-arrow ${agentOpen ? 'open' : ''}`}>v</span>
              </button>
              {agentOpen && (
                <div className="agent-trace-panel animate-slideDown">
                  {message.memory_used && (
                    <div className="agent-memory">
                      {t('chat.memory_used')}: {message.memory_used.recent_message_count || 0}
                      {message.memory_used.summary_used ? `, ${t('chat.summary_used')}` : ''}
                    </div>
                  )}
                  {message.agent_steps?.map((step, i) => (
                    <div key={`step-${i}`} className="agent-step-item">
                      <span className={`agent-status agent-status-${step.status || 'ok'}`}>
                        {step.status || 'ok'}
                      </span>
                      <span className="agent-phase">{step.phase}</span>
                      <span className="agent-message">{step.message}</span>
                    </div>
                  ))}
                  {message.tool_trace?.map((trace, i) => (
                    <div key={`tool-${i}`} className="agent-tool-item">
                      <div className="agent-tool-header">
                        <span className="agent-tool-name">{trace.tool}</span>
                        <span className="agent-tool-meta">
                          {trace.phase} - {trace.result_count || 0} {t('chat.results')} - {trace.duration_ms || 0}ms
                        </span>
                      </div>
                      {trace.input_summary && (
                        <div className="agent-tool-input">{trace.input_summary}</div>
                      )}
                      {trace.warnings?.length > 0 && (
                        <div className="agent-tool-warning">
                          {trace.warnings.slice(0, 2).join(', ')}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {confidence != null && (
            <div className="msg-confidence">
              <span className="confidence-label">{t('chat.confidence')}:</span>
              <div className="confidence-bar">
                <div
                  className="confidence-fill"
                  style={{ width: `${confidence}%` }}
                />
              </div>
              <span className="confidence-value">{confidence}%</span>
            </div>
          )}
        </div>

        <div className="msg-actions">
          <button className="msg-action-btn" onClick={handleCopy} title={t('chat.copy')}>
            {copied ? '✅' : '📋'}
          </button>
          <button className="msg-action-btn" title="👍">👍</button>
          <button className="msg-action-btn" title="👎">👎</button>
          <button className="msg-action-btn" title="⭐">⭐</button>
        </div>
      </div>
    </div>
  );
}

function normalizeConfidence(value) {
  if (value == null) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  const percent = numeric <= 1 ? numeric * 100 : numeric;
  return Math.max(0, Math.min(100, Math.round(percent)));
}
