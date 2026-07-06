import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import { useAuth } from '../../contexts/AuthContext';
import Modal from '../../components/Modal';
import toast from 'react-hot-toast';
import './AdminPage.css';

const ROLES = ['admin', 'business_user'];
const EMPTY_FORM = { username: '', password: '', role: 'business_user' };

export default function UserManagementPage() {
  const { t } = useTranslation();
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);

  useEffect(() => { loadUsers(); }, []);

  const filteredUsers = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return users;
    return users.filter((user) => (
      (user.username || '').toLowerCase().includes(query)
      || (user.role || '').toLowerCase().includes(query)
    ));
  }, [users, search]);

  const loadUsers = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await api('/admin/users');
      const data = await res.json();
      setUsers(data.users || []);
    } catch (err) {
      setUsers([]);
      setError(err.message || t('admin.users.load_error'));
    } finally {
      setLoading(false);
    }
  };

  const validateForm = ({ requirePassword }) => {
    if (!form.username.trim()) {
      toast.error(t('admin.users.username_required'));
      return false;
    }
    if (requirePassword && !form.password) {
      toast.error(t('admin.users.password_required'));
      return false;
    }
    if (form.password && form.password.length < 6) {
      toast.error(t('admin.users.password_min'));
      return false;
    }
    return true;
  };

  const handleAdd = async () => {
    if (!validateForm({ requirePassword: true })) return;
    setSubmitting(true);
    try {
      await api('/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: form.username.trim(),
          password: form.password,
          role: form.role,
        }),
      });
      toast.success(t('admin.users.user_added'));
      setShowAdd(false);
      setForm(EMPTY_FORM);
      loadUsers();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = async () => {
    if (!validateForm({ requirePassword: false })) return;
    setSubmitting(true);
    try {
      await api(`/admin/users/${editUser.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: form.role,
          ...(form.password ? { password: form.password } : {}),
        }),
      });
      toast.success(t('admin.users.user_updated'));
      setEditUser(null);
      setForm(EMPTY_FORM);
      loadUsers();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const toggleLock = async (user) => {
    setSubmitting(true);
    try {
      await api(`/admin/users/${user.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !user.is_active }),
      });
      toast.success(t('admin.users.user_updated'));
      loadUsers();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const openAdd = () => {
    setForm(EMPTY_FORM);
    setShowAdd(true);
  };

  const openEdit = (user) => {
    setEditUser(user);
    setForm({ username: user.username, password: '', role: user.role });
  };

  const roleBadge = {
    admin: 'badge-danger',
    business_user: 'badge-gold',
  };

  if (loading) {
    return <div className="flex justify-center" style={{ padding: 80 }}><div className="spinner spinner-lg" /></div>;
  }

  return (
    <div className="admin-page animate-fadeIn">
      <div className="page-header flex justify-between items-center flex-wrap gap-md">
        <div>
          <h1>{t('admin.users.title')}</h1>
          {error && <p className="text-muted text-sm">{error}</p>}
        </div>
        <div className="flex gap-sm flex-wrap">
          <input
            type="text"
            className="search-input"
            placeholder={t('admin.users.search')}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button className="btn btn-primary" onClick={openAdd} disabled={submitting}>
            + {t('admin.users.add_user')}
          </button>
        </div>
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>{t('admin.users.username')}</th>
              <th>{t('admin.users.role')}</th>
              <th>{t('admin.users.created')}</th>
              <th>{t('admin.users.status')}</th>
              <th>{t('admin.users.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {filteredUsers.map((user) => (
              <tr key={user.id}>
                <td>
                  <div className="flex items-center gap-sm">
                    <div className="avatar-circle" style={{ width: 30, height: 30, fontSize: 12 }}>
                      {user.username?.[0]?.toUpperCase()}
                    </div>
                    <span style={{ fontWeight: 600 }}>{user.username}</span>
                  </div>
                </td>
                <td>
                  <span className={`badge ${roleBadge[user.role] || 'badge-info'}`}>
                    {t(`roles.${user.role}`)}
                  </span>
                </td>
                <td>{user.created_at?.split('T')[0] || '-'}</td>
                <td>
                  <span className={`badge ${user.is_active ? 'badge-success' : 'badge-danger'}`}>
                    {user.is_active ? t('admin.users.active') : t('admin.users.locked')}
                  </span>
                </td>
                <td>
                  <div className="flex gap-sm flex-wrap">
                    <button className="btn btn-ghost btn-sm" onClick={() => openEdit(user)} disabled={submitting}>
                      {t('admin.users.edit')}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => toggleLock(user)} disabled={submitting}>
                      {user.is_active ? t('admin.users.lock') : t('admin.users.unlock')}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {filteredUsers.length === 0 && (
              <tr><td colSpan="5" className="text-center text-muted" style={{ padding: 32 }}>{t('admin.users.no_users')}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <Modal isOpen={showAdd} onClose={() => setShowAdd(false)} title={t('admin.users.add_user')} width="420px">
        <UserForm form={form} setForm={setForm} t={t} requireUsername />
        <div className="flex gap-sm" style={{ marginTop: 8 }}>
          <button className="btn btn-primary" onClick={handleAdd} disabled={submitting}>
            {submitting ? <span className="spinner" /> : null}
            {t('admin.users.save')}
          </button>
          <button className="btn btn-secondary" onClick={() => setShowAdd(false)} disabled={submitting}>{t('admin.users.cancel')}</button>
        </div>
      </Modal>

      <Modal isOpen={!!editUser} onClose={() => setEditUser(null)} title={`${t('admin.users.edit')}: ${editUser?.username || ''}`} width="420px">
        <UserForm form={form} setForm={setForm} t={t} editing isSelf={editUser?.id === currentUser?.id} />
        <div className="flex gap-sm" style={{ marginTop: 8 }}>
          <button className="btn btn-primary" onClick={handleEdit} disabled={submitting}>
            {submitting ? <span className="spinner" /> : null}
            {t('admin.users.save')}
          </button>
          <button className="btn btn-secondary" onClick={() => setEditUser(null)} disabled={submitting}>{t('admin.users.cancel')}</button>
        </div>
      </Modal>
    </div>
  );
}

function UserForm({ form, setForm, t, editing = false, isSelf = false }) {
  return (
    <>
      <div className="form-group">
        <label>{t('admin.users.username')}</label>
        <input
          value={form.username}
          disabled={editing}
          onChange={(e) => setForm({ ...form, username: e.target.value })}
          autoComplete="username"
        />
      </div>
      <div className="form-group">
        <label>{editing ? t('admin.users.password_optional') : t('admin.users.password')}</label>
        <input
          type="password"
          value={form.password}
          onChange={(e) => setForm({ ...form, password: e.target.value })}
          placeholder={editing ? t('admin.users.keep_password') : ''}
          autoComplete="new-password"
        />
      </div>
      <div className="form-group">
        <label>{t('admin.users.role')}</label>
        <select
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value })}
          disabled={isSelf}
        >
          {ROLES.map((role) => <option key={role} value={role}>{t(`roles.${role}`)}</option>)}
        </select>
        {isSelf && (
          <span className="text-muted text-sm" style={{ marginTop: 4, display: 'block' }}>
            {t('admin.users.cannot_change_own_role')}
          </span>
        )}
      </div>
    </>
  );
}
