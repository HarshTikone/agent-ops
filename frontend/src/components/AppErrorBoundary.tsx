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
        <main
          className="mx-auto max-w-[1120px] px-[var(--space-6)] py-[var(--space-8)]"
          role="alert"
        >
          <h1 className="text-[var(--color-danger)]">Something went wrong</h1>
          <p className="text-muted mt-[var(--space-2)] text-sm">
            The interface could not continue safely. Reload to restore the latest persisted state.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="btn btn-primary mt-[var(--space-4)]"
          >
            Reload application
          </button>
        </main>
      )
    }
    return this.props.children
  }
}
