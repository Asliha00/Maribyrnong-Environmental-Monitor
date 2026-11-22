import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listThresholds, updateThreshold, type AdminThreshold } from "../../api/admin";
import { ErrorMessage, Loading } from "../StatusMessage";

const field = "mt-1 w-full rounded border border-slate-400 px-2 py-1.5 text-sm dark:bg-slate-900";
const when = (iso: string | null) =>
  iso
    ? new Intl.DateTimeFormat("en-AU", {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: "Australia/Melbourne",
      }).format(new Date(iso))
    : "";

/** Threshold management (§4.5, risk R24): change a value with a reason; full change log. */
export default function AdminThresholds() {
  const qc = useQueryClient();
  const listing = useQuery({ queryKey: ["admin", "thresholds"], queryFn: listThresholds });
  const [editing, setEditing] = useState<AdminThreshold | null>(null);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");

  const save = useMutation({
    mutationFn: () =>
      updateThreshold((editing as AdminThreshold).threshold_id, Number(value), reason.trim()),
    onSuccess: (r) => {
      qc.setQueryData(["admin", "thresholds"], { thresholds: r.thresholds, history: r.history });
      qc.invalidateQueries({ queryKey: ["exceedances"] });
      qc.invalidateQueries({ queryKey: ["meta"] });
      setNotice(r.message);
      setEditing(null);
    },
  });

  if (listing.isPending) return <Loading label="Loading thresholds…" />;
  if (listing.isError)
    return <ErrorMessage error={listing.error} onRetry={() => listing.refetch()} />;
  const names = Object.fromEntries(listing.data.thresholds.map((t) => [t.threshold_id, t.label]));

  return (
    <section aria-labelledby="thresholds-title" className="space-y-4">
      <h2 id="thresholds-title" className="text-xl font-semibold">
        Thresholds
      </h2>
      <p className="max-w-prose text-sm text-slate-700 dark:text-slate-300">
        Changing a value recalculates which days exceed it, from valid daily data only. Every change
        is kept in the change log below with its reason.
      </p>
      <p role="status" className="text-sm text-emerald-800 dark:text-emerald-300">
        {notice}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Thresholds</caption>
          <thead className="border-b border-slate-400">
            <tr>
              <th scope="col" className="py-2 pr-3">
                Threshold
              </th>
              <th scope="col" className="pr-3">
                Applies to
              </th>
              <th scope="col" className="pr-3">
                Value
              </th>
              <th scope="col" className="pr-3">
                Days exceeded
              </th>
              <th scope="col" className="pr-3">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {listing.data.thresholds.map((t) => (
              <tr
                key={t.threshold_id}
                className="border-b border-slate-200 align-top dark:border-slate-800"
              >
                <th scope="row" className="py-2 pr-3 font-normal">
                  <span className="font-medium">{t.label}</span>
                  {t.source && (
                    <span className="block text-slate-600 dark:text-slate-400">{t.source}</span>
                  )}
                </th>
                <td className="pr-3">
                  {t.variable_label}, {t.statistic}
                </td>
                <td className="pr-3 whitespace-nowrap">
                  {t.operator} {t.value} {t.unit}
                </td>
                <td className="pr-3">{t.exceedance_days}</td>
                <td className="pr-3">
                  <button
                    type="button"
                    className="underline"
                    aria-label={`Change ${t.label}`}
                    onClick={() => {
                      save.reset();
                      setEditing(t);
                      setValue(String(t.value));
                      setReason("");
                    }}
                  >
                    Change
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && (
        <form
          aria-label={`Change ${editing.label}`}
          className="grid max-w-xl gap-3 rounded border border-slate-300 p-4 dark:border-slate-700"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <h3 className="font-semibold">Change “{editing.label}”</h3>
          <label className="text-sm">
            New value ({editing.unit})
            <input
              type="number"
              step="any"
              min={0}
              required
              className={field}
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </label>
          <label className="text-sm">
            Reason for the change (required, kept in the change log)
            <textarea
              required
              minLength={10}
              maxLength={500}
              rows={2}
              className={field}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          {save.error && <ErrorMessage error={save.error} />}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={save.isPending}
              className="rounded bg-sky-700 px-4 py-2 text-sm font-medium text-white hover:bg-sky-800 disabled:opacity-60"
            >
              Save and recalculate
            </button>
            <button
              type="button"
              onClick={() => setEditing(null)}
              className="rounded border border-slate-400 px-4 py-2 text-sm"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      <h3 className="pt-2 text-lg font-semibold">Change log</h3>
      {listing.data.history.length === 0 ? (
        <p className="text-sm text-slate-600 dark:text-slate-400">
          No threshold has been changed yet.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <caption className="sr-only">Threshold change log, newest first</caption>
            <thead className="border-b border-slate-400">
              <tr>
                <th scope="col" className="py-2 pr-3">
                  When
                </th>
                <th scope="col" className="pr-3">
                  Threshold
                </th>
                <th scope="col" className="pr-3">
                  Change
                </th>
                <th scope="col" className="pr-3">
                  Reason
                </th>
                <th scope="col" className="pr-3">
                  By
                </th>
              </tr>
            </thead>
            <tbody>
              {listing.data.history.map((h) => (
                <tr
                  key={h.history_id}
                  className="border-b border-slate-200 align-top dark:border-slate-800"
                >
                  <td className="py-2 pr-3 whitespace-nowrap">{when(h.changed_at)}</td>
                  <td className="pr-3">{names[h.threshold_id] ?? `#${h.threshold_id}`}</td>
                  <td className="pr-3 whitespace-nowrap">
                    {h.old_value} → {h.new_value}
                  </td>
                  <td className="pr-3">{h.reason}</td>
                  <td className="pr-3">{h.changed_by ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
