const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

/**
 * Centralized API client that auto-injects Bearer token.
 */
export async function apiClient(path, options = {}, token = '') {
  const headers = { ...(options.headers || {}) };

  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let errorMessage = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      errorMessage = body?.error?.message || body?.error?.code || errorMessage;
    } catch {
      /* Keep HTTP fallback */
    }
    throw new Error(errorMessage);
  }

  return response;
}

/**
 * Helper: make API call using token from localStorage.
 */
export function api(path, options = {}) {
  const token = localStorage.getItem('token') || '';
  return apiClient(path, options, token);
}

export { API_BASE };
