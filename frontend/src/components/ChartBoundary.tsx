import { Component, type ReactNode } from "react";

/**
 * Catches render errors from a chart subtree and shows the message inline,
 * instead of letting one broken chart blank the whole page. Also useful for
 * surfacing the real error during debugging.
 */
export class ChartBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(err: unknown) {
    return { error: err instanceof Error ? err.message : String(err) };
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: 12,
            fontSize: 12,
            color: "var(--bad)",
            fontFamily: "var(--mono)",
            whiteSpace: "pre-wrap",
          }}
        >
          Chart error: {this.state.error}
        </div>
      );
    }
    return this.props.children;
  }
}
