import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  /** Changing this value resets the boundary — e.g. the route path, so
   * navigating away from a crashed page recovers automatically. */
  resetKey?: string;
}

interface State {
  error: Error | null;
}

/** Contains a render crash to this subtree instead of white-screening the whole
 * app. A page whose data shape drifted from what it expects shows a readable
 * error here (with a reload) while the nav rail stays usable. */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidUpdate(prev: Props): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null }); // navigated away — recover
    }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('page render error:', error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-lg p-8 text-center">
          <h2 className="text-lg font-semibold">This page hit an error</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            Something went wrong rendering this section. Other pages still work.
          </p>
          <pre className="mt-4 overflow-x-auto rounded bg-muted p-3 text-left text-xs text-destructive">
            {this.state.error.message}
          </pre>
          <button
            type="button"
            className="mt-4 rounded-md border px-4 py-2 text-sm hover:bg-accent"
            onClick={() => {
              window.location.reload();
            }}
          >
            Reload
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
