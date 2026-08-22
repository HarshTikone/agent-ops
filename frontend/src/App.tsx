import { BackendStatus } from './components/BackendStatus'

function App() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-950 px-4 text-neutral-100">
      <h1 className="text-3xl font-semibold">Agent Ops</h1>
      <p className="max-w-md text-center text-neutral-400">
        Multi-agent orchestration copilot — planner + tool-using sub-agents with human-in-the-loop
        approval and full decision tracing.
      </p>
      <BackendStatus />
    </main>
  )
}

export default App
