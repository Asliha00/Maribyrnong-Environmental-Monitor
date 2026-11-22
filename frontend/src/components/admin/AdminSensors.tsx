import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "../../api/client";
import {
  BOUNDS,
  COORDINATE_MESSAGE,
  decommissionSensor,
  DEVICE_FAMILIES,
  issueDeviceKey,
  listAdminSensors,
  registerSensor,
  updateSensor,
  type AdminSensor,
} from "../../api/admin";
import { ErrorMessage, Loading } from "../StatusMessage";
import ConfirmDialog from "./ConfirmDialog";
import OneTimeSecret from "./OneTimeSecret";

const LAND_USES = ["Residential", "Industrial", "Parkland", "Transport corridor", "Commercial"];
const input =
  "mt-1 w-full rounded border px-2 py-1.5 text-sm dark:bg-slate-900 aria-[invalid=true]:border-red-700 aria-[invalid=true]:ring-1 aria-[invalid=true]:ring-red-700 border-slate-400";

type Form = {
  sensor_code: string;
  sensor_name: string;
  device_family: string;
  land_use: string;
  latitude: string;
  longitude: string;
  installation_date: string;
  notes: string;
  location_verified: boolean;
  sensitive_receptor: boolean;
};
const EMPTY: Form = {
  sensor_code: "",
  sensor_name: "",
  device_family: "mcc_aq",
  land_use: "Residential",
  latitude: "",
  longitude: "",
  installation_date: "",
  notes: "",
  location_verified: false,
  sensitive_receptor: false,
};

/** Decimal degrees inside the municipality (the server checks the same box). */
export function coordinatesValid(lat: string, lon: string): boolean {
  const la = Number(lat);
  const lo = Number(lon);
  return (
    lat.trim() !== "" &&
    lon.trim() !== "" &&
    Number.isFinite(la) &&
    Number.isFinite(lo) &&
    la >= BOUNDS.lat[0] &&
    la <= BOUNDS.lat[1] &&
    lo >= BOUNDS.lon[0] &&
    lo <= BOUNDS.lon[1]
  );
}

function toForm(s: AdminSensor): Form {
  return {
    sensor_code: s.sensor_code,
    sensor_name: s.sensor_name,
    device_family: s.device_family,
    land_use: s.land_use,
    latitude: s.latitude?.toString() ?? "",
    longitude: s.longitude?.toString() ?? "",
    installation_date: s.installation_date ?? "",
    notes: s.notes ?? "",
    location_verified: s.location_verified,
    sensitive_receptor: s.sensitive_receptor,
  };
}

