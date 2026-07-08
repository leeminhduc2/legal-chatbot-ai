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
    let errorCode = '';
    let errorDetails = null;
    try {
      const body = await response.json();
      errorCode = body?.error?.code || '';
      errorDetails = body?.error?.details || null;
      errorMessage = body?.error?.message || errorCode || errorMessage;
    } catch {
      /* Keep HTTP fallback */
    }
    const error = new Error(errorMessage);
    error.status = response.status;
    error.code = errorCode;
    error.details = errorDetails;
    throw error;
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
