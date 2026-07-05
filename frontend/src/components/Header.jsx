import { useState, useRef, useEffect } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useTheme } from '../contexts/ThemeContext';
import { useAuth } from '../contexts/AuthContext';
import logo from '../assets/logo.png';
import './Header.css';

/* ── Inline SVG Icons ── */
const SunIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="5" />
    <line x1="12" y1="1" x2="12" y2="3" />
    <line x1="12" y1="21" x2="12" y2="23" />
    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
    <line x1="1" y1="12" x2="3" y2="12" />
    <line x1="21" y1="12" x2="23" y2="12" />
    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
  </svg>
);

const MoonIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
  </svg>
);

const MonitorIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
    <line x1="8" y1="21" x2="16" y2="21" />
    <line x1="12" y1="17" x2="12" y2="21" />
  </svg>
);

const GlobeIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="2" y1="12" x2="22" y2="12" />
    <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
  </svg>
);

const THEME_ICONS = {
  light: <SunIcon />,
  dark: <MoonIcon />,
  system: <MonitorIcon />,
};

export default function Header() {
  const { t, i18n } = useTranslation();
  const { theme, cycleTheme } = useTheme();
  const { user, isAuthenticated, isGuest, logout } = useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);
  const navigate = useNavigate();

  const langLabel = i18n.language === 'vi' ? 'VI' : 'EN';

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
          <img className="logo-image" src={logo} alt={t('app.name')} />
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
            type="button"
          >
            {THEME_ICONS[theme]}
          </button>

          <button
            className="header-action-btn lang-btn"
            onClick={toggleLang}
            aria-label="Toggle language"
            type="button"
          >
            <GlobeIcon />
            <span>{langLabel}</span>
          </button>

          {isGuest ? (
            <div className="guest-auth-actions">
              <span className="guest-label">{t('roles.guest')}</span>
              <Link to="/login" className="btn btn-primary btn-sm">
                {t('nav.login')}
              </Link>
            </div>
          ) : isAuthenticated ? (
            <div className="avatar-wrapper" ref={dropdownRef}>
              <button
                className="avatar-btn"
                onClick={() => setDropdownOpen(!dropdownOpen)}
                type="button"
              >
                <div className="avatar-circle">
                  {user?.username?.[0]?.toUpperCase() || 'G'}
                </div>
                <div className="avatar-info">
                  <span className="avatar-name">{user?.username || 'Guest'}</span>
                  <span className="avatar-role">{t(`roles.${user?.role || 'guest'}`)}</span>
                </div>
                <span className="avatar-arrow">v</span>
              </button>
              {dropdownOpen && (
                <div className="avatar-dropdown animate-slideDown">
                  {user?.role !== 'guest' && (
                    <Link
                      to={user?.role === 'admin' ? '/admin/profile' : '/profile'}
                      className="dropdown-item"
                      onClick={() => setDropdownOpen(false)}
                    >
                      {t('nav.profile')}
                    </Link>
                  )}
                  <button className="dropdown-item" onClick={handleLogout} type="button">
                    {t('nav.logout')}
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
