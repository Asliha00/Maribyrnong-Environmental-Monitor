import { useId, useMemo, useState, type FormEvent } from "react";
import type { Filters, Meta, Resolution, Sensor } from "../api/data";
import { validateFilters } from "../lib/filters";
import InfoTip, { GLOSSARY } from "./InfoTip";

export const SENSOR_NOT_FOUND = "Sensor not found.";

const RESOLUTIONS: { value: Resolution; label: string }[] = [
  { value: "hour", label: "Hourly" },
  { value: "day", label: "Daily" },
  { value: "month", label: "Monthly" },
  { value: "season", label: "Seasonal" },
  { value: "raw", label: "Raw (≤ 7 days)" },
];

const fieldClass =
  "mt-1 w-full rounded border border-slate-400 bg-white px-2 py-1.5 text-slate-900 dark:bg-slate-800 dark:text-slate-100";

type Props = {
  meta: Meta;
  sensors: Sensor[];
  applied: Filters;
  busy: boolean;
  onApply: (filters: Filters) => void;
  onReset: () => void;
};

/** UC2 filter panel. Changes stay in a draft until "Apply Filter". */
export default function FilterPanel({ meta, sensors, applied, busy, onApply, onReset }: Props) {
  const [draft, setDraft] = useState<Filters>(applied);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const searchId = useId();
  // The parent re-mounts this panel (key) when the applied filters change, resetting the draft

  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    setDraft((d) => ({ ...d, [key]: value }));

  const matches = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    return sensors
      .filter(
        (s) =>
          !draft.sensorIds.includes(s.sensor_id) &&
          (s.sensor_code.toLowerCase().includes(q) || s.sensor_name.toLowerCase().includes(q)),
      )
      .slice(0, 6);
  }, [search, sensors, draft.sensorIds]);

  const addSensor = (id: number) => {
    set("sensorIds", [...draft.sensorIds, id]);
    setSearch("");
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    const problem = validateFilters(draft, meta);
    setError(problem);
    if (!problem) onApply(draft);
  }

  const variable = meta.variables.find((v) => v.variable === draft.variable);

  return (
    <form onSubmit={submit} aria-labelledby="filters-title" className="space-y-4" noValidate>
      <h2 id="filters-title" className="text-lg font-semibold">
        Filters
      </h2>

      <div>
        <label htmlFor="variable" className="block text-sm font-medium">
          Variable
        </label>
        <select
          id="variable"
          value={draft.variable}
          onChange={(e) => set("variable", e.target.value)}
          className={fieldClass}
        >
          {meta.variables.map((v) => (
            <option key={v.variable} value={v.variable}>
              {v.label} ({v.unit})
            </option>
          ))}
        </select>
        {variable && ["pm25", "pm10"].includes(variable.variable) && (
          <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
            {variable.label}
            <InfoTip label={variable.label} text={GLOSSARY[variable.variable as "pm25" | "pm10"]} />
            <span className="ml-2">Standard</span>
            <InfoTip label="the NEPM standard" text={GLOSSARY.nepm} />
          </p>
        )}
      </div>

      <fieldset>
        <legend className="text-sm font-medium">Time resolution</legend>
        <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
          {RESOLUTIONS.map((r) => (
            <label key={r.value} className="inline-flex items-center gap-1.5 text-sm">
              <input
                type="radio"
                name="resolution"
                value={r.value}
                checked={draft.resolution === r.value}
                onChange={() => set("resolution", r.value)}
              />
              {r.label}
            </label>
          ))}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-sm font-medium">Date range</legend>
        <div className="mt-1 grid grid-cols-2 gap-2">
          <label className="text-sm">
            From
            <input
              type="date"
              value={draft.start}
              min={meta.data_range.first_day ?? undefined}
              max={meta.data_range.last_day ?? undefined}
              onChange={(e) => set("start", e.target.value)}
              className={fieldClass}
            />
          </label>
          <label className="text-sm">
            To
            <input
              type="date"
              value={draft.end}
              min={meta.data_range.first_day ?? undefined}
              max={meta.data_range.last_day ?? undefined}
              onChange={(e) => set("end", e.target.value)}
              className={fieldClass}
            />
          </label>
        </div>
        <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
          Data available {meta.data_range.first_day} to {meta.data_range.last_day}.
        </p>
      </fieldset>

      <fieldset>
        <legend className="text-sm font-medium">Land use</legend>
        <p className="text-xs text-slate-600 dark:text-slate-400">None ticked = all land uses.</p>
        <div className="mt-1 grid grid-cols-1 gap-1 sm:grid-cols-2">
          {meta.land_uses.map((land) => (
            <label key={land} className="inline-flex items-center gap-1.5 text-sm">
              <input
                type="checkbox"
                checked={draft.landUses.includes(land)}
                onChange={(e) =>
                  set(
                    "landUses",
                    e.target.checked
                      ? [...draft.landUses, land]
                      : draft.landUses.filter((l) => l !== land),
                  )
                }
              />
              {land}
            </label>
          ))}
        </div>
      </fieldset>

      <div>
        <label htmlFor={searchId} className="block text-sm font-medium">
          Sensors
        </label>
        <p className="text-xs text-slate-600 dark:text-slate-400">
          Search by code or name. None chosen = all sensors.
        </p>
        <input
          id={searchId}
          type="search"
          autoComplete="off"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (matches[0]) addSensor(matches[0].sensor_id);
            }
          }}
          aria-describedby={`${searchId}-status`}
          className={fieldClass}
        />
        <div id={`${searchId}-status`} aria-live="polite">
          {search.trim() && matches.length === 0 && (
            <p className="mt-1 text-sm text-red-800 dark:text-red-300">{SENSOR_NOT_FOUND}</p>
          )}
        </div>
        {matches.length > 0 && (
          <ul
            aria-label="Matching sensors"
            className="mt-1 rounded border border-slate-300 dark:border-slate-700"
          >
            {matches.map((s) => (
              <li key={s.sensor_id}>
                <button
                  type="button"
                  onClick={() => addSensor(s.sensor_id)}
                  className="w-full px-2 py-1 text-left text-sm hover:bg-slate-100 focus:outline-none focus-visible:bg-slate-100 dark:hover:bg-slate-800 dark:focus-visible:bg-slate-800"
                >
                  <span className="font-medium">{s.sensor_code}</span> · {s.sensor_name}
                </button>
              </li>
            ))}
          </ul>
        )}
        {draft.sensorIds.length > 0 && (
          <ul aria-label="Chosen sensors" className="mt-2 flex flex-wrap gap-1">
            {draft.sensorIds.map((id) => {
              const s = sensors.find((x) => x.sensor_id === id);
              return (
                <li key={id}>
                  <button
                    type="button"
                    onClick={() =>
                      set(
                        "sensorIds",
                        draft.sensorIds.filter((x) => x !== id),
                      )
                    }
                    aria-label={`Remove ${s?.sensor_code ?? id}`}
                    className="rounded-full bg-slate-200 px-2 py-0.5 text-xs hover:bg-slate-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:bg-slate-700 dark:hover:bg-slate-600"
                  >
                    {s?.sensor_code ?? id} ✕
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={draft.excludeFlagged}
          onChange={(e) => set("excludeFlagged", e.target.checked)}
        />
        Exclude flagged readings
        <InfoTip label="a flagged reading" text={GLOSSARY.flagged} />
      </label>

      {error && (
        <p role="alert" className="rounded bg-red-100 p-2 text-sm text-red-900">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded bg-sky-800 px-4 py-2 font-medium text-white hover:bg-sky-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 disabled:opacity-50"
        >
          Apply Filter
        </button>
        <button
          type="button"
          onClick={() => {
            setError(null);
            setSearch("");
            onReset();
          }}
          className="rounded border border-slate-400 px-4 py-2 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:hover:bg-slate-800"
        >
          Reset
        </button>
      </div>
    </form>
  );
}
