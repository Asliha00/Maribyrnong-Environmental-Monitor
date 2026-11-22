import { NavLink, Navigate, Route, Routes } from "react-router";
import AdminSensors from "../components/admin/AdminSensors";
import AdminThresholds from "../components/admin/AdminThresholds";
import AdminUpload from "../components/admin/AdminUpload";
import AdminUsers from "../components/admin/AdminUsers";

// Absolute paths: inside the "admin/*" splat route, React Router 7 resolves a RELATIVE link
// against the current URL, so "upload" from /admin/sensors became /admin/sensors/upload and
// the fallback redirect then looped (/admin/sensors/upload/sensors/sensors/...).
const TABS = [
  { to: "/admin/sensors", label: "Sensors" },
  { to: "/admin/users", label: "Users" },
  { to: "/admin/thresholds", label: "Thresholds" },
  { to: "/admin/upload", label: "Upload data" },
];

/** UC5 administration (System Administrators after MFA; the server enforces it per route). */
export default function AdminPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Administration</h1>
      <nav aria-label="Administration sections">
        <ul className="flex flex-wrap gap-1 border-b border-slate-300 dark:border-slate-700">
          {TABS.map((t) => (
            <li key={t.to}>
              <NavLink
                to={t.to}
                className={({ isActive }) =>
                  `-mb-px block border-b-2 px-3 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 ${
                    isActive
                      ? "border-sky-700 text-sky-800 dark:text-sky-300"
                      : "border-transparent text-slate-700 hover:border-slate-400 dark:text-slate-300"
                  }`
                }
              >
                {t.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <Routes>
        <Route index element={<Navigate to="/admin/sensors" replace />} />
        <Route path="sensors" element={<AdminSensors />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="thresholds" element={<AdminThresholds />} />
        <Route path="upload" element={<AdminUpload />} />
        <Route path="*" element={<Navigate to="/admin/sensors" replace />} />
      </Routes>
    </div>
  );
}
