import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api } from '../../services/api';
import Modal from '../../components/Modal';
import toast from 'react-hot-toast';
import './AdminPage.css';

const ROLES = ['admin', 'business_user', 'guest'];

export default function UserManagementPage() {
  const { t } = useTranslation();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [form, setForm] = useState({ username: '', password: '', role: 'business_user' });

  useEffect(() => { loadUsers(); }, []);

  const loadUsers = async () => {
    setLoading(true);
    try {
      const res = await api('/admin/users');
      const data = await res.json();
      setUsers(data.users || []);
    } catch {
      /* No endpoint yet - show empty */
      setUsers([]);
    } finally {
      setLoading(false);
    }
  };

  const handleAdd = async () => {
    if (!form.username || !form.password) return;
    try {
      await api('/admin/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      toast.success(t('admin.users.user_added'));
      setShowAdd(false);
      setForm({ username: '', password: '', role: 'business_user' });
      loadUsers();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleEdit = async () => {
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
      loadUsers();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const toggleLock = async (user) => {
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
    }
  };

  const openEdit = (user) => {
    setEditUser(user);
    setForm({ username: user.username, password: '', role: user.role });
  };

  const roleBadge = {
    admin: 'badge-danger',
    business_user: 'badge-gold',
    guest: 'badge-info',
  };

  if (loading) {
    return <div className="flex justify-center" style={{ padding: 80 }}><div className="spinner spinner-lg" /></div>;
  }

  return (
    <div className="admin-page animate-fadeIn">
      <div className="page-header flex justify-between items-center flex-wrap gap-md">
        <h1>{t('admin.users.title')}</h1>
        <button className="btn btn-primary" onClick={() => { setShowAdd(true); setForm({ username: '', password: '', role: 'business_user' }); }}>
          + {t('admin.users.add_user')}
        </button>
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
            {users.map((user) => (
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
                    <button className="btn btn-ghost btn-sm" onClick={() => openEdit(user)}>
                      ✏️ {t('admin.users.edit')}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => toggleLock(user)}>
                      🔒 {user.is_active ? t('admin.users.lock') : t('admin.users.unlock')}
                    </button>
                  </div>
                </td>
              </tr>
            ))}
            {users.length === 0 && (
              <tr><td colSpan="5" className="text-center text-muted" style={{ padding: 32 }}>{t('admin.users.no_users')}</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Add User Modal */}
      <Modal isOpen={showAdd} onClose={() => setShowAdd(false)} title={t('admin.users.add_user')} width="420px">
        <div className="form-group">
          <label>{t('admin.users.username')}</label>
          <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </div>
        <div className="form-group">
          <label>{t('admin.users.password')}</label>
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        <div className="form-group">
          <label>{t('admin.users.role')}</label>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
          </select>
        </div>
        <div className="flex gap-sm" style={{ marginTop: 8 }}>
          <button className="btn btn-primary" onClick={handleAdd}>{t('admin.users.save')}</button>
          <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>{t('admin.users.cancel')}</button>
        </div>
      </Modal>

      {/* Edit User Modal */}
      <Modal isOpen={!!editUser} onClose={() => setEditUser(null)} title={`${t('admin.users.edit')}: ${editUser?.username || ''}`} width="420px">
        <div className="form-group">
          <label>{t('admin.users.username')}</label>
          <input value={form.username} disabled />
        </div>
        <div className="form-group">
          <label>{t('admin.users.password')} (optional)</label>
          <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Leave blank to keep" />
        </div>
        <div className="form-group">
          <label>{t('admin.users.role')}</label>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {ROLES.map((r) => <option key={r} value={r}>{t(`roles.${r}`)}</option>)}
          </select>
        </div>
        <div className="flex gap-sm" style={{ marginTop: 8 }}>
          <button className="btn btn-primary" onClick={handleEdit}>{t('admin.users.save')}</button>
          <button className="btn btn-secondary" onClick={() => setEditUser(null)}>{t('admin.users.cancel')}</button>
        </div>
      </Modal>
    </div>
  );
}
