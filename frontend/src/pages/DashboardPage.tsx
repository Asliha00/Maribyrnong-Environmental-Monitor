import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getHeatmap, getMeta, getReadings, getSensors, type Filters } from "../api/data";
import AlertsPanel from "../components/AlertsPanel";
import ExportControl from "../components/ExportControl";
import FilterPanel from "../components/FilterPanel";
import SensorMap, { type MapMode } from "../components/SensorMap";
import SensorPanel from "../components/SensorPanel";
import { ErrorMessage, Loading } from "../components/StatusMessage";
import SummaryCards from "../components/SummaryCards";
import TemporalHeatmap from "../components/TemporalHeatmap";
import TimeSeriesChart from "../components/TimeSeriesChart";
import { daysInclusive, defaultFilters, HEATMAP_MAX_DAYS } from "../lib/filters";
import { slotsByCode } from "../lib/palette";

/**
 * UC2 dashboard: map (left/top) · filter panel · visualisation panel. Queries run only for
 * APPLIED filters; the filter panel keeps its own draft until "Apply Filter".
 */
export default function DashboardPage() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: getMeta, staleTime: 10 * 60_000 });
  const sensors = useQuery({ queryKey: ["sensors"], queryFn: getSensors, staleTime: 60_000 });
  // Applied filters: the defaults (last 30 days of data) until the user applies their own
  const [chosen, setFilters] = useState<Filters | null>(null);
  const filters = useMemo(
    () => chosen ?? (meta.data ? defaultFilters(meta.data) : null),
    [chosen, meta.data],
  );
  // UC3: Export unlocks once the user has pressed Apply Filter (team choice, DECISIONS.md D-032)
  const [applied, setApplied] = useState(false);
  const [mapMode, setMapMode] = useState<MapMode>("latest");
  const [selected, setSelected] = useState<number | null>(null);

  const readings = useQuery({
    queryKey: ["readings", filters],
    queryFn: () => getReadings(filters as Filters),
    enabled: !!filters,
    retry: false,
  });
  const heatmapAllowed = !!filters && daysInclusive(filters.start, filters.end) <= HEATMAP_MAX_DAYS;
  const heatmap = useQuery({
    queryKey: ["heatmap", filters && { ...filters, resolution: undefined }],
    queryFn: () => getHeatmap(filters as Filters),
    enabled: heatmapAllowed && filters?.resolution !== "raw",
    retry: false,
  });

  const sensorList = useMemo(() => sensors.data?.sensors ?? [], [sensors.data]);
  const slots = useMemo(() => slotsByCode(sensorList.map((s) => s.sensor_code)), [sensorList]);
  const periodMeans = useMemo(
    () =>
      Object.fromEntries((readings.data?.series ?? []).map((s) => [s.sensor_code, s.summary.mean])),
    [readings.data],
  );

  if (meta.isPending || sensors.isPending || !filters)
    return <Loading label="Loading the dashboard…" />;
  if (meta.isError) return <ErrorMessage error={meta.error} onRetry={() => meta.refetch()} />;
  if (sensors.isError)
    return <ErrorMessage error={sensors.error} onRetry={() => sensors.refetch()} />;

  const variable =
    meta.data.variables.find((v) => v.variable === filters.variable) ?? meta.data.variables[0];
  const selectedSensor = sensorList.find((s) => s.sensor_id === selected) ?? null;
  const busy = readings.isFetching || heatmap.isFetching;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <div className="space-y-4">
          <SensorMap
            sensors={sensorList}
            variable={variable}
            mode={mapMode}
            onModeChange={setMapMode}
            periodMeans={periodMeans}
            selectedId={selected}
            onSelect={setSelected}
          />
          {selectedSensor && (
            <SensorPanel
              sensor={selectedSensor}
              variable={filters.variable}
              onClose={() => setSelected(null)}
            />
          )}
          <div className="rounded border border-slate-300 p-4 dark:border-slate-700">
            <FilterPanel
              key={JSON.stringify(filters)}
              meta={meta.data}
              sensors={sensorList}
              applied={filters}
              busy={busy}
              onApply={(f) => {
                setFilters(f);
                setApplied(true);
              }}
              onReset={() => {
                setFilters(defaultFilters(meta.data));
                setApplied(false);
              }}
            />
          </div>
        </div>

        <div className="min-w-0 space-y-4" aria-busy={busy}>
          <ExportControl filters={filters} applied={applied} />
          {readings.isFetching && <Loading label="Loading data…" />}
          {readings.isError && !readings.isFetching && (
            <ErrorMessage error={readings.error} onRetry={() => readings.refetch()} />
          )}
          {readings.data && !readings.isError && (
            <>
              <SummaryCards result={readings.data} />
              {readings.data.notes.length > 0 && (
                <ul className="list-disc space-y-1 rounded bg-slate-100 p-3 pl-7 text-xs text-slate-800 dark:bg-slate-800 dark:text-slate-100">
                  {readings.data.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
              <TimeSeriesChart result={readings.data} slots={slots} />
            </>
          )}
          {filters.resolution === "raw" ? (
            <p className="text-sm text-slate-600 dark:text-slate-400">
              The hour-by-month pattern is not shown for raw readings; choose another resolution to
              see it.
            </p>
          ) : !heatmapAllowed ? (
            <p className="text-sm text-slate-600 dark:text-slate-400">
              The hour-by-month pattern covers up to {HEATMAP_MAX_DAYS} days; choose a shorter range
              to see it.
            </p>
          ) : heatmap.isError ? (
            <ErrorMessage error={heatmap.error} onRetry={() => heatmap.refetch()} />
          ) : heatmap.data ? (
            <TemporalHeatmap result={heatmap.data} />
          ) : null}
          <AlertsPanel filters={filters} />
        </div>
      </div>
    </div>
  );
}
