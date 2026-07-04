import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import './ChatMessage.css';

export default function ChatMessage({ message }) {
  const { t } = useTranslation();
  const [citationsOpen, setCitationsOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const isUser = message.role === 'user';

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
                        <span className="citation-name">{cite.document_name}</span>
                        <span className="citation-number">{cite.document_number}</span>
                        {cite.article && (
                          <span className="citation-article">{cite.article}</span>
                        )}
                      </div>
                      <span className={`badge ${cite.is_active ? 'badge-success' : 'badge-danger'}`}>
                        {cite.is_active ? t('chat.active') : t('chat.expired')}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {message.confidence != null && (
            <div className="msg-confidence">
              <span className="confidence-label">{t('chat.confidence')}:</span>
              <div className="confidence-bar">
                <div
                  className="confidence-fill"
                  style={{ width: `${message.confidence}%` }}
                />
              </div>
              <span className="confidence-value">{message.confidence}%</span>
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
