import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../src/App";
import { AuthProvider } from "../src/hooks/useAuth";
import { strengthLabel } from "../src/components/PasswordStrength";

// These tests cover the app shell and authentication; the dashboard itself (map, charts,
// data requests) is tested in dashboard.test.tsx and the Playwright suite.
vi.mock("../src/pages/DashboardPage", () => ({
  default: () => <h1>Dashboard</h1>,
}));

type Reply = { status: number; body: unknown };
type Handler = (init: RequestInit) => Reply;

const USER = {
  user_id: 1,
  username: "demo_analyst",
  email: "demo.analyst@example.org",
  role: "Environmental Analyst",
  permissions: ["export_data", "filter_data", "view_data", "view_quality"],
  must_change_password: false,
  mfa_enabled: false,
  mfa_required: false,
  mfa_verified: false,
};
const err = (status: number, code: string, message: string): Reply => ({
  status,
  body: { error: { code, message } },
});

let routes: Record<string, Handler>;
let calls: { url: string; init: RequestInit }[];

/** A fake backend: "METHOD /api/path" -> reply. Unknown routes answer 404. */
function installFetch() {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ url, init });
      const key = `${init.method ?? "GET"} ${url}`;
      const reply = routes[key]?.(init) ?? err(404, "http_404", "Not found");
      return { ok: reply.status < 400, status: reply.status, json: async () => reply.body };
    }),
  );
}

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  routes = {
    "GET /api/health": () => ({ status: 200, body: { status: "ok", database: "ok" } }),
    "GET /api/me": () => err(401, "not_authenticated", "Please log in to continue."),
    "POST /api/auth/refresh": () => err(401, "not_authenticated", "Please log in to continue."),
  };
  installFetch();
  document.cookie = "mem_csrf=test-csrf-token; path=/";
});
afterEach(() => vi.unstubAllGlobals());

