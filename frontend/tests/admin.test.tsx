import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../src/api/client";

const api = vi.hoisted(() => ({
  listAdminSensors: vi.fn(),
  registerSensor: vi.fn(),
  updateSensor: vi.fn(),
  decommissionSensor: vi.fn(),
  issueDeviceKey: vi.fn(),
  listUsers: vi.fn(),
  createUser: vi.fn(),
  updateUser: vi.fn(),
  resetPassword: vi.fn(),
  resetMfa: vi.fn(),
  listThresholds: vi.fn(),
  updateThreshold: vi.fn(),
}));
vi.mock("../src/api/admin", async (original) => ({
  ...(await original<typeof import("../src/api/admin")>()),
  ...api,
}));
vi.mock("../src/hooks/useAuth", () => ({
  useAuth: () => ({ user: { user_id: 1, username: "me", permissions: ["manage_users"] } }),
}));

const { default: AdminSensors, coordinatesValid } =
  await import("../src/components/admin/AdminSensors");
const { default: AdminUsers } = await import("../src/components/admin/AdminUsers");
const { default: AdminThresholds } = await import("../src/components/admin/AdminThresholds");
const { fileProblem, uploadPathname, MAX_UPLOAD_BYTES } =
  await import("../src/components/admin/AdminUpload");

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const SENSOR = {
  sensor_id: 1,
  sensor_code: "MCC-01",
  sensor_name: "MCC Air Quality Unit 1",
  device_family: "mcc_aq",
  hardware_id: null,
  latitude: -37.801,
  longitude: 144.889,
  location_verified: false,
  land_use: "Transport corridor",
  installation_date: null,
  status: "Active",
  notes: null,
  has_device_key: false,
  first_reading_utc: null,
  last_reading_utc: null,
};

beforeEach(() => {
  Object.values(api).forEach((f) => f.mockReset());
  api.listAdminSensors.mockResolvedValue({ sensors: [SENSOR] });
});

describe("pure helpers", () => {
  it("accepts only coordinates inside Maribyrnong", () => {
    expect(coordinatesValid("-37.80", "144.89")).toBe(true);
    expect(coordinatesValid("-37.70", "144.89")).toBe(false);
    expect(coordinatesValid("37.80", "144.89")).toBe(false);
    expect(coordinatesValid("", "144.89")).toBe(false);
    expect(coordinatesValid("abc", "144.89")).toBe(false);
  });

  it("builds the only upload pathname the token route accepts", () => {
    const p = uploadPathname("../../Council Export (Jan).CSV", new Uint8Array(16).fill(171));
    expect(p).toBe(`uploads/Council-Export-Jan-${"ab".repeat(16)}.csv`);
    // same rule as upload/src/policy.ts UPLOAD_PATHNAME
    expect(p).toMatch(/^uploads\/[A-Za-z0-9][A-Za-z0-9._-]{0,100}-[0-9a-f]{32}\.csv$/);
    expect(uploadPathname("...")).toMatch(/^uploads\/upload-[0-9a-f]{32}\.csv$/);
  });

  it("checks the file before uploading", () => {
    const csv = (name: string, size: number) =>
      Object.defineProperty(new File(["x"], name), "size", { value: size });
    expect(fileProblem(null)).toMatch(/Choose a CSV/);
    expect(fileProblem(csv("data.xlsx", 10))).toMatch(/Choose a CSV file/);
    expect(fileProblem(csv("data.csv", 0))).toMatch(/empty/);
    expect(fileProblem(csv("data.csv", MAX_UPLOAD_BYTES + 1))).toMatch(/50 MB/);
    expect(fileProblem(csv("data.CSV", 1024))).toBeNull();
  });
});

