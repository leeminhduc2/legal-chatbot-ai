import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { API_BASE, apiClient } from '../services/api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('token') || '');
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const clearAuth = useCallback(() => {
    localStorage.removeItem('token');
    setToken('');
    setUser(null);
  }, []);

  /* Validate token on mount */
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }

    apiClient('/auth/me', {}, token)
      .then((res) => res.json())
      .then((data) => {
        if (data.user) {
          setUser(data.user);
        } else {
          clearAuth();
        }
      })
      .catch(() => {
        clearAuth();
      })
      .finally(() => {
        setLoading(false);
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const authenticate = async (path, username, password) => {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data?.error?.message || 'Login failed');
    }
    localStorage.setItem('token', data.access_token);
    setToken(data.access_token);
    setUser(data.user);
    return data.user;
  };

  const login = async (username, password) => {
    return authenticate('/auth/login', username, password);
  };

  const logout = async () => {
    try {
      await apiClient('/auth/logout', { method: 'POST' }, token);
    } catch {
      /* Ignore logout errors */
    }
    clearAuth();
  };

  const loginAsGuest = () => {
    setUser({ id: 'guest', username: 'Guest', role: 'guest', is_active: true });
    setLoading(false);
  };

  const isAuthenticated = !!token && !!user;
  const isGuest = user?.role === 'guest' && !token;
  const isAdmin = user?.role === 'admin';
  const isBusinessUser = user?.role === 'business_user';

  return (
    <AuthContext.Provider
      value={{
        token,
        user,
        loading,
        login,
        logout,
        loginAsGuest,
        isAuthenticated,
        isGuest,
        isAdmin,
        isBusinessUser,
        clearAuth,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