describe("authentication (UC1)", () => {
  it("sends anonymous visitors to the login page", async () => {
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome back" }),
    ).toBeInTheDocument();
  });

  it("shows the server's exact message for bad credentials", async () => {
    routes["POST /api/auth/login"] = () =>
      err(401, "invalid_credentials", "Invalid email or password");
    renderAt("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "x@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("forces a password change on first login", async () => {
    const pending = { ...USER, must_change_password: true };
    routes["POST /api/auth/login"] = () => ({
      status: 200,
      body: { user: pending, next_step: "change_password" },
    });
    renderAt("/login");
    await userEvent.type(await screen.findByLabelText("Email"), "demo.analyst@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "Tram-Lantern-Quartz-58");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      await screen.findByRole("heading", { name: "Change your password" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/must choose a new password/)).toBeInTheDocument();
  });

  it("shows the session-expired message when the session has lapsed", async () => {
    routes["GET /api/me"] = () =>
      err(401, "session_expired", "Your session has expired. Please log in again.");
    routes["POST /api/auth/refresh"] = () =>
      err(401, "session_expired", "Your session has expired. Please log in again.");
    renderAt("/");
    expect(
      await screen.findByText("Your session has expired. Please log in again."),
    ).toBeInTheDocument();
  });

  it("sends administrators without MFA to the MFA page", async () => {
    routes["GET /api/me"] = () => ({
      status: 200,
      body: {
        ...USER,
        role: "System Administrator",
        permissions: [...USER.permissions, "manage_users"],
        mfa_required: true,
      },
    });
    renderAt("/admin");
    expect(
      await screen.findByRole("heading", { name: "Two-factor authentication" }),
    ).toBeInTheDocument();
  });
});

describe("2FA recovery codes (D-037)", () => {
  const ADMIN = {
    ...USER,
    role: "System Administrator",
    permissions: [...USER.permissions, "manage_users"],
    mfa_required: true,
  };
  const CODES = Array.from(
    { length: 10 },
    (_, i) => `ABCD-EFGH-JKMN-PQ${String(i).padStart(2, "0")}`,
  );

  it("shows the codes once after enrolment and continues only after 'I have saved these codes'", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: ADMIN });
    routes["POST /api/auth/mfa/setup"] = () => ({
      status: 200,
      body: {
        otpauth_uri: "otpauth://x",
        qr_svg_data_uri: "data:image/svg+xml;base64,",
        manual_entry_key: "KEY",
      },
    });
    routes["POST /api/auth/mfa/verify"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, mfa_enabled: true, mfa_verified: true },
        next_step: "done",
        recovery_codes: CODES,
      },
    });
    renderAt("/mfa");
    await userEvent.click(await screen.findByRole("button", { name: "Set up authenticator app" }));
    await userEvent.type(await screen.findByLabelText("6-digit code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    const list = await screen.findByRole("list", { name: "Recovery codes" });
    expect(list.querySelectorAll("li")).toHaveLength(10);
    expect(list).toHaveTextContent(CODES[0]);
    const go = screen.getByRole("button", { name: "Continue" });
    expect(go).toBeDisabled();
    await userEvent.click(screen.getByLabelText("I have saved these codes"));
    await userEvent.click(go);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("signs in with a recovery code instead of the authenticator code", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: { ...ADMIN, mfa_enabled: true } });
    routes["POST /api/auth/mfa/recovery"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, mfa_enabled: true, mfa_verified: true },
        next_step: "done",
        recovery_codes_remaining: 8,
      },
    });
    renderAt("/mfa");
    await userEvent.click(
      await screen.findByRole("button", { name: "Use a recovery code instead" }),
    );
    await userEvent.type(screen.getByLabelText("Recovery code"), CODES[0]);
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    const sent = calls.find((c) => c.url === "/api/auth/mfa/recovery")!;
    expect(JSON.parse(sent.init.body as string)).toEqual({ code: CODES[0] });
  });

  it("warns when three or fewer recovery codes are left", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: { ...ADMIN, mfa_enabled: true } });
    routes["POST /api/auth/mfa/recovery"] = () => ({
      status: 200,
      body: {
        user: { ...ADMIN, mfa_enabled: true, mfa_verified: true },
        next_step: "done",
        recovery_codes_remaining: 2,
      },
    });
    renderAt("/mfa");
    await userEvent.click(
      await screen.findByRole("button", { name: "Use a recovery code instead" }),
    );
    await userEvent.type(screen.getByLabelText("Recovery code"), CODES[0]);
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByText(/You have 2 recovery codes left\./)).toBeInTheDocument();
  });

  it("shows the server's message for a wrong or used recovery code", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: { ...ADMIN, mfa_enabled: true } });
    routes["POST /api/auth/mfa/recovery"] = () =>
      err(
        400,
        "invalid_recovery_code",
        "That recovery code is not valid or has already been used.",
      );
    renderAt("/mfa");
    await userEvent.click(
      await screen.findByRole("button", { name: "Use a recovery code instead" }),
    );
    await userEvent.type(screen.getByLabelText("Recovery code"), "WRONG");
    await userEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already been used");
  });
  it("has no Two-factor tab in Administration (UC5 tabs only)", async () => {
    routes["GET /api/me"] = () => ({
      status: 200,
      body: { ...ADMIN, mfa_enabled: true, mfa_verified: true },
    });
    renderAt("/admin/users");
    const tabs = await screen.findByRole("navigation", { name: "Administration sections" });
    expect(tabs).not.toHaveTextContent("Two-factor");
  });

  it("does not show Account security to accounts without 2FA", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: USER });
    renderAt("/change-password");
    await screen.findByRole("heading", { name: "Change your password" });
    expect(screen.queryByRole("heading", { name: "Account security" })).not.toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/mfa/recovery-codes")).toBe(false);
  });

  it("shows Account security on the Change password page: count, warning, new set", async () => {
    routes["GET /api/me"] = () => ({
      status: 200,
      body: { ...ADMIN, mfa_enabled: true, mfa_verified: true },
    });
    routes["GET /api/auth/mfa/recovery-codes"] = () => ({
      status: 200,
      body: { remaining: 2, low: true },
    });
    routes["POST /api/auth/mfa/recovery-codes"] = () => ({
      status: 200,
      body: { recovery_codes: CODES },
    });
    renderAt("/change-password");
    expect(await screen.findByRole("heading", { name: "Account security" })).toBeInTheDocument();
    expect(await screen.findByText(/Generate a new set soon/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Generate new recovery codes" }));
    expect(screen.getByText(/current codes will stop working/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Yes, replace my codes" }));
    const list = await screen.findByRole("list", { name: "Recovery codes" });
    expect(list.querySelectorAll("li")).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Done" })).toBeDisabled();
  });
});

describe("no session at all", () => {
  it("does not try to refresh a session that never existed", async () => {
    document.cookie = "mem_csrf=; path=/; max-age=0"; // never logged in: no CSRF cookie
    renderAt("/");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome back" }),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/auth/refresh")).toBe(false);
  });
});

