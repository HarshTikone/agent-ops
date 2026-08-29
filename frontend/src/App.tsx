import { BrowserRouter, Link, Route, Routes, useParams } from 'react-router-dom'
import { BackendStatus } from './components/BackendStatus'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { BrandMark } from './components/icons'
import { OperatorKeyControl } from './components/OperatorKeyControl'
import { ThemeToggle } from './components/ThemeToggle'
import { SessionListPage } from './pages/SessionListPage'
import { SessionPage } from './pages/SessionPage'

// Keyed by sessionId so navigating from one session straight to another
// (e.g. via the "All sessions" link and a new session, without a full page
// reload) fully remounts SessionPage rather than reusing the instance —
// its own internal state (load/submitting/actionError) resets cleanly
// instead of briefly showing the previous session's data. See the comment
// in SessionPage.tsx's effect for why this replaces a manual state reset.
function SessionPageRoute() {
  const { sessionId } = useParams<{ sessionId: string }>()
  return <SessionPage key={sessionId} />
}

function NotFoundPage() {
  return (
    <main className="mx-auto max-w-[1120px] px-[var(--space-6)] py-[var(--space-8)]">
      <h1>Page not found</h1>
      <p className="text-muted mt-[var(--space-2)] text-sm">
        The requested Agent Ops page does not exist.
      </p>
      <Link to="/" className="btn btn-secondary mt-[var(--space-4)]">
        Return to all sessions
      </Link>
    </main>
  )
}

function App() {
  return (
    <BrowserRouter>
      <AppErrorBoundary>
        <div
          id="app-shell"
          className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)] transition-colors"
        >
          <header className="border-b border-[var(--color-divider)] px-[var(--space-6)] py-[var(--space-3)]">
            <div className="mx-auto flex w-full max-w-[1120px] flex-wrap items-center justify-between gap-[var(--space-4)]">
              <Link
                to="/"
                aria-label="Agent Ops home"
                className="brand-link flex items-center gap-[9px] text-[15px] tracking-[0.08em] uppercase"
              >
                <BrandMark className="flex-none text-[var(--color-accent)]" />
                Agent Ops
              </Link>
              <div className="flex flex-wrap items-center justify-end gap-[var(--space-4)]">
                <OperatorKeyControl />
                <BackendStatus />
                <ThemeToggle />
              </div>
            </div>
          </header>
          <Routes>
            <Route path="/" element={<SessionListPage />} />
            <Route path="/sessions/:sessionId" element={<SessionPageRoute />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </div>
      </AppErrorBoundary>
    </BrowserRouter>
  )
}

export default App
