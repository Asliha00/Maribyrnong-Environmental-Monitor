import { Outlet, Route, Routes } from "react-router";
import Layout from "./components/Layout";
import { RequireAuth, RequirePermission } from "./components/Guards";
import AdminPage from "./pages/AdminPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import DashboardPage from "./pages/DashboardPage";
import InsightsPage from "./pages/InsightsPage";
import LoginPage from "./pages/LoginPage";
import MfaPage from "./pages/MfaPage";
import PlaceholderPage from "./pages/PlaceholderPage";
import PrivacyPage from "./pages/PrivacyPage";
import QualityPage from "./pages/QualityPage";
import SensorHistoryPage from "./pages/SensorHistoryPage";

function Protected() {
  return (
    <RequireAuth>
      <Outlet />
    </RequireAuth>
  );
}

/** Route table. Placeholders are replaced phase by phase. */
export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Layout />}>
        <Route path="privacy" element={<PrivacyPage />} />
        <Route element={<Protected />}>
          <Route index element={<DashboardPage />} />
          <Route path="sensors/:sensorId" element={<SensorHistoryPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route
            path="admin/*"
            element={
              <RequirePermission permission="manage_users">
                <AdminPage />
              </RequirePermission>
            }
          />
          <Route
            path="quality"
            element={
              <RequirePermission permission="view_quality">
                <QualityPage />
              </RequirePermission>
            }
          />
          <Route path="change-password" element={<ChangePasswordPage />} />
          <Route path="mfa" element={<MfaPage />} />
          <Route
            path="*"
            element={
              <PlaceholderPage
                title="Page not found"
                note="The page you are looking for does not exist."
              />
            }
          />
        </Route>
      </Route>
    </Routes>
  );
}
