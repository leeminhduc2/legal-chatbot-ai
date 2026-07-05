import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useAuth } from '../contexts/AuthContext';
import toast from 'react-hot-toast';
import logo from '../assets/logo.png';
import './LoginPage.css';

export default function LoginPage({ initialMode = 'login' }) {
  const { t } = useTranslation();
  const { login, register, loginAsGuest } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState(initialMode);
  const [form, setForm] = useState({ username: '', password: '', confirmPassword: '' });
  const [busy, setBusy] = useState(false);
  const isRegister = mode === 'register';

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.username || !form.password) return;
    if (isRegister && form.password !== form.confirmPassword) {
      toast.error(t('login.password_mismatch'));
      return;
    }

    setBusy(true);
    try {
      const user = isRegister
        ? await register(form.username, form.password)
        : await login(form.username, form.password);
      toast.success(isRegister ? t('login.register_success') : t('login.success'));
      navigate(user.role === 'admin' ? '/admin' : isRegister ? '/chat' : '/');
    } catch (err) {
      toast.error(err.message || (isRegister ? t('login.register_error') : t('login.error')));
    } finally {
      setBusy(false);
    }
  };

  const handleGuest = () => {
    loginAsGuest();
    navigate('/');
  };

  const toggleMode = () => {
    setMode(isRegister ? 'login' : 'register');
    setForm({ username: '', password: '', confirmPassword: '' });
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
          <img className="login-logo-image" src={logo} alt={t('app.name')} />
        </div>

        <h1 className="login-title">
          {t(isRegister ? 'login.register_title' : 'login.title')}
        </h1>
        <p className="login-subtitle">
          {t(isRegister ? 'login.register_subtitle' : 'login.subtitle')}
        </p>

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
            autoComplete={isRegister ? 'new-password' : 'current-password'}
          />
        </div>

        {isRegister && (
          <div className="form-group">
            <label htmlFor="login-confirm-password">{t('login.confirm_password')}</label>
            <input
              id="login-confirm-password"
              type="password"
              value={form.confirmPassword}
              onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
              autoComplete="new-password"
            />
          </div>
        )}

        <button type="submit" className="btn btn-primary btn-lg w-full" disabled={busy}>
          {busy ? <span className="spinner" /> : null}
          {t(isRegister ? 'login.register_submit' : 'login.submit')} -&gt;
        </button>

        <p className="login-hint">{t('login.hint')}</p>

        <button type="button" className="login-switch" onClick={toggleMode}>
          {t(isRegister ? 'login.switch_to_login' : 'login.switch_to_register')}
        </button>

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
