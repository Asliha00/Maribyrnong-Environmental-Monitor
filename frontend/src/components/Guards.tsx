import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { pendingStep, useAuth } from "../hooks/useAuth";

export const FORBIDDEN_MESSAGE = "You do not have permission to access this page.";

function Loading() {
  return (
    <p role="status" className="p-6 text-slate-600 dark:text-slate-400">
      Loading…
    </p>
  );
}

/** Signed-in users only; also enforces the forced password change and admin MFA. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading, reason } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (!user) {
    const query = reason === "session_expired" ? "?expired=1" : "";
    return <Navigate to={`/login${query}`} replace state={{ from: location.pathname }} />;
  }
  const step = pendingStep(user);
  if (step && location.pathname !== step) return <Navigate to={step} replace />;
  return <>{children}</>;
}

/** UI half of SEC-10: the backend enforces the same rule with HTTP 403. */
export function RequirePermission({
  permission,
  children,
}: {
  permission: string;
  children: ReactNode;
}) {
  const { user } = useAuth();
  if (!user?.permissions.includes(permission)) {
    return (
      <section aria-labelledby="forbidden-title" className="max-w-prose">
        <h1 id="forbidden-title" className="text-2xl font-semibold">
          Access denied
        </h1>
        <p className="mt-2">{FORBIDDEN_MESSAGE}</p>
      </section>
    );
  }
  return <>{children}</>;
}
