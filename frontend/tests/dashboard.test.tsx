import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError, NETWORK_MESSAGE, TIMEOUT_MESSAGE } from "../src/api/client";
import {
  filterQuery,
  type Filters,
  type Meta,
  type ReadingsResult,
  type Sensor,
} from "../src/api/data";
import FilterPanel, { SENSOR_NOT_FOUND } from "../src/components/FilterPanel";
import { ErrorMessage } from "../src/components/StatusMessage";
import SummaryCards from "../src/components/SummaryCards";
import { mergeSeries, thresholdsToDraw } from "../src/lib/chart";
import { defaultFilters, INVALID_RANGE_MESSAGE, validateFilters } from "../src/lib/filters";
import { formatBucket, formatValue } from "../src/lib/format";
import { rampColor, SEQUENTIAL, seriesColor, slotsByCode } from "../src/lib/palette";

const META: Meta = {
  variables: [
    { variable: "temperature_c", label: "Temperature", unit: "°C", sensor_count: 2 },
    { variable: "pm25", label: "PM2.5", unit: "µg/m³", sensor_count: 2 },
  ],
  land_uses: ["Residential", "Industrial", "Parkland", "Transport corridor", "Commercial"],
  resolutions: ["hour", "day", "month", "season", "raw"],
  data_range: { first_day: "2025-02-16", last_day: "2026-02-16" },
  thresholds: [
    {
      threshold_id: 1,
      variable: "pm25",
      period: "day",
      operator: ">",
      value: 25,
      label: "PM2.5 24-hour standard",
      source: "NEPM",
    },
    {
      threshold_id: 3,
      variable: "temperature_c",
      period: "day_max",
      operator: ">=",
      value: 35,
      label: "Hot day",
      source: "x",
    },
  ],
  limits: { raw_max_days: 7, hour_max_days: 92, max_sensor_ids: 20 },
};

const sensor = (id: number, code: string, name: string): Sensor => ({
  sensor_id: id,
  sensor_code: code,
  sensor_name: name,
  device_family: "mcc_aq",
  land_use: "Parkland",
  status: "Active",
  latitude: -37.8,
  longitude: 144.9,
  location_verified: false,
  variables: [{ variable: "temperature_c", label: "Temperature", unit: "°C" }],
  latest: null,
  completeness: {},
  first_reading_utc: null,
  last_reading_utc: null,
  quality_notes: [],
});
const SENSORS = [
  sensor(1, "FP-AMEN", "Footscray Park - Amenities Block"),
  sensor(2, "MCC-01", "MCC Air Quality Unit 1"),
];

function panel(applied: Filters, onApply = vi.fn()) {
  render(
    <FilterPanel
      meta={META}
      sensors={SENSORS}
      applied={applied}
      busy={false}
      onApply={onApply}
      onReset={() => {}}
    />,
  );
  return onApply;
}

describe("filters", () => {
  it("defaults to the last 30 days of data, daily temperature, flagged excluded", () => {
    expect(defaultFilters(META)).toEqual({
      variable: "temperature_c",
      resolution: "day",
      start: "2026-01-18",
      end: "2026-02-16",
      landUses: [],
      sensorIds: [],
      excludeFlagged: true,
    });
  });

  it("rejects reversed and out-of-data ranges with the UC2 message", () => {
    const f = defaultFilters(META);
    expect(validateFilters({ ...f, start: "2026-02-10", end: "2026-02-01" }, META)).toBe(
      INVALID_RANGE_MESSAGE,
    );
    expect(validateFilters({ ...f, start: "2024-01-01", end: "2024-02-01" }, META)).toBe(
      INVALID_RANGE_MESSAGE,
    );
    expect(validateFilters(f, META)).toBeNull();
  });

  it("limits raw to 7 days and hourly to 92 days", () => {
    const f = defaultFilters(META);
    expect(
      validateFilters({ ...f, resolution: "raw", start: "2026-02-01", end: "2026-02-16" }, META),
    ).toMatch(/up to 7 days/);
    expect(
      validateFilters({ ...f, resolution: "raw", start: "2026-02-10", end: "2026-02-16" }, META),
    ).toBeNull();
    expect(
      validateFilters({ ...f, resolution: "hour", start: "2025-02-16", end: "2026-02-16" }, META),
    ).toMatch(/up to 92 days/);
  });

  it("builds repeated query keys for lists", () => {
    const f: Filters = {
      ...defaultFilters(META),
      landUses: ["Parkland", "Industrial"],
      sensorIds: [1, 2],
    };
    const q = new URLSearchParams(filterQuery(f));
    expect(q.getAll("land_use")).toEqual(["Parkland", "Industrial"]);
    expect(q.getAll("sensor_ids")).toEqual(["1", "2"]);
    expect(q.get("exclude_flagged")).toBe("true");
  });
});

