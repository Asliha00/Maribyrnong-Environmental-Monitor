import { Link, NavLink, Outlet, useNavigate } from "react-router";
import { useAuth } from "../hooks/useAuth";
import { roleLabel } from "../lib/roles";
import HealthBadge from "./HealthBadge";

const NAV = [
  { to: "/", label: "Dashboard", permission: "view_data" },
  { to: "/insights", label: "Insights", permission: "view_data" },
  { to: "/quality", label: "Data quality", permission: "view_quality" },
  { to: "/admin", label: "Administration", permission: "manage_users" },
];

/** App frame: header navigation, main content and the privacy footer (SEC-29). */
export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const nav = NAV.filter((item) => user?.permissions.includes(item.permission));

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex min-h-screen flex-col bg-white text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-white focus:p-2 focus:text-slate-900"
      >
        Skip to main content
      </a>
      <header className="border-b border-slate-200 dark:border-slate-800">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-3">
          <Link to="/" className="text-lg font-semibold">
            Maribyrnong Environmental Monitor
          </Link>
          <nav aria-label="Main">
            <ul className="flex gap-1">
              {nav.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      `rounded px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 ${
                        isActive
                          ? "bg-sky-800 text-white"
                          : "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          {user && (
            <div className="flex items-center gap-3 text-sm">
              {/* Role only: no username or email in the header (screenshots, demo video). */}
              <span className="font-medium">
                <span className="sr-only">Signed in as </span>
                {roleLabel(user.role)}
              </span>
              <Link to="/change-password" className="underline">
                Change password
              </Link>
              <button
                type="button"
                onClick={onLogout}
                className="rounded border border-slate-400 px-3 py-1 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:hover:bg-slate-800"
              >
                Log out
              </button>
            </div>
          )}
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 text-sm text-slate-600 dark:border-slate-800 dark:text-slate-400">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <span>Data: Maribyrnong City Council smart sensors</span>
          <span className="flex items-center gap-4">
            <HealthBadge />
            <Link to="/privacy" className="underline">
              Privacy notice
            </Link>
          </span>
        </div>
      </footer>
    </div>
  );
}
