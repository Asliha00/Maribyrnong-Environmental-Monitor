/** Header labels for the two roles in the proposal's use cases (DECISIONS.md D-035).
 *  "General User" (retired, kept only for old records) is treated as the Analyst. */
const ROLE_LABELS: Record<string, string> = {
  "System Administrator": "Administrator",
  "Environmental Analyst": "Analyst",
  "General User": "Analyst",
};

export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}
