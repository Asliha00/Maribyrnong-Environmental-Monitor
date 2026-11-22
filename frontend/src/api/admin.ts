/**
 * Administration (UC5) and data-quality calls. Every write sends the CSRF header (client.ts);
 * the server enforces manage_* + MFA or view_quality on each route.
 */
import { apiDelete, apiGet, apiPost, apiPut } from "./client";

export const DEVICE_FAMILIES = [
  { value: "mcc_aq", label: "MCC air-quality unit" },
  { value: "libelium", label: "Libelium environment sensor" },
  { value: "lora_r270", label: "LoRa R270 (temperature and pressure)" },
] as const;

/** Maribyrnong municipality bounding box (BUILD_PROMPT §4.5); the server checks it too. */
export const BOUNDS = { lat: [-37.835, -37.76], lon: [144.84, 144.925] } as const;
export const COORDINATE_MESSAGE =
  "Please enter valid GPS coordinates within the municipality boundary.";

export type AdminSensor = {
  sensor_id: number;
  sensor_code: string;
  sensor_name: string;
  device_family: string;
  hardware_id: string | null;
  latitude: number | null;
  longitude: number | null;
  location_verified: boolean;
  land_use: string;
  installation_date: string | null;
  status: "Active" | "Inactive";
  notes: string | null;
  has_device_key: boolean;
  sensitive_receptor: boolean;
  first_reading_utc: string | null;
  last_reading_utc: string | null;
};
export type SensorInput = {
  sensor_code: string;
  sensor_name: string;
  device_family: string;
  land_use: string;
  latitude: number;
  longitude: number;
  installation_date?: string | null;
  notes?: string | null;
  sensitive_receptor?: boolean;
};
export type SensorChange = Partial<
  Pick<
    AdminSensor,
    | "sensor_name"
    | "land_use"
    | "latitude"
    | "longitude"
    | "location_verified"
    | "notes"
    | "sensitive_receptor"
  >
> & { installation_date?: string | null; status?: "Active" };

export const listAdminSensors = () => apiGet<{ sensors: AdminSensor[] }>("/admin/sensors");
export const registerSensor = (body: SensorInput) =>
  apiPost<{ message: string; sensor: AdminSensor; device_key: string }>("/admin/sensors", body);
export const updateSensor = (id: number, body: SensorChange) =>
  apiPut<{ message: string; sensor: AdminSensor }>(`/admin/sensors/${id}`, body);
export const decommissionSensor = (id: number) =>
  apiDelete<{ message: string; sensor: AdminSensor }>(`/admin/sensors/${id}`);
export const issueDeviceKey = (id: number) =>
  apiPost<{ message: string; device_key: string }>(`/admin/sensors/${id}/device-key`);

export type AdminUser = {
  user_id: number;
  username: string;
  email: string;
  role_id: 1 | 2 | 3;
  role_name: string;
  is_active: boolean;
  must_change_password: boolean;
  mfa_enabled: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string | null;
};
/** The two roles of the proposal's use cases (D-035). Role 1 "General User" is retired: it stays
 *  in the roles table for old records but can no longer be given to anyone. */
export const ROLES = [
  { id: 2, name: "Environmental Analyst" },
  { id: 3, name: "System Administrator" },
] as const;
type WithPassword = { message: string; user: AdminUser; temporary_password: string };

export const listUsers = () => apiGet<{ users: AdminUser[] }>("/admin/users");
export const createUser = (body: { username: string; email: string; role_id: number }) =>
  apiPost<WithPassword>("/admin/users", body);
export const updateUser = (id: number, body: { role_id?: number; is_active?: boolean }) =>
  apiPut<{ message: string; user: AdminUser }>(`/admin/users/${id}`, body);
export const resetPassword = (id: number) =>
  apiPost<WithPassword>(`/admin/users/${id}/reset-password`);
export const resetMfa = (id: number) =>
  apiPost<{ message: string; user: AdminUser }>(`/admin/users/${id}/reset-mfa`);

export type AdminThreshold = {
  threshold_id: number;
  variable: string;
  variable_label: string;
  unit: string;
  statistic: string;
  period: string;
  operator: string;
  value: number;
  label: string;
  source: string | null;
  updated_at: string | null;
  exceedance_days: number;
};
export type ThresholdChange = {
  history_id: number;
  threshold_id: number;
  old_value: number | null;
  new_value: number;
  reason: string;
  changed_at: string | null;
  changed_by: string | null;
};
export type ThresholdListing = { thresholds: AdminThreshold[]; history: ThresholdChange[] };
export const listThresholds = () => apiGet<ThresholdListing>("/admin/thresholds");
export const updateThreshold = (id: number, value: number, reason: string) =>
  apiPut<ThresholdListing & { message: string }>(`/admin/thresholds/${id}`, { value, reason });

export type UploadSummary = {
  run_id: number;
  sensor_code: string;
  rows_read: number;
  rows_inserted: number;
  rows_duplicate: number;
  rows_already_stored: number;
  values_rejected: number;
  values_flagged: number;
  archived: boolean;
  seconds_loading: number;
  seconds_total: number;
};
export const ingestUpload = (pathname: string, sensorId: number, force: boolean) =>
  apiPost<{ message: string; summary: UploadSummary }>("/admin/ingest-upload", {
    pathname,
    sensor_id: sensorId,
    force,
  });

// ---------- data quality (view_quality) ----------
export type CompletenessRow = {
  sensor_id: number;
  sensor_code: string;
  sensor_name: string;
  status: string;
  valid_days: number;
  days: number;
  avg_pct: number;
  cells: { date: string; pct: number; valid: boolean }[];
};
export type Completeness = {
  variable: string;
  label: string;
  start: string;
  end: string;
  min_valid_pct: number;
  sensors: CompletenessRow[];
};
export type ErrorEntry = {
  error_id: number;
  sensor_id: number | null;
  sensor_code: string | null;
  ts_utc: string | null;
  error_type: string;
  variable: string | null;
  raw_value: string | null;
  description: string | null;
  ingestion_run_id: number | null;
  logged_at: string | null;
};
export type IngestionRun = {
  run_id: number;
  source_file: string;
  file_sha256: string;
  sensor_code: string | null;
  rows_read: number | null;
  rows_inserted: number | null;
  rows_duplicate: number | null;
  values_rejected: number | null;
  values_flagged: number | null;
  started_at: string | null;
  finished_at: string | null;
  completed: boolean;
  archived: boolean;
};
export type FlagCount = {
  sensor_code: string;
  flag: string;
  description: string;
  readings: number;
};
export type SecurityEvent = {
  audit_id: number;
  created_at: string | null;
  ip_address: string | null;
  failed_logins_last_10_min?: number;
};

export const getCompleteness = (variable: string, start: string, end: string) =>
  apiGet<Completeness>(
    `/quality/completeness?${new URLSearchParams({ variable, start, end }).toString()}`,
  );
export const getErrors = (filters: Record<string, string>) =>
  apiGet<{ total: number; items: ErrorEntry[]; by_type: Record<string, number> }>(
    `/quality/errors?${new URLSearchParams(filters).toString()}`,
  );
export const getRuns = () => apiGet<{ total: number; items: IngestionRun[] }>("/quality/runs");
export const getFlags = () => apiGet<{ total: number; items: FlagCount[] }>("/quality/flags");
export const getSecurityEvents = () => apiGet<{ items: SecurityEvent[] }>("/quality/security");
