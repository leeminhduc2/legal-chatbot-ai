import { useState, useRef, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import './Header.css';

export default function Header() {
  const { t, i18n } = useTranslation();
  const { theme, cycleTheme } = useTheme();
  const { user, isAuthenticated, isGuest, logout } = useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);
  const navigate = useNavigate();

  const themeIcon = theme === 'light' ? '☀️' : theme === 'dark' ? '🌙' : '💻';
  const langLabel = i18n.language === 'vi' ? '🇻🇳 VI' : '🇬🇧 EN';

  const toggleLang = () => {
    i18n.changeLanguage(i18n.language === 'vi' ? 'en' : 'vi');
  };

  const handleLogout = () => {
    setDropdownOpen(false);
    logout();
    navigate('/login');
  };

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const showNav = !user || user.role !== 'admin';

  return (
    <header className="app-header">
      <div className="header-inner">
        <Link to="/" className="header-logo">
          <div className="logo-icon">⚖️</div>
          <div className="logo-text">
            <span className="logo-name">{t('app.name')}</span>
            <span className="logo-subtitle">{t('app.subtitle')}</span>
          </div>
        </Link>

        {showNav && (
          <nav className="header-nav">
            <Link to="/" className="nav-link">{t('nav.home')}</Link>
            <Link to="/chat" className="nav-link">{t('nav.chat')}</Link>
          </nav>
        )}

        <div className="header-actions">
          <button
            className="btn-icon header-action-btn"
            onClick={cycleTheme}
            title={t(`theme.${theme}`)}
            aria-label="Toggle theme"
          >
            {themeIcon}
          </button>

          <button
            className="header-action-btn lang-btn"
            onClick={toggleLang}
            aria-label="Toggle language"
          >
            🌐 {langLabel}
          </button>

          {(isAuthenticated || isGuest) ? (
            <div className="avatar-wrapper" ref={dropdownRef}>
              <button
                className="avatar-btn"
                onClick={() => setDropdownOpen(!dropdownOpen)}
              >
                <div className="avatar-circle">
                  {user?.username?.[0]?.toUpperCase() || 'G'}
                </div>
                <div className="avatar-info">
                  <span className="avatar-name">{user?.username || 'Guest'}</span>
                  <span className="avatar-role">{t(`roles.${user?.role || 'guest'}`)}</span>
                </div>
                <span className="avatar-arrow">▾</span>
              </button>
              {dropdownOpen && (
                <div className="avatar-dropdown animate-slideDown">
                  <Link
                    to={user?.role === 'admin' ? '/admin/profile' : '/profile'}
                    className="dropdown-item"
                    onClick={() => setDropdownOpen(false)}
                  >
                    👤 {t('nav.profile')}
                  </Link>
                  <button className="dropdown-item" onClick={handleLogout}>
                    🚪 {t('nav.logout')}
                  </button>
                </div>
              )}
            </div>
          ) : (
            <Link to="/login" className="btn btn-primary btn-sm">
              {t('nav.login')}
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
