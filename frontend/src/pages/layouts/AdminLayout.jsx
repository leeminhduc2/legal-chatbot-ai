import { Outlet } from 'react-router-dom';
import Header from '../../components/Header';
import AdminSidebar from '../../components/AdminSidebar';
import './AdminLayout.css';

export default function AdminLayout() {
  return (
    <div className="admin-layout">
      <AdminSidebar />
      <div className="admin-main">
        <Header />
        <div className="admin-content">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
