import { BrowserRouter, Route, Routes, useParams } from 'react-router-dom'
import { BackendStatus } from './components/BackendStatus'
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

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-neutral-950 text-neutral-100">
        <header className="border-b border-neutral-800 px-4 py-3">
          <div className="mx-auto flex w-full max-w-2xl items-center justify-between">
            <h1 className="text-lg font-semibold">Agent Ops</h1>
            <BackendStatus />
          </div>
        </header>
        <Routes>
          <Route path="/" element={<SessionListPage />} />
          <Route path="/sessions/:sessionId" element={<SessionPageRoute />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

export default App
