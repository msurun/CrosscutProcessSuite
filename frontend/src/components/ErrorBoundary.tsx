// Render-time error boundary: keeps one broken screen from blanking the whole app.
// A class component is required because only classes receive componentDidCatch /
// getDerivedStateFromError. The fallback speaks through the injected translator, so this
// file stays free of user-facing strings.
import React from "react";
import type { Translate } from "../findings";

/** Props for {@link ErrorBoundary}. */
export interface ErrorBoundaryProps {
  /** Translator used for the fallback copy. */
  t: Translate;
  /** The subtree whose render errors are caught. */
  children: React.ReactNode;
  /**
   * Identity of the current screen. When it changes after an error, the boundary
   * clears itself so navigating elsewhere recovers without a full reload.
   */
  resetKey?: string;
}

/** Internal state: the caught error, or `null` while children render fine. */
interface ErrorBoundaryState {
  error: Error | null;
}

/**
 * Catches render errors thrown by `children` and shows a translated alert with a
 * reload button instead of crashing the tree.
 *
 * Errors from event handlers, async code and timers are NOT caught; they must be
 * handled where they occur.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  /**
   * React lifecycle: turns a thrown error into state during the render phase.
   * Must be static and pure; it runs before the fallback is rendered.
   */
  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  /**
   * React lifecycle: side-effect hook fired after an error was caught.
   * Logs the full error so the stack trace is not lost in the fallback UI.
   */
  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    console.error("ErrorBoundary caught a render error", error, info.componentStack);
  }

  /**
   * React lifecycle: called after every update. If the screen changed (resetKey
   * differs) while we were showing a fallback, drop the error so the new screen renders.
   */
  componentDidUpdate(previousProps: ErrorBoundaryProps): void {
    const screenChanged = previousProps.resetKey !== this.props.resetKey;
    if (screenChanged && this.state.error !== null) {
      this.clearError();
    }
  }

  /** Drops the caught error so `children` are rendered again on the next render. */
  private clearError = (): void => {
    this.setState({ error: null });
  };

  /** Renders the fallback alert, or the children when no error was caught. */
  render(): React.ReactNode {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }
    return this.renderFallback(error);
  }

  /** Builds the alert shown instead of the broken subtree. */
  private renderFallback(error: Error): React.ReactNode {
    const { t } = this.props;
    return (
      <div role="alert" className="error-boundary">
        <h2>{t("error.boundary")}</h2>
        <p>{t("error.boundaryDetail", { reason: error.message })}</p>
        <button type="button" className="filter-chip" onClick={this.clearError}>
          {t("error.reload")}
        </button>
      </div>
    );
  }
}
