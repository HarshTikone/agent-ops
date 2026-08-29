import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  failed: boolean
}

export class AppErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Agent Ops UI crashed', error, info.componentStack)
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="mx-auto max-w-2xl px-4 py-12" role="alert">
          <h1 className="text-xl font-semibold text-red-300">Something went wrong</h1>
          <p className="mt-2 text-sm text-neutral-400">
            The interface could not continue safely. Reload to restore the latest persisted state.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-4 rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-600"
          >
            Reload application
          </button>
        </main>
      )
    }
    return this.props.children
  }
}
