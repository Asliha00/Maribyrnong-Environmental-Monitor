import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { ApiError, changePassword } from "../api/client";
import AccountRecoveryCodes from "../components/AccountRecoveryCodes";
import PasswordStrength, { MIN_LENGTH } from "../components/PasswordStrength";
import { pendingStep, useAuth } from "../hooks/useAuth";

const inputClass =
  "mt-1 w-full rounded border border-slate-400 bg-white px-3 py-2 text-slate-900 dark:bg-slate-800 dark:text-slate-100";

/** UC1 forced first-login change, also usable voluntarily (SEC-05). Accounts with 2FA also
 * manage their recovery codes here, under "Account security" (D-037). */
export default function ChangePasswordPage() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const mismatch = confirm.length > 0 && next !== confirm;
  const ready = current && next.length >= MIN_LENGTH && next === confirm;

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setError(null);
    setBusy(true);
    try {
      const result = await changePassword(current, next);
      setUser(result.user);
      navigate(pendingStep(result.user) ?? "/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Your password could not be changed. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  const showSecurity = user?.mfa_enabled && user.mfa_verified && !user.must_change_password;

  return (
    <>
      <section aria-labelledby="page-title" className="max-w-md">
        <h1 id="page-title" className="text-2xl font-semibold">
          Change your password
        </h1>
        {user?.must_change_password && (
          <p className="mt-2 text-slate-700 dark:text-slate-300">
            You must choose a new password before using the dashboard.
          </p>
        )}
        <p className="mt-2 text-sm text-slate-600 dark:text-slate-400">
          Use at least {MIN_LENGTH} characters. Avoid common passwords and your name or email
          address. A short phrase of unrelated words works well.
        </p>
        {error && (
          <p role="alert" className="mt-4 rounded bg-red-100 p-3 text-sm text-red-900">
            {error}
          </p>
        )}
        <form onSubmit={onSubmit} className="mt-4 space-y-4" noValidate>
          <div>
            <label htmlFor="current" className="block text-sm font-medium">
              Current password
            </label>
            <input
              id="current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              className={inputClass}
            />
          </div>
          <div>
            <label htmlFor="new" className="block text-sm font-medium">
              New password
            </label>
            <input
              id="new"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              className={inputClass}
              aria-describedby="strength"
            />
            <div id="strength">
              <PasswordStrength password={next} />
            </div>
          </div>
          <div>
            <label htmlFor="confirm" className="block text-sm font-medium">
              Confirm new password
            </label>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className={inputClass}
              aria-invalid={mismatch}
            />
            {mismatch && (
              <p className="mt-1 text-sm text-red-800 dark:text-red-300">
                The passwords do not match.
              </p>
            )}
          </div>
          <button
            type="submit"
            disabled={busy || !ready}
            className="rounded bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Change password"}
          </button>
        </form>
      </section>
      {showSecurity && <AccountRecoveryCodes />}
    </>
  );
}
