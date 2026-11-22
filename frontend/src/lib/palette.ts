/**
 * Colours by the job they do (data-viz method; validated palette, DECISIONS.md D-031).
 * - identity: a sensor's categorical slot is fixed by its position in the full sensor
 *   list sorted by code, so a filter never repaints the survivors;
 * - magnitude: one blue ramp, light (low) -> dark (high).
 */
export const SERIES_SLOTS = 8;

export function seriesColor(slot: number): string {
  return `var(--series-${(slot % SERIES_SLOTS) + 1})`;
}

/** sensor_code -> slot, from the complete sensor list (not the filtered one). */
export function slotsByCode(codes: string[]): Record<string, number> {
  return Object.fromEntries([...codes].sort().map((code, i) => [code, i]));
}

/** Sequential blue ramp, steps 150 -> 700 of the reference palette. */
export const SEQUENTIAL = [
  "#b7d3f6",
  "#9ec5f4",
  "#86b6ef",
  "#6da7ec",
  "#5598e7",
  "#3987e5",
  "#2a78d6",
  "#256abf",
  "#1c5cab",
  "#184f95",
  "#104281",
  "#0d366b",
];

/** Ramp colour for a value inside [min, max] (equal-width bins). */
export function rampColor(value: number, min: number, max: number): string {
  if (!(max > min)) return SEQUENTIAL[Math.floor(SEQUENTIAL.length / 2)];
  const position = (value - min) / (max - min);
  const index = Math.min(
    SEQUENTIAL.length - 1,
    Math.max(0, Math.floor(position * SEQUENTIAL.length)),
  );
  return SEQUENTIAL[index];
}

/** Text colour that stays readable on a ramp cell. */
export function inkOn(fill: string): string {
  return SEQUENTIAL.indexOf(fill) >= 6 ? "#ffffff" : "#0b0b0b";
}
