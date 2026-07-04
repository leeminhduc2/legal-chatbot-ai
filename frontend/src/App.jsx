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
import ProcessedDataPage from './pages/admin/ProcessedDataPage';
import UserManagementPage from './pages/admin/UserManagementPage';

function ProtectedRoute({ children, roles }) {
  const { user, loading, isAuthenticated, isGuest } = useAuth();

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div className="spinner spinner-lg" />
      </div>
    );
  }

  if (!isAuthenticated && !isGuest) {
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

      {/* Home - accessible to all, redirects admin */}
      <Route
        path="/"
        element={
          user?.role === 'admin'
            ? <Navigate to="/admin" replace />
            : <ProtectedRoute><HomePage /></ProtectedRoute>
        }
      />

      {/* Chat - all roles */}
      <Route path="/chat" element={<ProtectedRoute><ChatPage /></ProtectedRoute>} />

      {/* Profile - all logged-in */}
      <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />

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
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="import" element={<ImportDocxPage />} />
        <Route path="processed" element={<ProcessedDataPage />} />
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
