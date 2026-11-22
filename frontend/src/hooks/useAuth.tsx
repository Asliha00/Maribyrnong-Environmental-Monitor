import { createContext, useContext, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, getMe, logout as apiLogout, type User } from "../api/client";

type AuthState = {
  user: User | null;
  loading: boolean;
  /** "session_expired" when a previously valid session lapsed (UC1 message) */
  reason: string | null;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

/** Holds the signed-in user, read from GET /api/me (the cookies are invisible to JS). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery<User | null, ApiError>({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await getMe();
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          if (error.code === "session_expired") throw error;
          return null;
        }
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });

  const setUser = (user: User | null) => queryClient.setQueryData(["me"], user);
  const logout = async () => {
    try {
      await apiLogout();
    } finally {
      // Not queryClient.clear(): that would detach this provider from the "me" query,
      // leaving the old user on screen after logout (caught by e2e/security.spec.ts).
      setUser(null);
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    }
  };

  const expired = me.error?.code === "session_expired";
  const value: AuthState = {
    user: me.data ?? null,
    loading: me.isPending,
    reason: expired ? "session_expired" : null,
    setUser,
    logout,
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** Where a user must go next, mirroring the backend's next_step rules. */
export function pendingStep(user: User): "/change-password" | "/mfa" | null {
  if (user.must_change_password) return "/change-password";
  if (user.mfa_required && !user.mfa_verified) return "/mfa";
  return null;
}