describe("permissions (SEC-10, UI side)", () => {
  it("tells an Analyst they cannot open the admin page", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: USER });
    renderAt("/admin");
    expect(
      await screen.findByText("You do not have permission to access this page."),
    ).toBeInTheDocument();
  });

  it("hides the Administration link from non-admins", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: USER });
    renderAt("/");
    expect(await screen.findByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Administration" })).not.toBeInTheDocument();
  });
});

describe("browser token handling (SEC-09)", () => {
  it("sends the CSRF header on state-changing requests and never stores tokens", async () => {
    routes["GET /api/me"] = () => ({ status: 200, body: USER });
    routes["POST /api/auth/logout"] = () => ({ status: 200, body: { ok: true } });
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: "Log out" }));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/auth/logout")).toBe(true));
    const logoutCall = calls.find((c) => c.url === "/api/auth/logout")!;
    expect((logoutCall.init.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "test-csrf-token",
    );
    expect(logoutCall.init.credentials).toBe("same-origin");
    // eslint-disable-next-line no-restricted-properties -- asserting nothing was stored (SEC-09)
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    // and the page really returns to the login screen (regression: stale user after logout)
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });

  it("retries once through /auth/refresh when the access token has lapsed", async () => {
    let refreshed = false;
    routes["POST /api/auth/refresh"] = () => {
      refreshed = true;
      return { status: 200, body: { user: USER, next_step: "done" } };
    };
    routes["GET /api/me"] = () =>
      refreshed
        ? { status: 200, body: USER }
        : err(401, "not_authenticated", "Please log in to continue.");
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(refreshed).toBe(true);
  });
});

describe("login page", () => {
  it("shows and hides the password with a labelled eye button", async () => {
    renderAt("/login");
    const password = await screen.findByLabelText("Password");
    expect(password).toHaveAttribute("type", "password");
    await userEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    await userEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
  });

  it("works by keyboard alone", async () => {
    routes["POST /api/auth/login"] = () =>
      err(401, "invalid_credentials", "Invalid email or password");
    renderAt("/login");
    await screen.findByLabelText("Email");
    await userEvent.tab();
    expect(screen.getByLabelText("Email")).toHaveFocus();
    await userEvent.keyboard("x@example.org");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Forgot password?" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByLabelText("Password")).toHaveFocus();
    await userEvent.keyboard("wrong-password");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show password" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "text");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Sign in" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password"); // hidden again
  });

  it("tells users who forgot their password to contact an administrator", async () => {
    renderAt("/login");
    const forgot = await screen.findByRole("button", { name: "Forgot password?" });
    expect(forgot).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(forgot);
    expect(forgot).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getByText("Please contact your administrator to reset your password."),
    ).toBeInTheDocument();
  });

  it("has no role choice and no 'Remember me'; the illustration is decorative", async () => {
    const { container } = renderAt("/login");
    await screen.findByLabelText("Email");
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/remember me/i)).not.toBeInTheDocument();
    const img = container.querySelector("img")!;
    expect(img).toHaveAttribute("alt", "");
    expect(screen.queryByRole("img")).not.toBeInTheDocument(); // hidden from assistive tech
  });
});

describe("header", () => {
  it.each([
    ["Environmental Analyst", "Analyst"],
    ["System Administrator", "Administrator"],
  ])("shows the role label for %s, never the username or email", async (role, label) => {
    routes["GET /api/me"] = () => ({
      status: 200,
      body: { ...USER, role, mfa_verified: true },
    });
    renderAt("/");
    const banner = await screen.findByRole("banner");
    await waitFor(() => expect(banner).toHaveTextContent(`Signed in as ${label}`));
    expect(banner).not.toHaveTextContent(USER.username);
    expect(banner).not.toHaveTextContent(USER.email);
  });
});

describe("app shell", () => {
  it("keeps the privacy notice public", async () => {
    renderAt("/privacy");
    expect(await screen.findByRole("heading", { name: "Privacy notice" })).toBeInTheDocument();
  });

  it("shows the API health from the same-origin /api/health", async () => {
    renderAt("/privacy");
    expect(await screen.findByText("Service online")).toBeInTheDocument();
  });
});

describe("password strength meter", () => {
  it.each([
    ["short", "Too short"],
    ["abcdefghijkl", "Weak"],
    ["Abcdefghijk1", "Fair"],
    ["Tram-Lantern-Quartz-58", "Strong"],
  ])("rates %s as %s", (password, label) => {
    expect(strengthLabel(password)).toBe(label);
  });
});
