import { useId, useState } from "react";

/** Plain-English explanations for non-specialists (usability NFR). */
export const GLOSSARY = {
  pm25: "PM2.5 is fine particulate matter smaller than 2.5 micrometres, mostly from vehicles, wood smoke and bushfires. It can travel deep into the lungs.",
  pm10: "PM10 is particulate matter smaller than 10 micrometres, such as dust and pollen.",
  nepm: "The National Environment Protection Measure (NEPM) for Ambient Air Quality sets Australia's air-quality standards. For PM2.5 the 24-hour standard is 25 µg/m³; for PM10 it is 50 µg/m³.",
  completeness:
    "Completeness is the share of expected readings the sensor actually sent. An average from less than 75% of the expected readings is shown greyed out and is not compared with standards.",
  flagged:
    "Flagged readings are kept but marked as suspicious: sudden particle spikes (which may be real smoke events) and temperature values frozen for hours. Excluding them gives a cleaner picture of typical conditions.",
  unverified:
    "The sensor's map position is an approximate placeholder that has not yet been confirmed with the council.",
} as const;

export default function InfoTip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative inline-block align-middle">
      <button
        type="button"
        aria-label={`What is ${label}?`}
        aria-expanded={open}
        aria-describedby={open ? id : undefined}
        onClick={() => setOpen((o) => !o)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="ml-1 inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-400 text-xs leading-none text-slate-700 hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-600 dark:text-slate-200 dark:hover:bg-slate-800"
      >
        ?
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute left-0 top-6 z-[1000] w-72 rounded border border-slate-300 bg-white p-2 text-sm font-normal text-slate-800 shadow-lg dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
        >
          {text}
        </span>
      )}
    </span>
  );
}
