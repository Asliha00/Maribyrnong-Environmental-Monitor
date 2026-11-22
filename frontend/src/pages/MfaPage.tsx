import { useState, type FormEvent } from "react";
import { Navigate } from "react-router";
import {
  ApiError,
  signInWithRecoveryCode,
  startMfaSetup,
  verifyMfa,
  type MfaSetup,
} from "../api/client";
import RecoveryCodes from "../components/RecoveryCodes";
import { useAuth } from "../hooks/useAuth";

const BUTTON =
  "rounded bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 disabled:opacity-50";
const LINK =
  "text-sm font-medium text-sky-800 underline hover:text-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:text-sky-300";

export const lowCodesMessage = (n: number) =>
  n === 0
    ? "That was your last recovery code. Generate a new set from Change password → Account security."
    : `You have ${n} recovery code${n === 1 ? "" : "s"} left. Generate a new set from Change password → Account security.`;

/** SEC-07: administrators enrol an authenticator app, then enter a code on every login.
 * A single-use recovery code can replace the authenticator code (D-037). */
export default function MfaPage() {
  const { user, setUser } = useAuth();
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [code, setCode] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [newCodes, setNewCodes] = useState<string[] | null>(null);
  const [lowWarning, setLowWarning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const enrolling = !user?.mfa_enabled && !newCodes;
  // Leave only once the verified user has reached the auth state: navigating straight after
  // setUser() let the route guard see the old, unverified user and send us back here.
  const [leaving, setLeaving] = useState(false);
  const finish = () => setLeaving(true);

  async function begin() {
    setError(null);
    setBusy(true);
    try {
      setSetup(await startMfaSetup());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start set-up. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (recovering) {
        const result = await signInWithRecoveryCode(code);
        setUser(result.user);
        if (result.recovery_codes_remaining <= 3) {
          setLowWarning(lowCodesMessage(result.recovery_codes_remaining));
          return;
        }
        finish();
        return;
      }
      const result = await verifyMfa(code);
      if (result.recovery_codes?.length) {
        setNewCodes(result.recovery_codes); // show once, before leaving this page
        setUser(result.user);
        return;
      }
      setUser(result.user);
      finish();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That code could not be checked. Please try again.",
      );
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setRecovering(!recovering);
    setCode("");
    setError(null);
  }

  if (leaving && user?.mfa_verified) return <Navigate to="/" replace />;

  if (newCodes) {
    return (
      <section aria-labelledby="page-title" className="max-w-md">
        <h1 id="page-title" className="text-2xl font-semibold">
          Two-factor authentication is on
        </h1>
        <p className="mt-2 text-slate-700 dark:text-slate-300">
          If you lose your phone, sign in with one of these codes instead of the 6-digit code.
        </p>
        <RecoveryCodes codes={newCodes} onDone={finish} />
      </section>
    );
  }

  if (lowWarning) {
    return (
      <section aria-labelledby="page-title" className="max-w-md">
        <h1 id="page-title" className="text-2xl font-semibold">
          Signed in with a recovery code
        </h1>
        <p role="status" className="mt-4 rounded bg-amber-100 p-3 text-sm text-amber-950">
          {lowWarning}
        </p>
        <button type="button" onClick={finish} className={`mt-4 ${BUTTON}`}>
          Continue
        </button>
      </section>
    );
  }

  return (
    <section aria-labelledby="page-title" className="max-w-md">
      <h1 id="page-title" className="text-2xl font-semibold">
        Two-factor authentication
      </h1>
      <p className="mt-2 text-slate-700 dark:text-slate-300">
        {enrolling
          ? "Administrators must protect their account with an authenticator app (for example Microsoft Authenticator or Google Authenticator)."
          : recovering
            ? "Enter one of your recovery codes. Each code works once."
            : "Enter the 6-digit code from your authenticator app."}
      </p>
      {error && (
        <p role="alert" className="mt-4 rounded bg-red-100 p-3 text-sm text-red-900">
          {error}
        </p>
      )}

      {enrolling && !setup && (
        <button type="button" onClick={begin} disabled={busy} className={`mt-4 ${BUTTON}`}>
          Set up authenticator app
        </button>
      )}

      {enrolling && setup && (
        <div className="mt-4 space-y-3">
          <p>1. Scan this code with your authenticator app:</p>
          <img
            src={setup.qr_svg_data_uri}
            alt="QR code to add this account to an authenticator app"
            className="h-48 w-48 rounded bg-white p-2"
          />
          <p className="text-sm">
            Can&apos;t scan it? Enter this key manually:{" "}
            <code className="break-all rounded bg-slate-100 px-1 dark:bg-slate-800">
              {setup.manual_entry_key}
            </code>
          </p>
          <p>2. Enter the 6-digit code it shows:</p>
        </div>
      )}

      {(!enrolling || setup) && (
        <form onSubmit={onSubmit} className="mt-4 flex items-end gap-3" noValidate>
          {recovering ? (
            <div>
              <label htmlFor="code" className="block text-sm font-medium">
                Recovery code
              </label>
              <input
                id="code"
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                maxLength={32}
                placeholder="XXXX-XXXX-XXXX-XXXX"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                className="mt-1 w-64 rounded border border-slate-400 bg-white px-3 py-2 font-mono text-slate-900 uppercase dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
          ) : (
            <div>
              <label htmlFor="code" className="block text-sm font-medium">
                6-digit code
              </label>
              <input
                id="code"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="\d{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                className="mt-1 w-32 rounded border border-slate-400 bg-white px-3 py-2 text-lg tracking-widest text-slate-900 dark:bg-slate-800 dark:text-slate-100"
              />
            </div>
          )}
          <button
            type="submit"
            disabled={busy || (recovering ? code.trim().length === 0 : code.length !== 6)}
            className={BUTTON}
          >
            Verify
          </button>
        </form>
      )}

      {!enrolling && (
        <button type="button" onClick={switchMode} className={`mt-4 ${LINK}`}>
          {recovering ? "Use your authenticator app instead" : "Use a recovery code instead"}
        </button>
      )}
    </section>
  );
}
