import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import toast from 'react-hot-toast';
import './LoginPage.css';

export default function LoginPage() {
  const { t } = useTranslation();
  const { login, loginAsGuest } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: '', password: '' });
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.username || !form.password) return;
    setBusy(true);
    try {
      const user = await login(form.username, form.password);
      toast.success(t('login.success'));
      if (user.role === 'admin') {
        navigate('/admin');
      } else {
        navigate('/');
      }
    } catch (err) {
      toast.error(err.message || t('login.error'));
    } finally {
      setBusy(false);
    }
  };

  const handleGuest = () => {
    loginAsGuest();
    navigate('/');
  };

  return (
    <div className="login-page">
      <div className="login-bg-effects">
        <div className="login-bg-orb orb-1" />
        <div className="login-bg-orb orb-2" />
        <div className="login-bg-orb orb-3" />
      </div>

      <form className="login-card card-glass animate-slideUp" onSubmit={handleSubmit}>
        <div className="login-logo">
          <div className="login-logo-icon">⚖️</div>
        </div>

        <h1 className="login-title">{t('login.title')}</h1>
        <p className="login-subtitle">{t('login.subtitle')}</p>

        <div className="form-group">
          <label htmlFor="login-username">{t('login.username')}</label>
          <input
            id="login-username"
            type="text"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            autoComplete="username"
            autoFocus
          />
        </div>

        <div className="form-group">
          <label htmlFor="login-password">{t('login.password')}</label>
          <input
            id="login-password"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            autoComplete="current-password"
          />
        </div>

        <button type="submit" className="btn btn-primary btn-lg w-full" disabled={busy}>
          {busy ? <span className="spinner" /> : null}
          {t('login.submit')} →
        </button>

        <p className="login-hint">{t('login.hint')}</p>

        <div className="login-divider">
          <span>{t('login.or')}</span>
        </div>

        <button
          type="button"
          className="btn btn-secondary btn-lg w-full"
          onClick={handleGuest}
        >
          {t('login.guest')}
        </button>
      </form>
    </div>
  );
}
