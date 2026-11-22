import { Link } from "react-router";
import type { Sensor } from "../api/data";
import { formatMelbourne, formatNumber, formatValue } from "../lib/format";
import InfoTip, { GLOSSARY } from "./InfoTip";

/** UC2 sensor panel: name, land use, latest readings with units, last updated (local
 * time), completeness badge, data-quality notes and a link to the history page. */
export default function SensorPanel({
  sensor,
  variable,
  onClose,
}: {
  sensor: Sensor;
  variable: string;
  onClose: () => void;
}) {
  const completeness = sensor.completeness[variable];
  const pct = completeness?.avg_daily_pct ?? null;
  const badge =
    pct === null
      ? "bg-slate-200 text-slate-800"
      : pct >= 75
        ? "bg-green-100 text-green-900"
        : "bg-amber-100 text-amber-900";
  return (
    <section
      aria-labelledby="sensor-panel-title"
      className="space-y-3 rounded border border-slate-300 p-4 dark:border-slate-700"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 id="sensor-panel-title" className="text-lg font-semibold">
            {sensor.sensor_name}
          </h2>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {sensor.sensor_code} · {sensor.land_use} · {sensor.status}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close sensor details"
          className="rounded px-2 py-1 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:hover:bg-slate-800"
        >
          ✕
        </button>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        {!sensor.location_verified && (
          <span className="rounded bg-amber-100 px-2 py-0.5 text-amber-900">
            Location unverified
            <InfoTip label="an unverified location" text={GLOSSARY.unverified} />
          </span>
        )}
        {completeness !== undefined && (
          <span className={`rounded px-2 py-0.5 ${badge}`}>
            Completeness {pct === null ? "unknown" : `${formatNumber(pct)}%`}
            {completeness &&
              ` (${completeness.valid_days} of ${completeness.days_with_data} days valid)`}
            <InfoTip label="completeness" text={GLOSSARY.completeness} />
          </span>
        )}
      </div>

      <div>
        <h3 className="text-sm font-medium">Latest readings</h3>
        <p className="text-xs text-slate-600 dark:text-slate-400">
          Last updated {formatMelbourne(sensor.latest?.ts_utc)} (Melbourne time)
        </p>
        <table className="mt-1 w-full text-sm">
          <tbody>
            {sensor.variables.map((v) => (
              <tr key={v.variable} className="border-t border-slate-200 dark:border-slate-800">
                <th scope="row" className="py-1 text-left font-normal">
                  {v.label}
                </th>
                <td className="py-1 text-right tabular-nums">
                  {formatValue(sensor.latest?.values[v.variable], v.unit, v.variable)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sensor.quality_notes.length > 0 && (
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-700 dark:text-slate-300">
          {sensor.quality_notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      <Link
        to={`/sensors/${sensor.sensor_id}`}
        className="inline-block text-sm font-medium underline"
      >
        View this sensor&apos;s history
      </Link>
    </section>
  );
}
