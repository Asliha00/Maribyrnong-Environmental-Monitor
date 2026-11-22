import { CircleMarker, MapContainer, TileLayer, Tooltip } from "react-leaflet";
import type { Sensor, VariableMeta } from "../api/data";
import { formatValue } from "../lib/format";
import { rampColor, SEQUENTIAL } from "../lib/palette";
import InfoTip, { GLOSSARY } from "./InfoTip";

export type MapMode = "latest" | "mean";

type Props = {
  sensors: Sensor[];
  variable: VariableMeta;
  mode: MapMode;
  onModeChange: (mode: MapMode) => void;
  periodMeans: Record<string, number | null>;
  selectedId: number | null;
  onSelect: (sensorId: number) => void;
};

const CENTRE: [number, number] = [-37.8, 144.895]; // Maribyrnong

export function valueFor(
  sensor: Sensor,
  variable: string,
  mode: MapMode,
  periodMeans: Record<string, number | null>,
) {
  if (!sensor.variables.some((v) => v.variable === variable)) return undefined; // not measured
  return mode === "latest"
    ? (sensor.latest?.values[variable] ?? null)
    : (periodMeans[sensor.sensor_code] ?? null);
}

/**
 * UC2 map. Active sensors as circles coloured by the selected variable: the latest reading,
 * or (spatial heat map) the mean over the filtered period, where the circle is also slightly
 * larger for higher values. Nothing is drawn between sensors: six approximate points cannot
 * support an interpolated surface (DECISIONS.md D-031).
 */
export default function SensorMap({
  sensors,
  variable,
  mode,
  onModeChange,
  periodMeans,
  selectedId,
  onSelect,
}: Props) {
  const active = sensors.filter(
    (s) => s.status === "Active" && s.latitude !== null && s.longitude !== null,
  );
  const values = active
    .map((s) => valueFor(s, variable.variable, mode, periodMeans))
    .filter((v): v is number => typeof v === "number");
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 0;

  return (
    <section aria-labelledby="map-title" className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="map-title" className="text-lg font-semibold">
          Sensor map
        </h2>
        <div
          role="radiogroup"
          aria-label="Colour the map by"
          className="flex rounded border border-slate-400 text-sm"
        >
          {(
            [
              ["latest", "Latest reading"],
              ["mean", "Period mean"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={mode === value}
              onClick={() => onModeChange(value)}
              className={`px-2 py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 ${
                mode === value
                  ? "bg-sky-800 text-white"
                  : "hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="h-[340px] overflow-hidden rounded border border-slate-300 dark:border-slate-700">
        <MapContainer center={CENTRE} zoom={13} scrollWheelZoom={false} className="h-full w-full">
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          />
          {active.map((s) => {
            const value = valueFor(s, variable.variable, mode, periodMeans);
            const measured = value !== undefined;
            const hasValue = typeof value === "number";
            const fill = hasValue ? rampColor(value, min, max) : "transparent";
            const radius =
              mode === "mean" && hasValue && max > min ? 8 + (6 * (value - min)) / (max - min) : 9;
            return (
              <CircleMarker
                key={s.sensor_id}
                center={[s.latitude as number, s.longitude as number]}
                radius={radius}
                eventHandlers={{ click: () => onSelect(s.sensor_id) }}
                pathOptions={{
                  color: selectedId === s.sensor_id ? "#0b0b0b" : hasValue ? "#ffffff" : "#898781",
                  weight: selectedId === s.sensor_id ? 3 : 2,
                  dashArray: s.location_verified ? undefined : "4 3",
                  fillColor: fill,
                  fillOpacity: hasValue ? 0.95 : 0,
                }}
              >
                <Tooltip>
                  {s.sensor_code} · {s.sensor_name}
                  <br />
                  {measured
                    ? formatValue(value, variable.unit, variable.variable)
                    : `Does not measure ${variable.label}`}
                  {!s.location_verified && (
                    <>
                      <br />
                      Location unverified
                    </>
                  )}
                </Tooltip>
              </CircleMarker>
            );
          })}
        </MapContainer>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-700 dark:text-slate-300">
        {values.length > 0 && (
          <span className="flex items-center gap-2">
            <span>{formatValue(min, variable.unit, variable.variable)}</span>
            <span
              aria-hidden="true"
              className="h-3 w-28 rounded"
              style={{ background: `linear-gradient(to right, ${SEQUENTIAL.join(", ")})` }}
            />
            <span>{formatValue(max, variable.unit, variable.variable)}</span>
            <span className="text-slate-600 dark:text-slate-400">
              ({mode === "latest" ? "latest reading" : "mean of the filtered period"},{" "}
              {variable.label})
            </span>
          </span>
        )}
        <span className="flex items-center gap-1">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-full border-2 border-dashed border-slate-500"
          />
          Location unverified
          <InfoTip label="an unverified location" text={GLOSSARY.unverified} />
        </span>
        <span className="flex items-center gap-1">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-3 rounded-full border-2 border-slate-400"
          />
          Hollow = does not measure {variable.label}
        </span>
      </div>

      <ul aria-label="Sensors on the map" className="grid grid-cols-1 gap-1 sm:grid-cols-2">
        {active.map((s) => {
          const value = valueFor(s, variable.variable, mode, periodMeans);
          return (
            <li key={s.sensor_id}>
              <button
                type="button"
                onClick={() => onSelect(s.sensor_id)}
                aria-pressed={selectedId === s.sensor_id}
                className={`w-full rounded border px-2 py-1 text-left text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 ${
                  selectedId === s.sensor_id
                    ? "border-sky-800 bg-sky-50 dark:bg-slate-800"
                    : "border-slate-300 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
                }`}
              >
                <span className="font-medium">{s.sensor_code}</span>{" "}
                <span className="text-slate-600 dark:text-slate-400">
                  {value === undefined
                    ? "not measured"
                    : formatValue(value, variable.unit, variable.variable)}
                </span>
                {!s.location_verified && (
                  <span className="ml-1 whitespace-nowrap rounded bg-amber-100 px-1 text-xs text-amber-900">
                    unverified
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
