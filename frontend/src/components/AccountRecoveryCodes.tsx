import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, getRecoveryStatus, regenerateRecoveryCodes } from "../api/client";
import RecoveryCodes from "./RecoveryCodes";

/** "Account security" on the Change password page: your own 2FA recovery codes (D-037),
 * how many are left, and a new set on request. A new set cancels every unused code, so the
 * old ones stop working at once. Shown only to accounts whose session passed 2FA. */
export default function AccountRecoveryCodes() {
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: ["recovery-status"], queryFn: getRecoveryStatus });
  const [confirming, setConfirming] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function generate() {
    setError(null);
    setBusy(true);
    try {
      setCodes((await regenerateRecoveryCodes()).recovery_codes);
      setConfirming(false);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not create new codes. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  function done() {
    setCodes(null);
    void queryClient.invalidateQueries({ queryKey: ["recovery-status"] });
  }

  return (
    <section
      aria-labelledby="recovery-heading"
      className="mt-10 max-w-md space-y-3 border-t border-slate-300 pt-6 dark:border-slate-700"
    >
      <h2 id="recovery-heading" className="text-xl font-semibold">
        Account security
      </h2>
      <h3 className="font-medium">Two-factor recovery codes</h3>
      <p className="text-sm text-slate-700 dark:text-slate-300">
        Recovery codes let you sign in without your authenticator app. Each code works once, after
        your password.
      </p>
      {error && (
        <p role="alert" className="rounded bg-red-100 p-3 text-sm text-red-900">
          {error}
        </p>
      )}

      {codes ? (
        <RecoveryCodes codes={codes} onDone={done} doneLabel="Done" />
      ) : (
        <>
          {status.isPending && <p>Loading…</p>}
          {status.isError && (
            <p role="alert" className="rounded bg-red-100 p-3 text-sm text-red-900">
              Could not load your recovery codes.
            </p>
          )}
          {status.data && (
            <p className={status.data.low ? "rounded bg-amber-100 p-3 text-sm text-amber-950" : ""}>
              You have <strong>{status.data.remaining}</strong> unused recovery code
              {status.data.remaining === 1 ? "" : "s"}.
              {status.data.low && " Generate a new set soon."}
            </p>
          )}
          {!confirming ? (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="rounded bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600"
            >
              Generate new recovery codes
            </button>
          ) : (
            <div className="space-y-2 rounded border border-amber-400 p-3">
              <p className="text-sm">
                Your current codes will stop working, including any you have given to someone.
                Continue?
              </p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={generate}
                  disabled={busy}
                  className="rounded bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 disabled:opacity-50"
                >
                  Yes, replace my codes
                </button>
                <button
                  type="button"
                  onClick={() => setConfirming(false)}
                  className="rounded border border-slate-400 px-4 py-2 font-medium hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:hover:bg-slate-800"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
