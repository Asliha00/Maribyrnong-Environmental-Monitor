import type { ReadingsResult } from "../api/data";
import { formatNumber, formatValue } from "../lib/format";
import InfoTip, { GLOSSARY } from "./InfoTip";

/** UC2 visualisation 5: mean / min / max / completeness for the whole selection. */
export default function SummaryCards({ result }: { result: ReadingsResult }) {
  const s = result.summary;
  const fmt = (v: number | null) => formatValue(v, result.unit, result.variable);
  const cards = [
    { label: "Mean", value: fmt(s.mean), note: `${result.label}, all selected sensors` },
    { label: "Minimum", value: fmt(s.min), note: "lowest bucket value" },
    { label: "Maximum", value: fmt(s.max), note: "highest bucket value" },
    {
      label: "Completeness",
      value:
        s.completeness_pct === null ? "Not applicable" : `${formatNumber(s.completeness_pct)}%`,
      note:
        s.completeness_pct === null
          ? "raw readings"
          : `${s.valid_buckets} of ${s.buckets} periods at least 75% complete`,
      tip: true,
    },
  ];
  return (
    <section
      aria-label="Summary for the selection"
      className="grid grid-cols-2 gap-2 lg:grid-cols-4"
    >
      {cards.map((c) => (
        <div key={c.label} className="rounded border border-slate-300 p-3 dark:border-slate-700">
          <p className="text-sm text-slate-600 dark:text-slate-400">
            {c.label}
            {c.tip && <InfoTip label="completeness" text={GLOSSARY.completeness} />}
          </p>
          <p className="text-2xl font-semibold">{c.value}</p>
          <p className="text-xs text-slate-600 dark:text-slate-400">{c.note}</p>
        </div>
      ))}
    </section>
  );
}