describe("filter panel", () => {
  it("shows 'Sensor not found.' and adds a matching sensor", async () => {
    panel(defaultFilters(META));
    const search = screen.getByLabelText("Sensors");
    await userEvent.type(search, "zzz");
    expect(screen.getByText(SENSOR_NOT_FOUND)).toBeInTheDocument();
    await userEvent.clear(search);
    await userEvent.type(search, "amen");
    await userEvent.click(screen.getByRole("button", { name: /FP-AMEN/ }));
    expect(screen.getByRole("list", { name: "Chosen sensors" })).toHaveTextContent("FP-AMEN");
  });

  it("does not apply invalid filters and shows the message", async () => {
    const onApply = panel({ ...defaultFilters(META), start: "2026-02-10", end: "2026-02-01" });
    await userEvent.click(screen.getByRole("button", { name: "Apply Filter" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Invalid date range selected.");
    expect(onApply).not.toHaveBeenCalled();
  });

  it("applies the chosen options", async () => {
    const onApply = panel(defaultFilters(META));
    await userEvent.selectOptions(screen.getByLabelText("Variable"), "pm25");
    await userEvent.click(screen.getByRole("radio", { name: "Monthly" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Parkland" }));
    await userEvent.click(screen.getByRole("checkbox", { name: /Exclude flagged readings/ }));
    await userEvent.click(screen.getByRole("button", { name: "Apply Filter" }));
    expect(onApply).toHaveBeenCalledWith(
      expect.objectContaining({
        variable: "pm25",
        resolution: "month",
        landUses: ["Parkland"],
        excludeFlagged: false,
      }),
    );
  });
});

describe("messages", () => {
  it("shows the server's 'no data' text as a status, not an error", () => {
    render(
      <ErrorMessage
        error={new ApiError(404, "no_data", "No data available for the selected filters.")}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "No data available for the selected filters.",
    );
  });

  it("offers a retry for timeouts and network failures with the UC2 wording", async () => {
    const retry = vi.fn();
    const { unmount } = render(
      <ErrorMessage error={new ApiError(0, "timeout", TIMEOUT_MESSAGE)} onRetry={retry} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The request is taking longer than expected. Please try again.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
    unmount();
    render(<ErrorMessage error={new ApiError(0, "network", NETWORK_MESSAGE)} />);
    expect(screen.getByRole("alert")).toHaveTextContent(/contact your system administrator/);
  });
});

describe("chart helpers", () => {
  const series = [
    {
      sensor_id: 1,
      sensor_code: "A",
      sensor_name: "A",
      land_use: "Parkland",
      location_verified: true,
      points: [
        {
          t: "2025-07-02",
          mean: 2,
          min: 1,
          max: 3,
          n: 96,
          completeness_pct: 100,
          valid: true,
          flagged: false,
        },
        {
          t: "2025-07-01",
          mean: 1,
          min: 0,
          max: 2,
          n: 40,
          completeness_pct: 42,
          valid: false,
          flagged: false,
        },
      ],
      summary: {
        mean: 1.6,
        min: 0,
        max: 3,
        n: 136,
        completeness_pct: 71,
        valid_buckets: 1,
        buckets: 2,
      },
    },
  ];

  it("separates invalid buckets so they can be greyed out", () => {
    const { rows } = mergeSeries(series);
    expect(rows.map((r) => r.t)).toEqual(["2025-07-01", "2025-07-02"]);
    expect(rows[0]).toMatchObject({ A: null, A__invalid: 1 });
    expect(rows[1]).toMatchObject({ A: 2, A__invalid: null });
  });

  it("draws 24-hour standards only on daily means", () => {
    expect(thresholdsToDraw(META.thresholds, "day").map((t) => t.threshold_id)).toEqual([1]);
    expect(thresholdsToDraw(META.thresholds, "month")).toEqual([]);
  });

  it("keeps a sensor's colour whatever the filter", () => {
    const all = slotsByCode(["MCC-02", "FP-AMEN", "MCC-01"]);
    expect(all).toEqual({ "FP-AMEN": 0, "MCC-01": 1, "MCC-02": 2 });
    expect(seriesColor(all["MCC-02"])).toBe("var(--series-3)");
  });

  it("maps magnitude onto the ramp from light to dark", () => {
    expect(rampColor(0, 0, 10)).toBe(SEQUENTIAL[0]);
    expect(rampColor(10, 0, 10)).toBe(SEQUENTIAL[SEQUENTIAL.length - 1]);
  });

  it("formats values with units and buckets readably", () => {
    expect(formatValue(21.456, "°C", "temperature_c")).toBe("21.5 °C");
    expect(formatValue(55, "%", "humidity_pct")).toBe("55%");
    expect(formatValue(null, "°C")).toBe("No data");
    expect(formatBucket("2025-07-15")).toBe("15 Jul 2025");
    expect(formatBucket("2025-07")).toBe("Jul 2025");
    expect(formatBucket("Summer 2025–26")).toBe("Summer 2025–26");
  });

  it("summary cards show units and completeness", () => {
    const result = {
      variable: "temperature_c",
      label: "Temperature",
      unit: "°C",
      resolution: "day",
      start: "",
      end: "",
      exclude_flagged: true,
      series: [],
      thresholds: [],
      notes: [],
      summary: {
        mean: 14.04,
        min: 10,
        max: 17,
        n: 10,
        completeness_pct: 87.5,
        valid_buckets: 7,
        buckets: 8,
      },
    } as ReadingsResult;
    render(<SummaryCards result={result} />);
    expect(screen.getByText("14 °C")).toBeInTheDocument();
    expect(screen.getByText("87.5%")).toBeInTheDocument();
    expect(screen.getByText("7 of 8 periods at least 75% complete")).toBeInTheDocument();
  });
});
