import { createContext, useContext, useEffect, useState, useCallback } from 'react';

const ThemeContext = createContext(null);

const THEME_KEY = 'theme';

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => {
    return localStorage.getItem(THEME_KEY) || 'dark';
  });

  const getEffectiveTheme = useCallback((themeValue) => {
    if (themeValue === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    return themeValue;
  }, []);

  const applyTheme = useCallback((themeValue) => {
    const effective = getEffectiveTheme(themeValue);
    document.documentElement.setAttribute('data-theme', effective);
  }, [getEffectiveTheme]);

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem(THEME_KEY, theme);
  }, [theme, applyTheme]);

  useEffect(() => {
    if (theme !== 'system') return;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = () => applyTheme('system');
    mediaQuery.addEventListener('change', handler);
    return () => mediaQuery.removeEventListener('change', handler);
  }, [theme, applyTheme]);

  const cycleTheme = () => {
    setThemeState((prev) => {
      const order = ['light', 'dark', 'system'];
      const idx = order.indexOf(prev);
      return order[(idx + 1) % order.length];
    });
  };

  return (
    <ThemeContext.Provider value={{ theme, setTheme: setThemeState, cycleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider');
  return ctx;
}
