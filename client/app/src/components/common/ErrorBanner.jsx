import { useEffect, useState } from "react";
import { AlertTriangle, X, RefreshCw } from "lucide-react";
import {
  subscribeTransientError,
  isNetworkError,
  isServerError,
} from "../../api.js";

// Auto-dismiss after this long. Long enough for the user to notice +
// click "Retry", short enough that a stale banner doesn't linger.
const AUTO_DISMISS_MS = 8000;

/**
 * Floating banner at the top of the screen for transient errors —
 * 5xx responses and network failures classified by ``api.js``. Shown
 * for the most recent error; bursts collapse to one. Auto-dismisses
 * after a few seconds, but the user can also dismiss manually or hit
 * "Retry" which simply reloads the page.
 *
 * We don't try to retry the failed call automatically — most call
 * sites already have their own retry surface (the user sends the
 * message again, opens the project again, etc.) and a "phantom retry"
 * here would be wrong for non-idempotent endpoints. The banner is
 * informational + a manual reload escape hatch.
 */
export default function ErrorBanner() {
  const [error, setError] = useState(null);

  useEffect(() => {
    return subscribeTransientError((err) => {
      setError(err);
    });
  }, []);

  useEffect(() => {
    if (!error) return;
    const t = setTimeout(() => setError(null), AUTO_DISMISS_MS);
    return () => clearTimeout(t);
  }, [error]);

  if (!error) return null;

  const isNet = isNetworkError(error);
  const isSrv = isServerError(error);
  const title = isNet
    ? "You appear to be offline"
    : isSrv
    ? "The server had a hiccup"
    : "Something went wrong";
  const detail = isNet
    ? "We couldn't reach the server. Check your connection and try again."
    : error.message || "Please try again in a moment.";

  return (
    <div className="fixed top-3 left-1/2 -translate-x-1/2 z-[100] w-[min(560px,calc(100vw-1.5rem))]">
      <div
        role="alert"
        className="flex items-start gap-3 p-3 pr-2 rounded-lg bg-white border border-red-200 shadow-lg"
      >
        <div className="shrink-0 w-8 h-8 rounded-full bg-red-50 flex items-center justify-center">
          <AlertTriangle size={16} className="text-red-600" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-semibold text-gray-900">{title}</div>
          <div className="text-[12px] text-gray-600 mt-0.5">{detail}</div>
        </div>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-red-600 text-white text-xs font-medium hover:bg-red-700 transition-colors"
          title="Reload the page"
        >
          <RefreshCw size={12} />
          Retry
        </button>
        <button
          type="button"
          onClick={() => setError(null)}
          className="shrink-0 w-7 h-7 rounded-md flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
          aria-label="Dismiss"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  );
}
