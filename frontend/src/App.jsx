import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import { ThemeProvider } from './contexts/ThemeContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';

/* Pages */
import LoginPage from './pages/LoginPage';
import HomePage from './pages/HomePage';
import ChatPage from './pages/ChatPage';
import ProfilePage from './pages/ProfilePage';
import DraftDocumentPage from './pages/DraftDocumentPage';
import DraftContractPage from './pages/DraftContractPage';
import ContractReviewPage from './pages/ContractReviewPage';
import RiskAlertsPage from './pages/RiskAlertsPage';

/* Admin */
import AdminLayout from './pages/layouts/AdminLayout';
import DashboardPage from './pages/admin/DashboardPage';
import DocumentsPage from './pages/admin/DocumentsPage';
import ImportDocxPage from './pages/admin/ImportDocxPage';
import UserManagementPage from './pages/admin/UserManagementPage';

function ProtectedRoute({ children, roles, allowGuest = false }) {
  const { user, loading, isAuthenticated, isGuest } = useAuth();

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div className="spinner spinner-lg" />
      </div>
    );
  }

  if (!isAuthenticated && !(allowGuest && isGuest)) {
    return <Navigate to="/login" replace />;
  }

  if (roles && user && !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function AppRoutes() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div className="spinner spinner-lg" />
      </div>
    );
  }

  return (
    <Routes>
      {/* Public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<LoginPage initialMode="register" />} />

      {/* Home - accessible to all, redirects admin */}
      <Route
        path="/"
        element={
          user?.role === 'admin'
            ? <Navigate to="/admin" replace />
            : <ProtectedRoute allowGuest><HomePage /></ProtectedRoute>
        }
      />

      {/* Chat - all roles */}
      <Route path="/chat" element={<ProtectedRoute allowGuest><ChatPage /></ProtectedRoute>} />

      {/* Profile - authenticated non-guest users */}
      <Route path="/profile" element={<ProtectedRoute roles={['free_user', 'business_user']}><ProfilePage /></ProtectedRoute>} />

      {/* Business user features */}
      <Route path="/draft-document" element={<ProtectedRoute roles={['business_user', 'admin']}><DraftDocumentPage /></ProtectedRoute>} />
      <Route path="/draft-contract" element={<ProtectedRoute roles={['business_user', 'admin']}><DraftContractPage /></ProtectedRoute>} />
      <Route path="/contract-review" element={<ProtectedRoute roles={['business_user', 'admin']}><ContractReviewPage /></ProtectedRoute>} />
      <Route path="/risk-alerts" element={<ProtectedRoute roles={['business_user', 'admin']}><RiskAlertsPage /></ProtectedRoute>} />

      {/* Admin */}
      <Route
        path="/admin"
        element={
          <ProtectedRoute roles={['admin']}>
            <AdminLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="documents" element={<Navigate to="/admin/documents/published" replace />} />
        <Route path="documents/published" element={<DocumentsPage mode="published" />} />
        <Route path="documents/review" element={<DocumentsPage mode="review" />} />
        <Route path="import" element={<ImportDocxPage />} />
        <Route path="users" element={<UserManagementPage />} />
        <Route path="profile" element={<ProfilePage embedded />} />
        <Route path="chat" element={<ChatPage />} />
      </Route>

      {/* Fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ThemeProvider>
        <AuthProvider>
          <AppRoutes />
          <Toaster
            position="top-right"
            toastOptions={{
              duration: 3000,
              style: {
                background: 'var(--bg-card)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
                borderRadius: 'var(--radius-md)',
                fontSize: '14px',
              },
            }}
          />
        </AuthProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
