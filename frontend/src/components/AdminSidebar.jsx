import { NavLink } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import './AdminSidebar.css';

const MENU_ITEMS = [
  { key: 'dashboard', path: '/admin', icon: '📊', end: true },
  { key: 'documents', path: '/admin/documents', icon: '📋' },
  { key: 'import', path: '/admin/import', icon: '📥' },
  { key: 'processed', path: '/admin/processed', icon: '🗄️' },
  { key: 'users', path: '/admin/users', icon: '👥' },
  { key: 'profile', path: '/admin/profile', icon: '👤' },
  { key: 'chatbot', path: '/admin/chat', icon: '💬' },
];

export default function AdminSidebar() {
  const { t } = useTranslation();

  return (
    <aside className="admin-sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">⚖️</div>
        <span className="sidebar-title">{t('admin.sidebar.title')}</span>
      </div>

      <nav className="sidebar-nav">
        {MENU_ITEMS.map((item) => (
          <NavLink
            key={item.key}
            to={item.path}
            end={item.end}
            className={({ isActive }) => `sidebar-link ${isActive ? 'active' : ''}`}
          >
            <span className="sidebar-icon">{item.icon}</span>
            <span className="sidebar-label">{t(`admin.sidebar.${item.key}`)}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <span className="sidebar-version">BaoHiem Legal AI · v1.0</span>
      </div>
    </aside>
  );
}
