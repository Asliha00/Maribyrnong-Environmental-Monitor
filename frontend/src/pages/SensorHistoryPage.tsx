import { useState } from "react";
import { Link, useParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { getMeta, getReadings, getSensor, getSensors, type Resolution } from "../api/data";
import SensorPanel from "../components/SensorPanel";
import { ErrorMessage, Loading } from "../components/StatusMessage";
import SummaryCards from "../components/SummaryCards";
import TimeSeriesChart from "../components/TimeSeriesChart";
import { slotsByCode } from "../lib/palette";

const RESOLUTIONS: { value: Resolution; label: string }[] = [
  { value: "day", label: "Daily" },
  { value: "month", label: "Monthly" },
  { value: "season", label: "Seasonal" },
];

/** A sensor's history (linked from the sensor panel): any variable it measures, over the
 * whole data period. */
export default function SensorHistoryPage() {
  const id = Number(useParams().sensorId);
  const valid = Number.isInteger(id) && id > 0;
  const meta = useQuery({ queryKey: ["meta"], queryFn: getMeta, staleTime: 10 * 60_000 });
  const all = useQuery({ queryKey: ["sensors"], queryFn: getSensors, staleTime: 60_000 });
  const sensor = useQuery({
    queryKey: ["sensor", id],
    queryFn: () => getSensor(id),
    enabled: valid,
    retry: false,
  });
  const [variable, setVariable] = useState<string | null>(null);
  const [resolution, setResolution] = useState<Resolution>("day");
  const chosen = variable ?? sensor.data?.variables[0]?.variable ?? null;
  const range = meta.data?.data_range;

  const readings = useQuery({
    queryKey: ["history", id, chosen, resolution, range],
    queryFn: () =>
      getReadings({
        variable: chosen as string,
        resolution,
        start: range?.first_day as string,
        end: range?.last_day as string,
        landUses: [],
        sensorIds: [id],
        excludeFlagged: true,
      }),
    enabled: valid && !!chosen && !!range?.first_day,
    retry: false,
  });

  if (!valid) return <ErrorMessage error={new Error("bad id")} />;
  if (sensor.isPending || meta.isPending) return <Loading label="Loading sensor…" />;
  if (sensor.isError) return <ErrorMessage error={sensor.error} />;
  const slots = slotsByCode((all.data?.sensors ?? []).map((s) => s.sensor_code));

  return (
    <div className="space-y-4">
      <p>
        <Link to="/" className="text-sm underline">
          ← Back to the dashboard
        </Link>
      </p>
      <h1 className="text-2xl font-semibold">Sensor history: {sensor.data.sensor_code}</h1>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
        <SensorPanel sensor={sensor.data} variable={chosen ?? ""} onClose={() => history.back()} />
        <div className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <label className="text-sm">
              Variable
              <select
                value={chosen ?? ""}
                onChange={(e) => setVariable(e.target.value)}
                className="mt-1 block rounded border border-slate-400 bg-white px-2 py-1.5 text-slate-900 dark:bg-slate-800 dark:text-slate-100"
              >
                {sensor.data.variables.map((v) => (
                  <option key={v.variable} value={v.variable}>
                    {v.label} ({v.unit})
                  </option>
                ))}
              </select>
            </label>
            <fieldset>
              <legend className="text-sm">Resolution</legend>
              <div className="mt-1 flex gap-3">
                {RESOLUTIONS.map((r) => (
                  <label key={r.value} className="inline-flex items-center gap-1.5 text-sm">
                    <input
                      type="radio"
                      name="history-resolution"
                      checked={resolution === r.value}
                      onChange={() => setResolution(r.value)}
                    />
                    {r.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
          {readings.isFetching && <Loading label="Loading history…" />}
          {readings.isError && !readings.isFetching && (
            <ErrorMessage error={readings.error} onRetry={() => readings.refetch()} />
          )}
          {readings.data && !readings.isError && (
            <>
              <SummaryCards result={readings.data} />
              <TimeSeriesChart result={readings.data} slots={slots} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
