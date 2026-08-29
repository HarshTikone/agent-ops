import { BrowserRouter, Route, Routes, useParams } from 'react-router-dom'
import { BackendStatus } from './components/BackendStatus'
import { AppErrorBoundary } from './components/AppErrorBoundary'
import { OperatorKeyControl } from './components/OperatorKeyControl'
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
    <main className="mx-auto max-w-2xl px-4 py-12">
      <h1 className="text-xl font-semibold text-neutral-100">Page not found</h1>
      <p className="mt-2 text-sm text-neutral-400">The requested Agent Ops page does not exist.</p>
      <a href="/" className="mt-4 inline-block text-sm text-blue-400 hover:text-blue-300">
        Return to all sessions
      </a>
    </main>
  )
}

function App() {
  return (
    <BrowserRouter>
      <div id="app-shell" className="min-h-screen bg-neutral-950 text-neutral-100">
        <header className="border-b border-neutral-800 px-4 py-3">
          <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-3">
            <h1 className="text-lg font-semibold">Agent Ops</h1>
            <div className="flex flex-wrap items-center justify-end gap-3">
              <OperatorKeyControl />
              <BackendStatus />
            </div>
          </div>
        </header>
        <AppErrorBoundary>
          <Routes>
            <Route path="/" element={<SessionListPage />} />
            <Route path="/sessions/:sessionId" element={<SessionPageRoute />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AppErrorBoundary>
      </div>
    </BrowserRouter>
  )
}

export default App
