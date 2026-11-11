import { Component, type ReactNode } from "react";

/** Keeps one broken page from blanking the whole app. Resets when its `key` changes (the Shell keys
 *  it by route), so navigating away and back gives the page a fresh start. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) { return { error }; }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="panel error">
        <strong>Something went wrong on this page.</strong>
        <div className="muted">{this.state.error.message}</div>
        <button className="btn" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
