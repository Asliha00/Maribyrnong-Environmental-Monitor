/** Insights API (§4.3): every number on the Insights page comes from these calls. */
import { apiGetAnalysis } from "./client";

export type Comparison = {
  difference: number | null;
  low: number | null;
  high: number | null;
  days: number;
  direction: "rising" | "falling" | "no clear change" | "not enough data";
};
export type Frame = {
  start: string;
  end: string;
  days: number;
  months: number;
  thresholds: { hot_day_c: number | null; pm25_standard: number | null };
};
export type Site = {
  sensor_code: string;
  sensor_name: string;
  land_use: string;
  sensitive_receptor: boolean;
  location_verified: boolean;
  temperature_days: number;
  mean_temperature_c: number | null;
  temperature_vs_others: Comparison | null;
  temperature_vs_others_c_rank?: number;
  hot_days: number | null;
  hot_day_share: {
    hot_days_reported: number;
    hot_days_reached: number;
    share_pct: number | null;
  } | null;
  pm25_days: number;
  mean_pm25: number | null;
  pm25_vs_others: Comparison | null;
  pm25_vs_others_ugm3_rank?: number;
  pm25_exceedance_days: number | null;
};
export type Disparities = Frame & {
  sites: Site[];
  rankings: Record<"temperature" | "hot_days" | "pm25" | "pm25_exceedances", string[]>;
  by_land_use: {
    land_use: string;
    sensors: string[];
    temperature_vs_others_c: number | null;
    hot_day_share_pct: number | null;
    pm25_vs_others_ugm3: number | null;
  }[];
  equity: {
    sensor_code: string;
    sensor_name: string;
    land_use: string;
    more_exposed: string[];
    comparison: Record<
      string,
      Comparison & { unit?: string; label?: string; share_pct?: number | null }
    >;
  }[];
};
export type GroupDifference = {
  difference_c: number | null;
  low: number | null;
  high: number | null;
  hours: number;
  days: number;
  direction: Comparison["direction"];
};
export type Green = Frame & {
  all_hours: GroupDifference;
  hot_afternoons: GroupDifference;
  park_sensors: string[];
  other_sensors: string[];
  hot_day_threshold_c: number | null;
  hot_days: number;
  park_sensor_valid_hours: Record<string, number>;
  hours_in_range: number;
  caveats: string[];
};
export type Trend = {
  slope_per_month: number;
  low: number;
  high: number;
  months: number;
  direction: Comparison["direction"];
};
export type Trends = Frame & {
  trends: Record<
    string,
    {
      sensor_code: string;
      land_use: string;
      unit: string;
      months: number;
      monthly: { month: string; mean: number }[];
      absolute: Trend | null;
      relative: Trend | null;
    }[]
  >;
};
export type Patterns = Frame & {
  diurnal: Record<string, { sensor_code: string; land_use: string; hours: (number | null)[] }[]>;
  seasonal: Record<
    string,
    { sensor_code: string; seasons: { season: string; mean: number | null; valid: boolean }[] }[]
  >;
};
export type Evidence = { label: string; value: number | null; unit: string; detail: string };
export type Recommendation = {
  id: string;
  priority: "high" | "medium";
  title: string;
  text: string;
  evidence: Evidence[];
};
export type Recommendations = Frame & {
  network: {
    low_completeness: { sensor_code: string; completeness_pct: number }[];
    not_fitted: { sensor_code: string; variable: string; label: string }[];
    sensors_per_land_use: Record<string, number>;
    uncovered_land_uses: string[];
    single_sensor_land_uses: string[];
  };
  recommendations: Recommendation[];
};

const get =
  <T>(name: string) =>
  () =>
    apiGetAnalysis<T>(`/analysis/${name}`);
export const getDisparities = get<Disparities>("disparities");
export const getGreen = get<Green>("green-infrastructure");
export const getTrends = get<Trends>("trends");
export const getPatterns = get<Patterns>("diurnal");
export const getRecommendations = get<Recommendations>("recommendations");
