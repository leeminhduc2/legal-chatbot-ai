import { useState, useRef, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import toast from 'react-hot-toast';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../services/api';
import ChatMessage from '../components/ChatMessage';
import Header from '../components/Header';
import './ChatPage.css';

export default function ChatPage() {
  const { t } = useTranslation();
  const { isAdmin, isAuthenticated } = useAuth();
  const [searchParams] = useSearchParams();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [activeConv, setActiveConv] = useState(null);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const initialQuerySent = useRef(false);

  useEffect(() => {
    if (isAuthenticated) {
      loadConversations();
    } else {
      setConversations([]);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    const q = searchParams.get('q');
    if (q && !initialQuerySent.current) {
      initialQuerySent.current = true;
      sendMessage(q);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  const loadConversations = async () => {
    setHistoryLoading(true);
    try {
      const res = await api('/chat/conversations');
      const data = await res.json();
      setConversations(data.conversations || []);
    } catch (err) {
      toast.error(err.message || t('chat.history_error'));
    } finally {
      setHistoryLoading(false);
    }
  };

  const openConversation = async (conversationId) => {
    setHistoryLoading(true);
    try {
      const res = await api(`/chat/conversations/${conversationId}`);
      const data = await res.json();
      setActiveConv(data.conversation?.id || conversationId);
      setMessages(data.messages || []);
    } catch (err) {
      toast.error(err.message || t('chat.history_error'));
    } finally {
      setHistoryLoading(false);
    }
  };

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
        content: data.answer || data.response || t('chat.no_response'),
        citations: data.citations || [],
        confidence: data.confidence ?? null,
        warnings: data.warnings || [],
        retrieval_mode: data.retrieval_mode || null,
        trace_id: data.trace_id || null,
        agent_steps: data.agent_steps || [],
        tool_trace: data.tool_trace || [],
        memory_used: data.memory_used || null,
        agent_timeline: data.agent_timeline || [],
      };
      setMessages((prev) => [...prev, aiMsg]);
      if (data.conversation_id) {
        setActiveConv(data.conversation_id);
        loadConversations();
      }
    } catch (err) {
      toast.error(err.message || t('chat.send_error'));
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: t('chat.send_error'),
          citations: [],
          confidence: null,
        },
      ]);
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
        <aside className={`chat-sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
          <button className="btn btn-secondary w-full" onClick={handleNewChat}>
            + {t('chat.new_chat')}
          </button>

          <div className="chat-history-section">
            <h4 className="chat-history-title">{t('chat.history')}</h4>
            {!isAuthenticated ? (
              <div className="chat-history-login">
                <p className="text-muted text-sm">{t('chat.login_for_history')}</p>
                <Link to="/login" className="btn btn-primary btn-sm">
                  {t('nav.login')}
                </Link>
              </div>
            ) : historyLoading && conversations.length === 0 ? (
              <p className="text-muted text-sm" style={{ padding: '8px 0' }}>
                {t('chat.history_loading')}
              </p>
            ) : conversations.length === 0 ? (
              <p className="text-muted text-sm" style={{ padding: '8px 0' }}>
                {t('chat.empty')}
              </p>
            ) : (
              conversations.map((conv) => (
                <button
                  key={conv.id}
                  className={`history-item ${activeConv === conv.id ? 'active' : ''}`}
                  onClick={() => openConversation(conv.id)}
                >
                  {conv.title || 'Conversation'}
                </button>
              ))
            )}
          </div>
        </aside>

        <div className="chat-main">
          <button
            className="sidebar-toggle btn-icon"
            onClick={() => setSidebarOpen(!sidebarOpen)}
            type="button"
          >
            {sidebarOpen ? '<' : '>'}
          </button>

          <div className="chat-messages">
            {messages.length === 0 && (
              <div className="chat-empty-state">
                <div className="chat-empty-icon">AI</div>
                <h2>{t('chat.empty')}</h2>
                <p className="text-muted">{t('chat.empty_desc')}</p>
              </div>
            )}

            {messages.map((msg, i) => (
              <ChatMessage key={`${msg.id || 'local'}-${i}`} message={msg} />
            ))}

            {isTyping && (
              <div className="chat-msg chat-msg-ai">
                <div className="msg-avatar">AI</div>
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
              &gt;
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
