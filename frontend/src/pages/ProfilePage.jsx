import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../services/api';
import toast from 'react-hot-toast';
import Header from '../components/Header';
import './ProfilePage.css';

export default function ProfilePage({ embedded }) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [form, setForm] = useState({ current: '', newPass: '', confirm: '' });
  const [busy, setBusy] = useState(false);

  const handlePasswordChange = async (e) => {
    e.preventDefault();
    if (form.newPass.length < 6) {
      toast.error(t('profile.password_min'));
      return;
    }
    if (form.newPass !== form.confirm) {
      toast.error(t('profile.password_mismatch'));
      return;
    }
    setBusy(true);
    try {
      await api('/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          current_password: form.current,
          new_password: form.newPass,
        }),
      });
      toast.success(t('profile.password_updated'));
      setForm({ current: '', newPass: '', confirm: '' });
    } catch (err) {
      toast.error(err.message || t('profile.password_error'));
    } finally {
      setBusy(false);
    }
  };

  const roleColor = {
    admin: 'badge-danger',
    business_user: 'badge-gold',
    guest: 'badge-info',
  };

  const content = (
    <div className="profile-container animate-slideUp">
      <div className="page-header">
        <h1>{t('profile.title')}</h1>
      </div>

      <div className="profile-grid">
        {/* Info Card */}
        <div className="card profile-info-card">
          <div className="profile-avatar-large">
            {user?.username?.[0]?.toUpperCase() || 'U'}
          </div>
          <h2 className="profile-username">{user?.username || '-'}</h2>
          <span className={`badge ${roleColor[user?.role] || 'badge-info'}`}>
            {t(`roles.${user?.role || 'guest'}`)}
          </span>
          <div className="profile-meta">
            <div className="meta-row">
              <span className="meta-label">{t('profile.created')}</span>
              <span className="meta-value">{user?.created_at?.split('T')[0] || '-'}</span>
            </div>
            <div className="meta-row">
              <span className="meta-label">{t('profile.status')}</span>
              <span className={`badge ${user?.is_active !== false ? 'badge-success' : 'badge-danger'}`}>
                {user?.is_active !== false ? t('profile.active') : t('profile.locked')}
              </span>
            </div>
          </div>
        </div>

        {/* Password Card */}
        <div className="card profile-password-card">
          <h3>{t('profile.change_password')}</h3>
          <form onSubmit={handlePasswordChange} className="password-form">
            <div className="form-group">
              <label htmlFor="current-password">{t('profile.current_password')}</label>
              <input
                id="current-password"
                type="password"
                value={form.current}
                onChange={(e) => setForm({ ...form, current: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label htmlFor="new-password">{t('profile.new_password')}</label>
              <input
                id="new-password"
                type="password"
                value={form.newPass}
                onChange={(e) => setForm({ ...form, newPass: e.target.value })}
              />
            </div>
            <div className="form-group">
              <label htmlFor="confirm-password">{t('profile.confirm_password')}</label>
              <input
                id="confirm-password"
                type="password"
                value={form.confirm}
                onChange={(e) => setForm({ ...form, confirm: e.target.value })}
              />
            </div>
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? <span className="spinner" /> : null}
              {t('profile.update')}
            </button>
          </form>
        </div>
      </div>
    </div>
  );

  if (embedded) return content;

  return (
    <div className="home-layout">
      <Header />
      <main style={{ padding: '24px' }}>{content}</main>
    </div>
  );
}
