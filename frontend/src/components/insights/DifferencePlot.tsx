import type { Comparison } from "../../api/insights";

export type DifferenceRow = {
  label: string;
  sublabel?: string;
  value: Comparison | null;
  badge?: string;
};

/** Signed words for a difference, so meaning never depends on colour alone. */
export function describeDifference(
  c: Comparison | null,
  unit: string,
  words: [string, string] = ["above", "below"],
) {
  if (!c || c.difference === null) return "not enough data";
  const amount = `${Math.abs(c.difference).toFixed(2)} ${unit}`;
  const side = c.difference >= 0 ? words[0] : words[1];
  const sure = c.direction === "no clear change" ? " (not distinguishable from zero)" : "";
  return `${amount} ${side}${sure}`;
}

/**
 * Dot-and-whisker chart of differences from the other sites, with the 95% interval and a
 * zero line. Diverging colours (data-viz method): warm red above zero, cool blue below, grey
 * when the interval crosses zero; every row also says it in words.
 */
export default function DifferencePlot({
  rows,
  unit,
  words,
}: {
  rows: DifferenceRow[];
  unit: string;
  words?: [string, string];
}) {
  const shown = rows.filter((r) => r.value && r.value.difference !== null);
  const extent = Math.max(
    0.1,
    ...shown.flatMap((r) => [
      Math.abs(r.value!.low ?? r.value!.difference!),
      Math.abs(r.value!.high ?? 0),
    ]),
  );
  const width = 640;
  const left = 190;
  const plot = width - left - 170;
  const row = 34;
  const x = (v: number) => left + plot / 2 + (v / extent) * (plot / 2);
  const colour = (c: Comparison) =>
    c.direction === "rising"
      ? "var(--diverging-warm)"
      : c.direction === "falling"
        ? "var(--diverging-cool)"
        : "var(--chart-muted)";
  return (
    <svg
      viewBox={`0 0 ${width} ${shown.length * row + 30}`}
      className="w-full max-w-3xl"
      role="img"
      aria-label={shown
        .map((r) => `${r.label}: ${describeDifference(r.value, unit, words)}`)
        .join("; ")}
    >
      <line x1={x(0)} x2={x(0)} y1={0} y2={shown.length * row + 6} stroke="var(--chart-axis)" />
      <text
        x={x(0)}
        y={shown.length * row + 22}
        textAnchor="middle"
        className="fill-[var(--chart-ink-2)] text-[11px]"
      >
        same as the others
      </text>
      {shown.map((r, i) => {
        const c = r.value!;
        const y = i * row + 18;
        return (
          <g key={r.label}>
            <text
              x={left - 10}
              y={y + 4}
              textAnchor="end"
              className="fill-[var(--chart-ink)] text-[12px]"
            >
              {r.label}
              {r.badge ? ` (${r.badge})` : ""}
            </text>
            {c.low !== null && c.high !== null && (
              <line x1={x(c.low)} x2={x(c.high)} y1={y} y2={y} stroke={colour(c)} strokeWidth={2} />
            )}
            <circle
              cx={x(c.difference!)}
              cy={y}
              r={5}
              fill={colour(c)}
              stroke="var(--chart-surface)"
              strokeWidth={2}
            />
            <text x={left + plot + 10} y={y + 4} className="fill-[var(--chart-ink-2)] text-[11px]">
              {c.difference! >= 0 ? "+" : ""}
              {c.difference!.toFixed(2)} {unit} · {c.days} days
            </text>
          </g>
        );
      })}
    </svg>
  );
}
