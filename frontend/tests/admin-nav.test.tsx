import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it, vi } from "vitest";

// The sections themselves are tested in admin.test.tsx; here only navigation matters.
vi.mock("../src/components/admin/AdminSensors", () => ({
  default: () => <h2>Sensors section</h2>,
}));
vi.mock("../src/components/admin/AdminUsers", () => ({ default: () => <h2>Users section</h2> }));
vi.mock("../src/components/admin/AdminThresholds", () => ({
  default: () => <h2>Thresholds section</h2>,
}));
vi.mock("../src/components/admin/AdminUpload", () => ({ default: () => <h2>Upload section</h2> }));

const { default: AdminPage } = await import("../src/pages/AdminPage");

function Where() {
  return <output aria-label="path">{useLocation().pathname}</output>;
}

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="admin/*" element={<AdminPage />} />
      </Routes>
      <Where />
    </MemoryRouter>,
  );
}

const TABS = [
  ["Sensors", "/admin/sensors"],
  ["Users", "/admin/users"],
  ["Thresholds", "/admin/thresholds"],
  ["Upload data", "/admin/upload"],
] as const;

describe("administration tabs", () => {
  // Regression: relative links inside the admin/* splat route resolved against the current URL
  // (/admin/sensors -> /admin/sensors/upload) and the fallback redirect looped forever.
  it.each(TABS)("from every tab, %s goes to %s", async (label, path) => {
    for (const [, start] of TABS) {
      renderAt(start);
      await userEvent.click(screen.getByRole("link", { name: label }));
      expect(screen.getByLabelText("path")).toHaveTextContent(path);
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
      document.body.innerHTML = "";
    }
  });

  it("sends /admin and unknown admin paths to Sensors, once", () => {
    for (const start of ["/admin", "/admin/nonsense", "/admin/sensors/upload"]) {
      renderAt(start);
      expect(screen.getByLabelText("path")).toHaveTextContent(/^\/admin\/sensors$/);
      expect(screen.getByRole("heading", { name: "Sensors section" })).toBeInTheDocument();
      document.body.innerHTML = "";
    }
  });
});
