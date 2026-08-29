import { useEffect, useState } from 'react'
import { applyTheme, getInitialTheme, type Theme } from '../lib/theme'
import { MoonIcon, SunIcon } from './icons'

/**
 * Dark is the default; the choice persists across reloads (localStorage).
 * The icon shows the theme the button will switch to — sun while dark, moon
 * while light — matching the design reference.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  const targetTheme = theme === 'dark' ? 'light' : 'dark'

  return (
    <button
      type="button"
      aria-label={`Switch to ${targetTheme} theme`}
      title={`Switch to ${targetTheme} theme`}
      onClick={() => setTheme(targetTheme)}
      className="btn btn-secondary btn-icon"
    >
      {theme === 'dark' ? <SunIcon /> : <MoonIcon />}
    </button>
  )
}
