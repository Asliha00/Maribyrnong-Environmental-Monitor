import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { describeDifference } from "../src/components/insights/DifferencePlot";

const api = vi.hoisted(() => ({
  getDisparities: vi.fn(),
  getGreen: vi.fn(),
  getTrends: vi.fn(),
  getPatterns: vi.fn(),
  getRecommendations: vi.fn(),
}));
vi.mock("../src/api/insights", async (original) => ({
  ...(await original<typeof import("../src/api/insights")>()),
  ...api,
}));
vi.mock("../src/api/data", async (original) => ({
  ...(await original<typeof import("../src/api/data")>()),
  getSensors: vi.fn(async () => ({ sensors: [] })),
}));
// Recharts needs a real layout engine; the charts have their own table views tested elsewhere
vi.mock("../src/components/insights/DiurnalChart", () => ({ default: () => null }));

const { default: InsightsPage, limitations } = await import("../src/pages/InsightsPage");

const frame = (months: number) => ({
  start: "2025-02-16",
  end: "2026-02-16",
  days: 366,
  months,
  thresholds: { hot_day_c: 35, pm25_standard: 25 },
});
const cmp = (difference: number, direction: string, days = 300) => ({
  difference,
  low: difference - 0.1,
  high: difference + 0.1,
  days,
  direction,
});

/** One synthetic world; `parkDelta` decides whether parks look cooler or warmer. */
function world(parkDelta: number, sites: number, months: number) {
  const site = (i: number) => ({
    sensor_code: `S-${i}`,
    sensor_name: `Site ${i}`,
    land_use: i === 0 ? "Parkland" : "Residential",
    sensitive_receptor: i === 1,
    location_verified: i !== 2,
    temperature_days: 300,
    mean_temperature_c: 18,
    temperature_vs_others: cmp(
      i === 0 ? parkDelta : 0.4,
      i === 0 && parkDelta < 0 ? "falling" : "rising",
    ),
    hot_days: 3,
    hot_day_share: { hot_days_reported: 5, hot_days_reached: 3, share_pct: 60 },
    pm25_days: 300,
    mean_pm25: 6,
    pm25_vs_others: cmp(0.3, "rising"),
    pm25_exceedance_days: 0,
  });
  const all = Array.from({ length: sites }, (_, i) => site(i));
  const group = (d: number) => ({
    difference_c: d,
    low: d - 0.2,
    high: d + 0.2,
    hours: 900,
    days: 40,
    direction: d < 0 ? "falling" : "rising",
  });
  api.getDisparities.mockResolvedValue({
    ...frame(months),
    sites: all,
    rankings: {
      temperature: all.map((s) => s.sensor_code),
      hot_days: [],
      pm25: [],
      pm25_exceedances: [],
    },
    by_land_use: [],
    equity: [
      {
        sensor_code: "S-1",
        sensor_name: "Site 1",
        land_use: "Residential",
        more_exposed: ["temperature"],
        comparison: { temperature: { ...cmp(0.4, "rising"), unit: "°C", label: "Temperature" } },
      },
    ],
  });
  api.getGreen.mockResolvedValue({
    ...frame(months),
    all_hours: group(parkDelta),
    hot_afternoons: group(parkDelta * 2),
    park_sensors: ["S-0"],
    other_sensors: all.slice(1).map((s) => s.sensor_code),
    hot_day_threshold_c: 35,
    hot_days: 8,
    park_sensor_valid_hours: { "S-0": 5000 },
    hours_in_range: 8784,
    caveats: [`Only 1 park sensor (S-0) and ${sites - 1} other sensors.`],
  });
  api.getTrends.mockResolvedValue({ ...frame(months), trends: { temperature_c: [] } });
  api.getPatterns.mockResolvedValue({ ...frame(months), diurnal: {}, seasonal: {} });
  api.getRecommendations.mockResolvedValue({
    ...frame(months),
    network: {
      low_completeness: [{ sensor_code: "S-0", completeness_pct: 57 }],
      not_fitted: [],
      sensors_per_land_use: { Parkland: 1, Residential: sites - 1 },
      uncovered_land_uses: [],
      single_sensor_land_uses: ["Parkland"],
    },
    recommendations: [
      {
        id: "x",
        priority: "high",
        title: `Recommendation from ${sites} sites`,
        text: "From the data.",
        evidence: [{ label: "Evidence", value: parkDelta, unit: "°C", detail: "40 days" }],
      },
    ],
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <InsightsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => Object.values(api).forEach((f) => f.mockReset()));

describe("insights page", () => {
  it("states what the data say when parks are cooler", async () => {
    world(-1.5, 4, 13);
    renderPage();
    expect(
      await screen.findByText(/parks were 1\.50 °C cooler than other sites/),
    ).toBeInTheDocument();
    expect(screen.getByText("Recommendation from 4 sites")).toBeInTheDocument();
    expect(screen.getByText(/13 months of data/)).toBeInTheDocument();
    expect(screen.getByText(/4 sensors, 1 land use with only one sensor/)).toBeInTheDocument();
    expect(screen.getByText(/High priority/)).toBeInTheDocument(); // priority in words, not colour
  });

  it("says the opposite when the data say the opposite (no hard-coded findings)", async () => {
    world(1.2, 6, 7);
    renderPage();
    expect(
      await screen.findByText(/parks were 1\.20 °C warmer than other sites/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/cooler than other sites/)).not.toBeInTheDocument();
    expect(screen.getByText(/7 months of data/)).toBeInTheDocument();
    expect(screen.getByText("Recommendation from 6 sites")).toBeInTheDocument();
  });

  it("shows the API's message when insights fail", async () => {
    world(-1, 3, 12);
    api.getGreen.mockRejectedValue(new Error("boom"));
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("describes a difference in words, including uncertainty", () => {
    expect(describeDifference(cmp(0.48, "rising") as never, "°C", ["warmer", "cooler"])).toBe(
      "0.48 °C warmer",
    );
    expect(
      describeDifference(cmp(-0.05, "no clear change") as never, "°C", ["warmer", "cooler"]),
    ).toBe("0.05 °C cooler (not distinguishable from zero)");
    expect(describeDifference(null, "°C")).toBe("not enough data");
  });

  it("builds the limitations from the numbers", () => {
    world(-1, 5, 11);
    return Promise.all([api.getDisparities(), api.getRecommendations()]).then(([d, r]) => {
      expect(limitations(d, r)).toEqual([
        "11 months of data (2025-02-16 to 2026-02-16)",
        "5 sensors, 1 land use with only one sensor",
        "1 sensor location not yet verified",
        "S-0 below 75% of expected readings",
      ]);
    });
  });
});
