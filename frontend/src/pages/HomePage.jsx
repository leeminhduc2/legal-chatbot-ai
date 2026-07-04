import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import FeatureCard from '../components/FeatureCard';
import Header from '../components/Header';
import './HomePage.css';

export default function HomePage() {
  const { t } = useTranslation();
  const { user, isGuest, isBusinessUser, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');

  const handleSend = (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    navigate(`/chat?q=${encodeURIComponent(query.trim())}`);
  };

  const handleSuggestion = (text) => {
    navigate(`/chat?q=${encodeURIComponent(text)}`);
  };

  const suggestions = t('home.suggestions', { returnObjects: true });

  const features = [
    { key: 'draft_document', to: '/draft-document' },
    { key: 'draft_contract', to: '/draft-contract' },
    { key: 'contract_review', to: '/contract-review' },
    { key: 'risk_alerts', to: '/risk-alerts' },
  ];

  return (
    <div className="home-layout">
      <Header />
      <main className="home-main">
        {/* Hero Section */}
        <section className="hero-section">
          <div className="hero-content animate-fadeIn">
            {(isAuthenticated || isGuest) && user && (
              <div className="hero-greeting">
                <span className="greeting-badge">
                  <span className="greeting-avatar">
                    {user.username?.[0]?.toUpperCase() || 'G'}
                  </span>
                  {t('home.greeting')} {user.username || 'Guest'}
                </span>
                <span className="hero-badge badge-gold">✨ {t('home.hero_badge')}</span>
              </div>
            )}

            <h1 className="hero-title">
              {t('home.hero_title')}{' '}
              <span className="hero-ai-text">{t('home.hero_ai')}</span>
            </h1>

            <p className="hero-desc">{t('home.hero_desc')}</p>

            {/* Chat Input */}
            <form className="hero-chat-form" onSubmit={handleSend}>
              <div className="hero-chat-input-wrap">
                <input
                  type="text"
                  className="hero-chat-input"
                  placeholder={t('home.chat_placeholder')}
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  id="home-chat-input"
                />
                <button type="submit" className="btn btn-primary hero-send-btn">
                  {t('home.send')} →
                </button>
              </div>
            </form>

            {/* Suggestions */}
            <div className="hero-suggestions">
              {Array.isArray(suggestions) && suggestions.map((s, i) => (
                <button
                  key={i}
                  className="suggestion-chip"
                  onClick={() => handleSuggestion(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        </section>

        {/* Guest Banner */}
        {isGuest && (
          <div className="guest-banner animate-slideUp">
            🔒 {t('home.login_banner')}
          </div>
        )}

        {/* Advanced Features (business user only) */}
        {(isBusinessUser || isAuthenticated) && user?.role !== 'admin' && (
          <section className="features-section animate-slideUp">
            <div className="features-header">
              <h2>{t('home.advanced_title')}</h2>
              <span className="text-muted text-sm">{t('home.advanced_subtitle')}</span>
            </div>
            <div className="features-grid">
              {features.map((f) => (
                <FeatureCard
                  key={f.key}
                  icon={t(`features.${f.key}.icon`)}
                  title={t(`features.${f.key}.title`)}
                  description={t(`features.${f.key}.desc`)}
                  to={f.to}
                />
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