function SensorForm({
  initial,
  editing,
  busy,
  serverError,
  onSubmit,
  onCancel,
}: {
  initial: Form;
  editing: boolean;
  busy: boolean;
  serverError: ApiError | null;
  onSubmit: (f: Form) => void;
  onCancel: () => void;
}) {
  const [f, setF] = useState(initial);
  const [checked, setChecked] = useState(false);
  const set = (k: keyof Form) => (e: { target: { value: string } }) =>
    setF({ ...f, [k]: e.target.value });
  const badCoords =
    (checked && !coordinatesValid(f.latitude, f.longitude)) ||
    serverError?.code === "invalid_coordinates";
  const badName = serverError?.code === "duplicate_sensor_name";
  const badCode = serverError?.code === "duplicate_sensor_code";
  const message = badCoords ? COORDINATE_MESSAGE : serverError?.message;

  return (
    <form
      noValidate
      aria-label={editing ? `Edit ${initial.sensor_code}` : "Register a sensor"}
      className="grid gap-3 rounded border border-slate-300 p-4 sm:grid-cols-2 dark:border-slate-700"
      onSubmit={(e) => {
        e.preventDefault();
        setChecked(true);
        if (coordinatesValid(f.latitude, f.longitude)) onSubmit(f);
      }}
    >
      <h3 className="text-lg font-semibold sm:col-span-2">
        {editing ? `Edit ${initial.sensor_code}` : "Register a sensor"}
      </h3>
      {!editing && (
        <label className="text-sm">
          Sensor code
          <input
            className={input}
            required
            value={f.sensor_code}
            onChange={(e) => setF({ ...f, sensor_code: e.target.value.toUpperCase() })}
            aria-invalid={badCode}
            placeholder="e.g. MCC-03"
          />
        </label>
      )}
      <label className="text-sm">
        Name
        <input
          className={input}
          required
          value={f.sensor_name}
          onChange={set("sensor_name")}
          aria-invalid={badName}
        />
      </label>
      {!editing && (
        <label className="text-sm">
          Device type
          <select className={input} value={f.device_family} onChange={set("device_family")}>
            {DEVICE_FAMILIES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="text-sm">
        Land use
        <select className={input} value={f.land_use} onChange={set("land_use")}>
          {LAND_USES.map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        Latitude (decimal degrees)
        <input
          className={input}
          inputMode="decimal"
          value={f.latitude}
          onChange={set("latitude")}
          aria-invalid={badCoords}
          placeholder="-37.80"
        />
      </label>
      <label className="text-sm">
        Longitude (decimal degrees)
        <input
          className={input}
          inputMode="decimal"
          value={f.longitude}
          onChange={set("longitude")}
          aria-invalid={badCoords}
          placeholder="144.89"
        />
      </label>
      <label className="text-sm">
        Installation date (optional)
        <input
          type="date"
          className={input}
          value={f.installation_date}
          onChange={set("installation_date")}
        />
      </label>
      {editing && (
        <label className="flex items-center gap-2 self-end text-sm">
          <input
            type="checkbox"
            checked={f.location_verified}
            onChange={(e) => setF({ ...f, location_verified: e.target.checked })}
          />
          Location verified with the council
        </label>
      )}
      <label className="flex items-center gap-2 self-end text-sm">
        <input
          type="checkbox"
          checked={f.sensitive_receptor}
          onChange={(e) => setF({ ...f, sensitive_receptor: e.target.checked })}
        />
        Sensitive site (for example childcare, school or aged care)
      </label>
      <label className="text-sm sm:col-span-2">
        Notes (optional)
        <textarea
          className={input}
          rows={2}
          maxLength={500}
          value={f.notes}
          onChange={set("notes")}
        />
      </label>
      {message && (
        <p role="alert" className="text-sm text-red-800 sm:col-span-2 dark:text-red-300">
          {message}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-60"
        >
          {editing ? "Save changes" : "Register sensor"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-slate-400 px-4 py-2 text-sm"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

/** UC5 sensor management (admins with MFA). */
export default function AdminSensors() {
  const qc = useQueryClient();
  const sensors = useQuery({ queryKey: ["admin", "sensors"], queryFn: listAdminSensors });
  const [mode, setMode] = useState<
    { kind: "none" } | { kind: "new" } | { kind: "edit"; sensor: AdminSensor }
  >({ kind: "none" });
  const [secret, setSecret] = useState<{ label: string; value: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [confirm, setConfirm] = useState<AdminSensor | null>(null);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["admin", "sensors"] });
    qc.invalidateQueries({ queryKey: ["sensors"] }); // the dashboard map updates immediately
  };
  const register = useMutation({
    mutationFn: (f: Form) =>
      registerSensor({
        sensor_code: f.sensor_code.trim(),
        sensor_name: f.sensor_name.trim(),
        device_family: f.device_family,
        land_use: f.land_use,
        latitude: Number(f.latitude),
        longitude: Number(f.longitude),
        installation_date: f.installation_date || null,
        notes: f.notes.trim() || null,
        sensitive_receptor: f.sensitive_receptor,
      }),
    onSuccess: (r) => {
      setNotice(r.message);
      setSecret({ label: `Device key for ${r.sensor.sensor_code}`, value: r.device_key });
      setMode({ kind: "none" });
      refresh();
    },
  });
  const edit = useMutation({
    mutationFn: ({ id, f }: { id: number; f: Form }) =>
      updateSensor(id, {
        sensor_name: f.sensor_name.trim(),
        land_use: f.land_use,
        latitude: Number(f.latitude),
        longitude: Number(f.longitude),
        location_verified: f.location_verified,
        installation_date: f.installation_date || null,
        notes: f.notes.trim() || null,
        sensitive_receptor: f.sensitive_receptor,
      }),
    onSuccess: (r) => {
      setNotice(r.message);
      setMode({ kind: "none" });
      refresh();
    },
  });
  const retire = useMutation({
    mutationFn: (s: AdminSensor) =>
      s.status === "Active"
        ? decommissionSensor(s.sensor_id)
        : updateSensor(s.sensor_id, { status: "Active" }),
    onSuccess: (r) => {
      setNotice(r.message);
      setConfirm(null);
      refresh();
    },
  });
  const rotate = useMutation({
    mutationFn: (s: AdminSensor) => issueDeviceKey(s.sensor_id).then((r) => ({ r, s })),
    onSuccess: ({ r, s }) => {
      setSecret({ label: `New device key for ${s.sensor_code}`, value: r.device_key });
      refresh();
    },
  });

  if (sensors.isPending) return <Loading label="Loading sensors…" />;
  if (sensors.isError)
    return <ErrorMessage error={sensors.error} onRetry={() => sensors.refetch()} />;

  return (
    <section aria-labelledby="sensors-title" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="sensors-title" className="text-xl font-semibold">
          Sensors
        </h2>
        {mode.kind === "none" && (
          <button
            type="button"
            onClick={() => {
              register.reset();
              setMode({ kind: "new" });
            }}
            className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800"
          >
            Register a sensor
          </button>
        )}
      </div>
      <p role="status" className="text-sm text-emerald-800 dark:text-emerald-300">
        {notice}
      </p>
      {secret && (
        <OneTimeSecret
          label={secret.label}
          value={secret.value}
          note="Configure the device with this key now. It is stored only as a hash and will not be shown again."
          onDismiss={() => setSecret(null)}
        />
      )}
      {mode.kind === "new" && (
        <SensorForm
          initial={EMPTY}
          editing={false}
          busy={register.isPending}
          serverError={register.error instanceof ApiError ? register.error : null}
          onSubmit={(f) => register.mutate(f)}
          onCancel={() => setMode({ kind: "none" })}
        />
      )}
      {mode.kind === "edit" && (
        <SensorForm
          key={mode.sensor.sensor_id}
          initial={toForm(mode.sensor)}
          editing
          busy={edit.isPending}
          serverError={edit.error instanceof ApiError ? edit.error : null}
          onSubmit={(f) => edit.mutate({ id: mode.sensor.sensor_id, f })}
          onCancel={() => setMode({ kind: "none" })}
        />
      )}
      {(retire.error || rotate.error) && <ErrorMessage error={retire.error ?? rotate.error} />}

      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Registered sensors</caption>
          <thead className="border-b border-slate-400">
            <tr>
              <th scope="col" className="py-2 pr-3">
                Sensor
              </th>
              <th scope="col" className="pr-3">
                Device type
              </th>
              <th scope="col" className="pr-3">
                Land use
              </th>
              <th scope="col" className="pr-3">
                Location
              </th>
              <th scope="col" className="pr-3">
                Status
              </th>
              <th scope="col" className="pr-3">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {sensors.data.sensors.map((s) => (
              <tr
                key={s.sensor_id}
                className="border-b border-slate-200 align-top dark:border-slate-800"
              >
                <th scope="row" className="py-2 pr-3 font-normal">
                  <span className="font-medium">{s.sensor_code}</span>
                  <span className="block text-slate-600 dark:text-slate-400">{s.sensor_name}</span>
                </th>
                <td className="pr-3">
                  {DEVICE_FAMILIES.find((d) => d.value === s.device_family)?.label ??
                    s.device_family}
                </td>
                <td className="pr-3">{s.land_use}</td>
                <td className="pr-3">
                  {s.latitude?.toFixed(4)}, {s.longitude?.toFixed(4)}
                  <span className="block text-slate-600 dark:text-slate-400">
                    {s.location_verified ? "Verified" : "Not verified"}
                    {s.sensitive_receptor && " · sensitive site"}
                  </span>
                </td>
                <td className="pr-3">{s.status === "Active" ? "Active" : "Decommissioned"}</td>
                <td className="space-x-2 whitespace-nowrap pr-3">
                  <button
                    type="button"
                    className="underline"
                    aria-label={`Edit ${s.sensor_code}`}
                    onClick={() => {
                      edit.reset();
                      setMode({ kind: "edit", sensor: s });
                    }}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="underline"
                    aria-label={`${s.status === "Active" ? "Decommission" : "Reactivate"} ${s.sensor_code}`}
                    onClick={() => setConfirm(s)}
                  >
                    {s.status === "Active" ? "Decommission" : "Reactivate"}
                  </button>
                  <button
                    type="button"
                    className="underline"
                    aria-label={`${s.has_device_key ? "New device key" : "Issue device key"} for ${s.sensor_code}`}
                    onClick={() => rotate.mutate(s)}
                  >
                    {s.has_device_key ? "New device key" : "Issue device key"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {confirm && (
        <ConfirmDialog
          title={
            confirm.status === "Active"
              ? `Decommission ${confirm.sensor_code}?`
              : `Reactivate ${confirm.sensor_code}?`
          }
          confirmLabel={confirm.status === "Active" ? "Decommission" : "Reactivate"}
          danger={confirm.status === "Active"}
          busy={retire.isPending}
          onConfirm={() => retire.mutate(confirm)}
          onCancel={() => setConfirm(null)}
        >
          {confirm.status === "Active"
            ? "The sensor is marked inactive and stops accepting data. Its readings and history are kept and stay visible."
            : "The sensor becomes active again and can receive data."}
        </ConfirmDialog>
      )}
    </section>
  );
}
