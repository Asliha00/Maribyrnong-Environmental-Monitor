import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router";
import { ApiError, login } from "../api/client";
import illustrationDark from "../assets/login-illustration-dark-transparent.webp";
import illustrationLight from "../assets/login-illustration-light.webp";
import { pendingStep, useAuth } from "../hooks/useAuth";

export const EXPIRED_MESSAGE = "Your session has expired. Please log in again.";
export const FORGOT_MESSAGE = "Please contact your administrator to reset your password.";

const STEP_ROUTES = {
  change_password: "/change-password",
  mfa_setup: "/mfa",
  mfa_verify: "/mfa",
} as const;

// Colours are the login tokens in index.css (light and dark), never raw hex here.
const focusRing =
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-login-accent focus-visible:ring-offset-2 focus-visible:ring-offset-login-card";
const field =
  "h-12 w-full rounded-lg border border-login-input-border bg-login-input px-4 text-base text-login-input-text focus:border-login-accent focus:outline-none focus:ring-2 focus:ring-login-accent";

/** UC1 login. All error text comes from the server so it matches the proposal exactly.
 *  No role choice: the role comes from the account. */
export default function LoginPage() {
  const { user, setUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [forgot, setForgot] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={pendingStep(user) ?? "/"} replace />;

  const from = (location.state as { from?: string } | null)?.from ?? "/";

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await login(email.trim(), password);
      setUser(result.user);
      navigate(result.next_step === "done" ? from : STEP_ROUTES[result.next_step], {
        replace: true,
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed. Please try again.");
    } finally {
      setBusy(false);
      setPassword("");
      setShowPassword(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-login-page bg-[radial-gradient(ellipse_at_27%_50%,var(--color-login-glow)_20%,transparent_60%)] px-4 py-8 sm:px-6">
      <div className="grid w-full max-w-[1720px] items-center gap-6 md:grid-cols-[minmax(0,1fr)_minmax(320px,380px)] lg:grid-cols-[58fr_42fr] lg:gap-12">
        {/* Decorative (alt=""), hidden below md. No frame: the page colour is the artwork's
            edge colour, and a soft edge feather hides any remaining edge. The browser loads
            only the image for the active theme (same prefers-color-scheme rule as the site). */}
        <div
          data-illustration
          className="login-art-mask relative hidden w-full justify-self-center overflow-hidden md:block aspect-[957/941] max-w-[min(880px,86vh)] dark:aspect-[854/725] dark:max-w-[min(1040px,99.6vh)]"
        >
          {/* The files are untouched; the browser shows only the artwork area of each, at its
              true shape (no stretching), and the same height in both themes. Dark: a
              transparent-background copy made by scripts/make_login_dark_art.py (D-036). */}
          <picture>
            <source media="(prefers-color-scheme: dark)" srcSet={illustrationDark} />
            <img
              src={illustrationLight}
              alt=""
              className="absolute top-0 left-[-5.12%] h-full w-[174.71%] max-w-none object-fill dark:left-0 dark:w-full"
            />
          </picture>
        </div>
        <section
          aria-labelledby="page-title"
          className="mx-auto w-full max-w-[580px] rounded-[20px] border border-login-card-border bg-login-card p-6 dark:border-transparent shadow-[0_12px_40px_var(--color-login-shadow)] sm:p-10"
        >
          <p className="text-sm font-medium text-login-accent sm:text-base">
            Maribyrnong Environmental Monitor
          </p>
          <h1 id="page-title" className="mt-3 text-3xl font-bold text-login-heading sm:text-[32px]">
            Welcome back
          </h1>
          <p className="mt-2 text-base leading-relaxed text-login-subtitle">
            Sign in with your council account to view air quality and heat data.
          </p>
          {params.get("expired") === "1" && !error && (
            <p
              role="status"
              aria-live="polite"
              className="mt-5 rounded-lg bg-amber-100 p-3 text-sm text-amber-900"
            >
              {EXPIRED_MESSAGE}
            </p>
          )}
          {error && (
            <p
              role="alert"
              aria-live="assertive"
              className="mt-5 rounded-lg bg-red-100 p-3 text-sm text-red-900"
            >
              {error}
            </p>
          )}
          <form onSubmit={onSubmit} className="mt-7 space-y-5" noValidate>
            <div>
              <label htmlFor="email" className="block text-base font-semibold text-login-label">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={`mt-2 ${field}`}
              />
            </div>
            <div>
              <div className="flex items-baseline justify-between gap-2">
                <label
                  htmlFor="password"
                  className="block text-base font-semibold text-login-label"
                >
                  Password
                </label>
                <button
                  type="button"
                  aria-expanded={forgot}
                  aria-controls="forgot-help"
                  onClick={() => setForgot((f) => !f)}
                  className={`rounded text-sm text-login-accent underline underline-offset-2 transition-colors hover:text-login-accent-hover motion-reduce:transition-none sm:text-base ${focusRing}`}
                >
                  Forgot password?
                </button>
              </div>
              <div className="relative mt-2">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className={`${field} pr-12`}
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  aria-controls="password"
                  onClick={() => setShowPassword((s) => !s)}
                  className={`absolute inset-y-0 right-0 flex w-12 items-center justify-center rounded-r-lg text-login-subtitle transition-colors hover:text-login-heading motion-reduce:transition-none ${focusRing}`}
                >
                  <EyeIcon crossed={showPassword} />
                </button>
              </div>
              <div id="forgot-help" aria-live="polite">
                {forgot && (
                  <p className="mt-3 rounded-lg border border-login-card-border bg-login-page p-3 text-sm text-login-heading">
                    {FORGOT_MESSAGE}
                  </p>
                )}
              </div>
            </div>
            <button
              type="submit"
              disabled={busy || !email || !password}
              className={`h-14 w-full rounded-lg bg-login-accent px-4 text-lg font-semibold text-login-on-accent transition-colors hover:bg-login-accent-hover disabled:cursor-not-allowed disabled:opacity-85 disabled:hover:bg-login-accent motion-reduce:transition-none ${focusRing}`}
            >
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}

function EyeIcon({ crossed }: { crossed: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
      {crossed && <path d="M3 3l18 18" />}
    </svg>
  );
}
