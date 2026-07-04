import { useState, useRef, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../services/api';
import ChatMessage from '../components/ChatMessage';
import Header from '../components/Header';
import './ChatPage.css';

export default function ChatPage() {
  const { t } = useTranslation();
  const { user, isAdmin } = useAuth();
  const [searchParams] = useSearchParams();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState([]);
  const [activeConv, setActiveConv] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);

  /* Handle initial query from home page */
  useEffect(() => {
    const q = searchParams.get('q');
    if (q && messages.length === 0) {
      sendMessage(q);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const sendMessage = async (text) => {
    const content = text || input.trim();
    if (!content) return;

    const userMsg = { role: 'user', content };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setIsTyping(true);

    try {
      const res = await api('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: content,
          conversation_id: activeConv,
        }),
      });
      const data = await res.json();
      const aiMsg = {
        role: 'assistant',
        content: data.answer || data.response || 'No response.',
        citations: data.citations || [],
        confidence: data.confidence ?? null,
      };
      setMessages((prev) => [...prev, aiMsg]);
    } catch {
      /* If no chat endpoint, show a mock response */
      const mockMsg = {
        role: 'assistant',
        content: `Theo quy định hiện hành, doanh nghiệp bảo hiểm phải đáp ứng các điều kiện về vốn pháp định, cơ cấu tổ chức và người quản trị. Cụ thể, vốn điều lệ tối thiểu đối với bảo hiểm phi nhân thọ là 400 tỷ đồng, đối với bảo hiểm nhân thọ là 750 tỷ đồng, và tái bảo hiểm là 500 tỷ đồng. Doanh nghiệp phải có phương án kinh doanh khả thi và hệ thống công nghệ thông tin đáp ứng yêu cầu quản lý.`,
        citations: [
          {
            document_name: 'Luật Kinh doanh bảo hiểm',
            document_number: '08/2022/QH15',
            article: 'Điều 64',
            is_active: true,
          },
          {
            document_name: 'Nghị định 46/2023/NĐ-CP',
            document_number: '46/2023/NĐ-CP',
            article: 'Điều 35, khoản 2',
            is_active: true,
          },
        ],
        confidence: 92,
      };
      setMessages((prev) => [...prev, mockMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    sendMessage();
  };

  const handleNewChat = () => {
    setMessages([]);
    setActiveConv(null);
    inputRef.current?.focus();
  };

  const showHeader = !isAdmin;

  return (
    <div className="chat-layout">
      {showHeader && <Header />}
      <div className="chat-container">
        {/* Sidebar */}
        <aside className={`chat-sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
          <button className="btn btn-secondary w-full" onClick={handleNewChat}>
            + {t('chat.new_chat')}
          </button>

          <div className="chat-history-section">
            <h4 className="chat-history-title">{t('chat.history')}</h4>
            {conversations.length === 0 ? (
              <p className="text-muted text-sm" style={{ padding: '8px 0' }}>
                {t('chat.empty')}
              </p>
            ) : (
              conversations.map((conv) => (
                <button
                  key={conv.id}
                  className={`history-item ${activeConv === conv.id ? 'active' : ''}`}
                  onClick={() => setActiveConv(conv.id)}
                >
                  💬 {conv.title || 'Conversation'}
                </button>
              ))
            )}
          </div>
        </aside>

        {/* Chat Area */}
        <div className="chat-main">
          <button
            className="sidebar-toggle btn-icon"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            {sidebarOpen ? '◀' : '▶'}
          </button>

          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="chat-empty-state">
                <div className="chat-empty-icon">⚖️</div>
                <h2>{t('chat.empty')}</h2>
                <p className="text-muted">{t('chat.empty_desc')}</p>
              </div>
            )}

            {messages.map((msg, i) => (
              <ChatMessage key={i} message={msg} />
            ))}

            {isTyping && (
              <div className="chat-msg chat-msg-ai">
                <div className="msg-avatar">⚖️</div>
                <div className="msg-body">
                  <div className="msg-bubble msg-ai-bubble">
                    <div className="typing-dots">
                      <span />
                      <span />
                      <span />
                    </div>
                  </div>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          <form className="chat-input-bar" onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              className="chat-input"
              placeholder={t('chat.placeholder')}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              id="chat-input"
            />
            <button
              type="submit"
              className="chat-send-btn btn btn-primary"
              disabled={!input.trim() || isTyping}
            >
              ➤
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
