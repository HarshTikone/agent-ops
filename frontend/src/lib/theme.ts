/**
 * Theme state lives on <html data-theme>, which is what the token sheet in
 * index.css switches on. Dark is the product default (design handoff);
 * a stored choice always wins, and index.html applies the same rule inline
 * before first paint so there is no flash of the wrong theme.
 */

export type Theme = 'light' | 'dark'

const THEME_STORAGE_KEY = 'agent-ops.theme'

export function readStoredTheme(): Theme | null {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return stored === 'light' || stored === 'dark' ? stored : null
  } catch {
    // Private-mode/disabled storage: fall back to the default theme.
    return null
  }
}

export function getInitialTheme(): Theme {
  return readStoredTheme() ?? 'dark'
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // Persistence is a convenience, not a requirement — ignore failures.
  }
}