describe("sensor management", () => {
  it("shows the UC5 coordinate message and red fields without calling the server", async () => {
    wrap(<AdminSensors />);
    await userEvent.click(await screen.findByRole("button", { name: "Register a sensor" }));
    const form = screen.getByRole("form", { name: "Register a sensor" });
    await userEvent.type(within(form).getByLabelText("Sensor code"), "new-01");
    await userEvent.type(within(form).getByLabelText("Name"), "Yarraville Gardens");
    await userEvent.type(within(form).getByLabelText(/Latitude/), "-38.5");
    await userEvent.type(within(form).getByLabelText(/Longitude/), "144.88");
    await userEvent.click(within(form).getByRole("button", { name: "Register sensor" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Please enter valid GPS coordinates within the municipality boundary.",
    );
    expect(within(form).getByLabelText(/Latitude/)).toHaveAttribute("aria-invalid", "true");
    expect(api.registerSensor).not.toHaveBeenCalled();
  });

  it("registers, says so, and shows the device key once", async () => {
    api.registerSensor.mockResolvedValue({
      message: "Sensor registered successfully",
      sensor: { ...SENSOR, sensor_id: 2, sensor_code: "NEW-01" },
      device_key: "one-time-device-key",
    });
    wrap(<AdminSensors />);
    await userEvent.click(await screen.findByRole("button", { name: "Register a sensor" }));
    const form = screen.getByRole("form", { name: "Register a sensor" });
    await userEvent.type(within(form).getByLabelText("Sensor code"), "new-01");
    await userEvent.type(within(form).getByLabelText("Name"), "Yarraville Gardens");
    await userEvent.type(within(form).getByLabelText(/Latitude/), "-37.815");
    await userEvent.type(within(form).getByLabelText(/Longitude/), "144.885");
    await userEvent.click(within(form).getByRole("button", { name: "Register sensor" }));
    expect(await screen.findByText("Sensor registered successfully")).toBeInTheDocument();
    expect(api.registerSensor).toHaveBeenCalledWith(
      expect.objectContaining({ sensor_code: "NEW-01", latitude: -37.815, longitude: 144.885 }),
    );
    const secret = screen.getByRole("region", { name: "Device key for NEW-01" });
    expect(secret).toHaveTextContent("one-time-device-key");
    await userEvent.click(within(secret).getByRole("button", { name: "I have saved it" }));
    expect(screen.queryByText("one-time-device-key")).not.toBeInTheDocument();
  });

  it("shows the duplicate-name message from the server", async () => {
    api.registerSensor.mockRejectedValue(
      new ApiError(
        409,
        "duplicate_sensor_name",
        "A sensor with this name already exists. Please use a unique name.",
      ),
    );
    wrap(<AdminSensors />);
    await userEvent.click(await screen.findByRole("button", { name: "Register a sensor" }));
    const form = screen.getByRole("form", { name: "Register a sensor" });
    await userEvent.type(within(form).getByLabelText("Sensor code"), "X-1");
    await userEvent.type(within(form).getByLabelText("Name"), "MCC Air Quality Unit 1");
    await userEvent.type(within(form).getByLabelText(/Latitude/), "-37.8");
    await userEvent.type(within(form).getByLabelText(/Longitude/), "144.88");
    await userEvent.click(within(form).getByRole("button", { name: "Register sensor" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A sensor with this name already exists. Please use a unique name.",
    );
    expect(within(form).getByLabelText("Name")).toHaveAttribute("aria-invalid", "true");
  });

  it("asks before decommissioning", async () => {
    api.decommissionSensor.mockResolvedValue({
      message: "Sensor decommissioned. Its data and history are kept.",
      sensor: { ...SENSOR, status: "Inactive" },
    });
    wrap(<AdminSensors />);
    await userEvent.click(await screen.findByRole("button", { name: "Decommission MCC-01" }));
    const dialog = screen.getByRole("alertdialog", { name: "Decommission MCC-01?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Decommission" }));
    expect(api.decommissionSensor).toHaveBeenCalledWith(1);
    expect(await screen.findByText(/Its data and history are kept/)).toBeInTheDocument();
  });
});

describe("user management", () => {
  const user = (id: number, name: string, extra = {}) => ({
    user_id: id,
    username: name,
    email: `${name}@example.org`,
    role_id: 2,
    role_name: "Environmental Analyst",
    is_active: true,
    must_change_password: false,
    mfa_enabled: false,
    locked: false,
    last_login_at: null,
    created_at: null,
    ...extra,
  });

  it("offers no access changes on your own account", async () => {
    api.listUsers.mockResolvedValue({
      users: [user(1, "me", { role_id: 3, role_name: "System Administrator" }), user(2, "pat")],
    });
    wrap(<AdminUsers />);
    expect(await screen.findByText("(you)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Deactivate me/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deactivate pat" })).toBeInTheDocument();
  });

  it("offers only the Analyst and Administrator roles (D-035)", async () => {
    api.listUsers.mockResolvedValue({
      users: [user(2, "pat"), user(4, "old", { role_id: 1, role_name: "General User" })],
    });
    wrap(<AdminUsers />);
    await userEvent.click(await screen.findByRole("button", { name: "Create a user" }));
    const create = within(screen.getByRole("form", { name: "Create a user" }));
    const options = (select: HTMLElement) =>
      within(select)
        .getAllByRole("option")
        .filter((o) => !(o as HTMLOptionElement).disabled)
        .map((o) => o.textContent);
    const roles = ["Environmental Analyst", "System Administrator"];
    expect(options(create.getByRole("combobox", { name: "Role" }))).toEqual(roles);
    expect(options(screen.getByRole("combobox", { name: "Role for pat" }))).toEqual(roles);
    // an old General User record shows its role, but it cannot be chosen again
    const old = screen.getByRole("combobox", { name: "Role for old" });
    expect(old).toHaveDisplayValue("General User (retired)");
    expect(options(old)).toEqual(roles);
    expect(screen.queryByRole("button", { name: "Apply role for old" })).not.toBeInTheDocument();
  });

  it("resets a password after confirmation and shows the temporary password once", async () => {
    api.listUsers.mockResolvedValue({ users: [user(2, "pat")] });
    api.resetPassword.mockResolvedValue({
      message: "Password reset.",
      user: user(2, "pat", { must_change_password: true }),
      temporary_password: "shown-once",
    });
    wrap(<AdminUsers />);
    await userEvent.click(await screen.findByRole("button", { name: "Reset password for pat" }));
    await userEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Reset password" }),
    );
    expect(api.resetPassword).toHaveBeenCalledWith(2);
    expect(
      await screen.findByRole("region", { name: "Temporary password for pat" }),
    ).toHaveTextContent("shown-once");
  });
});

describe("threshold management", () => {
  it("requires a reason and shows the change log", async () => {
    const t = {
      threshold_id: 1,
      variable: "pm25",
      variable_label: "PM2.5",
      unit: "µg/m³",
      statistic: "daily mean",
      period: "day",
      operator: ">",
      value: 25,
      label: "PM2.5 24-hour standard",
      source: "NEPM",
      updated_at: null,
      exceedance_days: 2,
    };
    api.listThresholds.mockResolvedValue({ thresholds: [t], history: [] });
    api.updateThreshold.mockResolvedValue({
      message: "Threshold updated. Exceedances recalculated: 5 days now exceed it (was 2).",
      thresholds: [{ ...t, value: 20, exceedance_days: 5 }],
      history: [
        {
          history_id: 1,
          threshold_id: 1,
          old_value: 25,
          new_value: 20,
          reason: "Trial of a stricter level.",
          changed_at: "2026-10-29T05:00:00Z",
          changed_by: "me",
        },
      ],
    });
    wrap(<AdminThresholds />);
    expect(await screen.findByText("No threshold has been changed yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Change PM2.5 24-hour standard" }));
    const form = screen.getByRole("form", { name: "Change PM2.5 24-hour standard" });
    expect(within(form).getByLabelText(/Reason/)).toBeRequired();
    await userEvent.clear(within(form).getByLabelText(/New value/));
    await userEvent.type(within(form).getByLabelText(/New value/), "20");
    await userEvent.type(within(form).getByLabelText(/Reason/), "Trial of a stricter level.");
    await userEvent.click(within(form).getByRole("button", { name: "Save and recalculate" }));
    await waitFor(() =>
      expect(api.updateThreshold).toHaveBeenCalledWith(1, 20, "Trial of a stricter level."),
    );
    expect(await screen.findByText(/5 days now exceed it/)).toBeInTheDocument();
    expect(screen.getByText("25 → 20")).toBeInTheDocument();
  });
});
