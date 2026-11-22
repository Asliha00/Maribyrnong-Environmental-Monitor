import { ApiError } from "../api/client";

/** Loading and error states. Error text is the server's (or the client's UC2 timeout /
 * network message), shown verbatim so it matches the proposal's use cases. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 p-4 text-sm text-slate-600 dark:text-slate-300"
    >
      <span
        aria-hidden="true"
        className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-sky-700"
      />
      {label}
    </p>
  );
}

export function ErrorMessage({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? error.message
      : "Something went wrong. Please try again or contact your administrator.";
  const isNoData = error instanceof ApiError && error.code === "no_data";
  const canRetry =
    error instanceof ApiError && ["timeout", "network", "rate_limited"].includes(error.code);
  return (
    <div
      role={isNoData ? "status" : "alert"}
      className={`flex flex-wrap items-center gap-3 rounded p-3 text-sm ${
        isNoData
          ? "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-100"
          : "bg-red-100 text-red-900"
      }`}
    >
      <span>{message}</span>
      {canRetry && onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded border border-current px-2 py-0.5 font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600"
        >
          Try again
        </button>
      )}
    </div>
  );
}
