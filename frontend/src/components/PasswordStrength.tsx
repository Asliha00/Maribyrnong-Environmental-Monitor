/**
 * Strength meter for the password-change screen (UC1 / SEC-05). Guidance only: the
 * server enforces the real policy (length, common-password list, no name/email).
 */
export const MIN_LENGTH = 12;
const LABELS = ["Too short", "Weak", "Fair", "Good", "Strong"] as const;

export function strengthScore(password: string): number {
  if (password.length < MIN_LENGTH) return 0;
  let score = 1;
  if (password.length >= 16) score += 1;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(password)).length;
  if (classes >= 3) score += 1;
  if (classes === 4 || password.length >= 20) score += 1;
  return Math.min(score, 4);
}

export function strengthLabel(password: string): string {
  return LABELS[strengthScore(password)];
}

const COLOURS = ["bg-red-700", "bg-red-700", "bg-amber-600", "bg-sky-700", "bg-green-700"];

export default function PasswordStrength({ password }: { password: string }) {
  const score = strengthScore(password);
  return (
    <div className="mt-2" aria-live="polite">
      <div
        className="h-2 w-full rounded bg-slate-200 dark:bg-slate-700"
        role="meter"
        aria-label="Password strength"
        aria-valuemin={0}
        aria-valuemax={4}
        aria-valuenow={score}
        aria-valuetext={LABELS[score]}
      >
        <div
          className={`h-2 rounded ${COLOURS[score]}`}
          style={{ width: `${(score / 4) * 100}%` }}
        />
      </div>
      <p className="mt-1 text-sm">
        Strength: <strong>{LABELS[score]}</strong>
        {password.length > 0 && password.length < MIN_LENGTH
          ? ` (${MIN_LENGTH - password.length} more characters needed)`
          : ""}
      </p>
    </div>
  );
}
